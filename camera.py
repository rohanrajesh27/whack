from __future__ import annotations

import os
import re
import sys
from typing import Any

import cv2
import numpy as np
import pytesseract
import requests
import torch
from dotenv import load_dotenv
from PIL import Image
from torchvision import models, transforms

from ripeness_keywords import infer_ripeness_score

load_dotenv()

RECEIVE_DATA_URL = "https://whack-wlr9.onrender.com/receive-data"

# ── Model setup (loaded once at startup) ────────────────────────────────────

# Image classification (ResNet-50 via torchvision)
print("Loading classification model (ResNet-50)...")
resnet = models.resnet50(weights=models.ResNet50_Weights.IMAGENET1K_V1)
resnet.eval()
imagenet_labels: list[str] = models.ResNet50_Weights.IMAGENET1K_V1.meta["categories"]

resnet_transform = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])

# ── Camera capture ───────────────────────────────────────────────────────────

def capture_frame(prompt: str = "Capture") -> Any:
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Could not open camera (index 0).", file=sys.stderr)
        sys.exit(1)

    print(f"{prompt}\nPress SPACE to capture, Q to quit.")
    frame = None
    while True:
        ok, current = cap.read()
        if not ok:
            print("Failed to read from camera.", file=sys.stderr)
            break
        cv2.imshow(f"{prompt} (SPACE = grab, Q = quit)", current)
        key = cv2.waitKey(1) & 0xFF
        if key == ord(" "):
            frame = current.copy()
            break
        if key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

    if frame is None:
        print("No frame captured.", file=sys.stderr)
        sys.exit(1)
    return frame


def frame_to_pil(frame: Any) -> Image.Image:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)

# ── Analysis functions ───────────────────────────────────────────────────────

def classify_image(image: Image.Image, top_k: int = 5) -> list[tuple[str, float]]:
    """Return the top-k ImageNet class predictions using ResNet-50."""
    tensor = resnet_transform(image).unsqueeze(0)
    with torch.no_grad():
        logits = resnet(tensor)
    probs  = torch.softmax(logits, dim=1)[0]
    top_k_probs, top_k_indices = torch.topk(probs, top_k)
    return [
        (imagenet_labels[idx.item()], round(prob.item() * 100, 2))
        for prob, idx in zip(top_k_probs, top_k_indices)
    ]


def infer_product_name(
    caption: str,
    top_classes: list[tuple[str, float]],
) -> str:
    """Infer a likely grocery product name from classifier-derived text + ImageNet labels."""
    caption_lower = caption.lower()
    grocery_items = [
        "banana",
        "apple",
        "orange",
        "avocado",
        "tomato",
        "lettuce",
        "cucumber",
        "strawberry",
        "grape",
        "pear",
        "peach",
        "mango",
        "pineapple",
        "broccoli",
        "carrot",
    ]

    for item in grocery_items:
        if item in caption_lower:
            return item.title()

    if top_classes:
        top_label = top_classes[0][0].lower()
        for item in grocery_items:
            if item in top_label:
                return item.title()
        return top_label.title()

    return "Unknown product"


