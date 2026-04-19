// ============================================================================
// FreshTag ESP32 — shelf telemetry + LCD price (matches Flask /receive-data)
// ============================================================================
// Line 1 = shelf price (from JSON display_line_1, e.g. "$0.42").
// Line 2 = freshness / ripeness / weight hint (display_line_2).
//
// After a photo on the laptop (camera.py → flag=1), the backend updates
// ripeness on the lot. This sketch polls GET …/banana-display often so the
// LCD shows the new price without waiting for the next telemetry POST merge.
//
// Open this folder in Arduino IDE: firmware/FreshTagESP32/
// ============================================================================

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include "DHT.h"
#include "HX711.h"

// --- Wi‑Fi & backend (set before upload; do not commit secrets to git) -----
static const char* WIFI_SSID = "YOUR_WIFI_SSID";
static const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
// Origin only, no trailing slash (e.g. https://your-app.onrender.com)
static const char* BACKEND_ORIGIN = "https://your-app.onrender.com";
static const char* DEVICE_ID = "shelf_001";
// Must match a banana lot in Mongo (lot_code / lot_id), same as camera OCR target.
static const char* LOT_CODE = "ST1-I1-B1-334";

// --- Intervals --------------------------------------------------------------
static const unsigned long TELEMETRY_INTERVAL_MS = 3000;
static const unsigned long DISPLAY_POLL_MS = 1500;  // price refresh after laptop camera

// --- Hardware ---------------------------------------------------------------
#define DHTPIN 4
#define DHTTYPE DHT11
static const int LOADCELL_DOUT_PIN = 16;
static const int LOADCELL_SCK_PIN = 17;
static const float SCALE_FACTOR = 387.02f;
static const float ZERO_DEADBAND_G = 5.0f;

DHT dht(DHTPIN, DHTTYPE);
HX711 scale;
LiquidCrystal_I2C lcd(0x27, 16, 2);

static unsigned long lastTelemetryMs = 0;
static unsigned long lastDisplayMs = 0;

void displayLCD(const String& line1, const String& line2) {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(line1.substring(0, 16));
  lcd.setCursor(0, 1);
  lcd.print(line2.substring(0, 16));
}

bool httpsGETJson(const char* pathAndQuery, DynamicJsonDocument& outDoc, String& rawOut) {
  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  String url = String(BACKEND_ORIGIN) + pathAndQuery;
  http.begin(client, url);
  http.setTimeout(10000);
  int code = http.GET();
  rawOut = http.getString();
  http.end();
  if (code <= 0) return false;
  DeserializationError err = deserializeJson(outDoc, rawOut);
  return !err;
}

bool httpsPOSTJson(const char* path, const String& jsonBody, DynamicJsonDocument& outDoc, String& rawOut) {
  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  String url = String(BACKEND_ORIGIN) + path;
  http.begin(client, url);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(10000);
  int code = http.POST(jsonBody);
  rawOut = http.getString();
  http.end();
  if (code <= 0) return false;
  DeserializationError err = deserializeJson(outDoc, rawOut);
  return !err;
}

void applyDisplayFromJson(JsonObjectConst root) {
  if (!root.containsKey("display_line_1")) return;
  String line1 = root["display_line_1"].as<String>();
  String line2 = root.containsKey("display_line_2") ? root["display_line_2"].as<String>() : String("");
  displayLCD(line1, line2);
}

void pollBananaDisplay() {
  DynamicJsonDocument doc(512);
  String raw;
  String path = String("/receive-data/banana-display?lot_code=") + LOT_CODE;
  if (!httpsGETJson(path.c_str(), doc, raw)) {
    Serial.println("[DISPLAY] GET failed");
    return;
  }
  String st = doc["status"] | "";
  if (st != "success") {
    Serial.println("[DISPLAY] non-success: " + raw.substring(0, 120));
    return;
  }
  applyDisplayFromJson(doc.as<JsonObjectConst>());
  Serial.println("[DISPLAY] line1 (price): " + String(doc["display_line_1"] | ""));
}

void sendTelemetry() {
  float raw_weight = scale.is_ready() ? scale.get_units(5) : 0.0f;
  float temperature_c = dht.readTemperature();
  float humidity_pct = dht.readHumidity();
  float weight_grams = (fabs(raw_weight) <= ZERO_DEADBAND_G) ? 0.0f : raw_weight;

  if (isnan(temperature_c)) temperature_c = 25.0f;
  if (isnan(humidity_pct)) humidity_pct = 50.0f;

  StaticJsonDocument<256> doc;
  doc["flag"] = 0;
  doc["device_id"] = DEVICE_ID;
  doc["lot_code"] = LOT_CODE;
  doc["weight_grams"] = weight_grams;
  doc["temperature_c"] = temperature_c;
  doc["humidity_pct"] = humidity_pct;

  String payload;
  serializeJson(doc, payload);
  Serial.println("[SEND] " + payload);

  DynamicJsonDocument resp(768);
  String raw;
  if (!httpsPOSTJson("/receive-data", payload, resp, raw)) {
    Serial.println("[TELEM] POST failed");
    displayLCD("Network error", "retry...");
    return;
  }

  // Backend: display_line_1 = price only, line_2 = F/R/W after merge.
  if (resp.containsKey("display_line_1")) {
    applyDisplayFromJson(resp.as<JsonObjectConst>());
    Serial.println("[TELEM] LCD from POST response");
  } else {
    Serial.println("[TELEM] no display fields (check lot_code / merge)");
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);

  lcd.init();
  lcd.backlight();
  displayLCD("FreshTag boot", "Starting...");

  dht.begin();
  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
  scale.set_scale(SCALE_FACTOR);
  displayLCD("Tare in 3s", "Clear platform");
  delay(3000);
  scale.tare();

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  displayLCD("WiFi connect", WIFI_SSID);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  if (WiFi.status() != WL_CONNECTED) {
    displayLCD("WiFi FAILED", "Check creds");
    while (true) delay(1000);
  }
  displayLCD("WiFi OK", WiFi.localIP().toString().substring(0, 16));
  delay(1500);
  displayLCD("Price: ---", LOT_CODE);
}

void loop() {
  unsigned long now = millis();

  if (now - lastDisplayMs >= DISPLAY_POLL_MS) {
    lastDisplayMs = now;
    pollBananaDisplay();
  }

  if (now - lastTelemetryMs >= TELEMETRY_INTERVAL_MS) {
    lastTelemetryMs = now;
    sendTelemetry();
  }
}