def preprocess_for_ocr(image: Image.Image) -> Image.Image:
    """Clean up a phone photo before sending it to Tesseract."""
    img = np.array(image)
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    gray = cv2.fastNlMeansDenoising(gray, h=10)
    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        10,
    )
    kernel = np.ones((2, 2), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    return Image.fromarray(binary)


def extract_text(image: Image.Image) -> str:
    """Run Tesseract OCR with optimised config for product labels."""
    prepped = preprocess_for_ocr(image)
    custom_config = r"--oem 3 --psm 11"
    return pytesseract.image_to_string(prepped, config=custom_config)


# Product code: ***-*#-*#-###  (* = alphanumeric, # = digit) after upper-casing OCR text.
PRODUCT_CODE_STRICT = re.compile(r"\b([A-Z0-9]{3}-[A-Z0-9]\d-[A-Z0-9]\d-\d{3})\b")
PRODUCT_CODE_FUZZY = re.compile(
    r"\b([A-Z0-9]{3})[^A-Z0-9]+([A-Z0-9]\d)[^A-Z0-9]+([A-Z0-9]\d)[^A-Z0-9]+(\d{3})\b"
)
PRODUCT_CODE_COMPACT = re.compile(r"([A-Z0-9]{3})([A-Z0-9]\d)([A-Z0-9]\d)(\d{3})")


def extract_product_code(raw_text: str) -> str | None:
    """Find a code matching ***-*#-*#-###. Swaps I->1 first since Tesseract often misreads 1 as I."""
    normalised = raw_text.upper().replace("I", "1")

    m = PRODUCT_CODE_STRICT.search(normalised)
    if m:
        return m.group(1)

    m = PRODUCT_CODE_FUZZY.search(normalised)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"

    compact = re.sub(r"[\s\-\._|/\\]+", "", normalised)
    m = PRODUCT_CODE_COMPACT.search(compact)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"

    return None


def format_analysis_report(
    caption:      str,
    ripeness:     int,
    top_classes:  list[tuple[str, float]],
    raw_text:     str,
    product_code: str | None,
) -> str:
    """Assemble a human-readable analysis report."""
    lines: list[str] = []

    lines.append("=" * 60)
    lines.append("           OBJECT + TEXT ANALYSIS REPORT")
    lines.append("=" * 60)
    lines.append("  Single capture: ResNet-50 classification + Tesseract OCR on the same frame")

    lines.append("\n[1] CLASSIFIER TEXT (ResNet labels, used for name + ripeness hints)")
    lines.append("-" * 40)
    lines.append(f"  {caption}")

    lines.append("\n[2] TOP IMAGE CLASSIFICATIONS (ResNet-50 / ImageNet)")
    lines.append("-" * 40)
    for rank, (label, pct) in enumerate(top_classes, 1):
        lines.append(f"  {rank}. {label:<30} {pct:>6.2f}%")

    lines.append("\n[3] GROCERY RIPENESS ASSESSMENT")
    lines.append("-" * 40)
    lines.append(f"  {ripeness} / 5")

    lines.append("\n[4] OBJECT DETECTION")
    lines.append("-" * 40)
    lines.append("  (Not used — pipeline is one frame through ResNet + Tesseract only.)")

    lines.append("\n[5] EXTRACTED TEXT (Tesseract OCR)")
    lines.append("-" * 40)
    cleaned = raw_text.strip()
    lines.append(cleaned if cleaned else "  (no text detected)")

    lines.append("\n[6] PRODUCT CODE  (format: ***-*#-*#-###; * = alnum, # = digit)")
    lines.append("-" * 40)
    if product_code:
        lines.append(f"  ✔  Found: {product_code}")
    else:
        lines.append("  ✘  No matching product code found in OCR output.")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)

# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    frame = capture_frame("Capture: product + label in one shot (SPACE)")
    image = frame_to_pil(frame)

    print("\nRunning analysis — please wait...\n")

    # Same PIL image: ImageNet classification (ResNet) + OCR (Tesseract).
    top_classes = classify_image(image, top_k=5)
    raw_text = extract_text(image)

    caption = ", ".join(label for label, _ in top_classes)
    ripeness_score = infer_ripeness_score(caption)
    product_code = extract_product_code(raw_text)

    product_name = infer_product_name(caption, top_classes)

    report = format_analysis_report(
        caption, ripeness_score, top_classes, raw_text, product_code
    )
    print(report)

    print(f"{product_name}, {ripeness_score}, {product_code or 'UNKNOWN'}")

    # POST JSON (flag must be first key). flag=1 → HTML confirmation + server log.
    body = {"flag": 1, "product_code": product_code, "ripeness_score": ripeness_score}
    try:
        response = requests.post(RECEIVE_DATA_URL, json=body, timeout=30)
        if response.status_code == 200:
            print("Server acknowledged (200).")
            ct = (response.headers.get("Content-Type") or "").lower()
            if "application/json" in ct:
                print("Server Response:", response.json())
            else:
                print("Server returned HTML page (length %s bytes)." % len(response.text))
        else:
            print(f"Failed to send data. Status code: {response.status_code}")
            print("Response:", response.text[:2000])
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")


if __name__ == "__main__":
    main()