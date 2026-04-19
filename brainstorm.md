Rohan, Dane, Nick, Jonny

## Track 2: GW Global Food Institute

## Problem Statement 2
### Reimagining the Corner Store as a Healthy Food Hub

The George Washington University — Global Food Institute

---

## Operating reality: what a DC corner store actually is

Before we design anything, we ground ourselves in the real environment. Based on DC Central Kitchen's Healthy Corners program (the proven model referenced in the problem statement):

- **Small footprint.** Produce often lives on a single shelf and one small fridge (roughly 24" x 24" x 61").
- **Thin staffing.** Typically the owner plus one or two cashiers. No produce manager, no IT team.
- **Low-tech baseline.** Many stores use basic cash registers. POS integration should not be assumed.
- **Low price points.** Average suggested retail around $2.19 per item, priced at or below big-box grocery.
- **SNAP-driven customer base.** 86% of Healthy Corners partner stores accept SNAP. SNAP Match coupons ($5 for fruits and vegetables) are a core affordability lever.
- **Delivery cadence.** Healthy Corners delivers 1–3x per week, stores order by the unit.
- **What shoppers care about.** Freshness is the #1 quality signal (77% of shoppers, per AU's 2025 evaluation), followed by display appearance and quantity available. Price and variety are close behind.

**Design implication:** The solution has to work on a single produce shelf, with a single owner, no POS integration, alongside SNAP and SNAP Match, under a mission-aligned affordability ceiling.

---

## Our solution (working concept)

**Core insight**

Fresh food has a shelf life that changes daily, but corner stores price produce manually and have no low-cost way to markdown items before they spoil. Owners carry that risk in their head, which is one of the main reasons small stores hesitate to stock fresh produce in the first place.

**Proposed solution**

A shelf-edge freshness sensor and pricing display, purpose-built for the corner store (not the supermarket). It reads weight trend, volatile organic compounds, and storage conditions, computes a freshness score, and shows today's fair price on a small LCD right on the shelf. The owner does nothing. The shelf updates itself.

**How it works (draft workflow)**

1. **Item registration.** Owner scans or taps to register a delivery lot (e.g., "banana lot, delivered Monday"). Lowest-friction option is a QR scan from the DCCK delivery sheet or a manual button press.
2. **Continuous sensing.** ESP32 reads load cell (weight trend), Explore CCS811 (VOC/ethylene proxy for ripening), and DHT11 (temperature, humidity). Data is timestamped via Wi-Fi/NTP.
3. **Freshness score.** A weighted, rules-based score from 0 to 100 blends weight loss rate, VOC trend, and cumulative temperature/humidity exposure.
4. **Dynamic price.** Score maps to a price curve with a ceiling (never above the DCCK-aligned benchmark) and a floor (respects SNAP Match economics).
5. **Shelf display.** LCD1602 shows today's price. LEDs give an at-a-glance status (green/yellow/amber/red).
6. **Owner dashboard.** Weekly sales and waste summary auto-generated (mirrors the report DCCK currently produces by hand for partner stores).

**Value proposition (in the order that matters for a corner store owner)**

1. **Risk reduction.** Owners stock fresh produce more confidently because "day 8" bananas still sell at a fair markdown instead of being thrown out.
2. **Customer trust.** A visible, freshness-linked price signals honesty and respect, which builds the repeat shopping behavior that underpins a healthy store economy.
3. **Time savings.** Owners save minutes per day on manual markdowns and waste tracking.
4. **Automated scorecard data.** The sensor auto-populates several variables in the Healthy Corners Scorecard (sales, waste, variety, deliveries), giving program operators clean data they currently collect manually.

**SNAP and SNAP Match compatibility**

Every price shown has to work inside SNAP rules and alongside DCCK's SNAP Match produce-for-produce coupon model. Guardrails built into the pricing logic:
- **Mission ceiling.** Never price above a reference benchmark tied to big-box grocery.
- **Affordability floor.** Never price so low that SNAP Match coupon economics break.
- **Anti-gouging logic.** Price moves only downward from the anchor price as freshness declines. Prices do not float upward on supply shocks.

---

## Hardware (current inventory / ordered)

**Ordered (confirmed)**
- **Core system**
  - Elegoo UNO R3 starter kit (Arduino compatible)
  - Inland ESP32-WROOM-32D module (main board for MVP, Wi-Fi enabled)
- **Sensors (inputs)**
  - Inland electronic scale kit: 5kg load cell + HX711 (weight trend, ripeness proxy)
  - Inland CCS811 air quality sensor (VOC / ethylene proxy for ripening and spoilage)
- **Output / interface**
  - Inland 2-channel 5V relay module
- **Wiring**
  - Inland Dupont jumper wires (20cm, 3 pack)

**Also on hand / confirmed for demo**
- DHT11 temperature + humidity sensor (from Uno kit)
- LCD1602 screen (price + status display)
- LEDs (green/yellow/amber/red status indicators)
- Breadboard, resistors, basic electronics
- Webcam (optional, stretch goal for visual confirmation)

**Hardware notes and gaps**

- **Timekeeping.** ESP32 Wi-Fi/NTP for timestamps. RTC module only if Wi-Fi is unavailable at the demo site.
- **Item identification.** QR/barcode scan (phone camera) or a simple physical button on the device to register "new lot, day zero." Low friction for the owner.
- **Data logging.** Wi-Fi upload to our Flask backend (demo hosted on Render; MongoDB for persistence) for the dashboard. MicroSD as fallback where Wi-Fi is unreliable.

**Minimum viable hardware MVP (what we actually demo)**

ESP32 + load cell + HX711 + DHT11 + CCS811 + LCD1602 + status LEDs, running a freshness score that drives a live price on the shelf. Two fruits on stage: one fresh banana, one pre-aged banana. Judges watch the prices differ in real time.

---

## Opportunity Areas

### 1) Technology for Healthy Inventory

Tools that help store owners source, price, and manage fresh and nutritious food efficiently, built for the single-owner operating reality.

**Brainstorm ideas**
- **Shelf-edge dynamic pricing.** The core of our MVP. Freshness-linked price updates on an LCD at the shelf, no POS integration required.
- **Smart ordering.** Suggested order quantities for produce and dairy based on past sales, seasonality, and local demand patterns.
- **Spoilage and shrink tracking.** A daily waste log that auto-learns spoilage rates and improves future ordering. Our sensor populates this automatically.
- **Scorecard automation.** Auto-populate variables in the Healthy Corners Scorecard (sales, waste, variety, deliveries) from sensor data.
- **Phone-based scan-to-manage inventory.** Owner or staff uses a phone camera to register a lot, no extra hardware.
- **Margin plus freshness view.** Combine profit margin with a freshness score so owners see the financial picture at a glance.

**Key users**
- Store owners and managers (primary)
- Cashiers and staff (secondary, they execute the markdown at the register)
- Healthy Corners program staff (tertiary, they use the auto-populated scorecard data)

**Questions to answer**
- **Data availability.** Most small stores lack POS data. The sensor itself becomes the data source.
- **Cold chain.** Refrigeration is limited. The sensor has to work outside the fridge for bananas, onions, potatoes, and similar items, and inside for leafy greens and cut fruit.
- **Pricing constraints.** Margin thresholds have to reflect the DCCK affordability ceiling and SNAP Match economics.

---

### 2) Community-Centered Store Design

Make corner stores more engaging, culturally relevant, and responsive to local needs.

**Brainstorm ideas**
- **Community preference board.** In-store QR survey and lightweight voting on new items, results shared with owners.
- **Culturally relevant healthy swaps.** Recipe cards and ingredient bundles reflecting local cuisines (Ethiopian, West African, Caribbean, Latin American, depending on neighborhood).
- **Healthy grab-and-go zone.** Layout guidance and signage templates for tight spaces. DCCK has found grab-and-go items sell strongly.
- **Loyalty built around produce.** Rewards that emphasize healthy purchases, designed to stack cleanly with SNAP Match.
- **Community partner hours.** Schedule tool for pop-ups (WIC/SNAP support, nutrition demos, clinics).
- **Plain-language shelf tags.** Simple labels like "high fiber" and "low sugar," plus price-per-serving.

**Key users**
- Community members and shoppers
- Store owners
- Community organizations (clinics, schools, nonprofits, DCCK Store Navigators)

**Questions to answer**
- **Trust and engagement.** What incentives actually drive repeat healthy purchases in LILA neighborhoods?
- **Language and accessibility.** Which languages and literacy levels must signage and UX support?
- **Space constraints.** What is the smallest layout change a store can adopt and sustain?

---

### 3) Supply Chain Innovation

Improve access to affordable fresh food through better distribution and partnerships, modeled on what DCCK already does as a mission-driven wholesaler.

**Brainstorm ideas**
- **Group purchasing.** Co-op ordering across multiple corner stores to hit distributor minimums and reduce costs.
- **Micro-distribution hub.** A local hub that breaks down bulk produce into store-sized orders (the DCCK model).
- **Demand aggregation dashboard.** Show distributors and local farms consistent demand patterns to justify routes and better pricing.
- **Local producer partnerships.** Connect stores with nearby farms and urban gardens, predictable weekly order cycles.
- **Last-mile delivery coordination.** Optimize delivery windows and consolidate shipments to reduce spoilage.
- **SNAP/WIC alignment.** Highlight items that are benefit-eligible and move reliably, reducing owner risk.

**Key users**
- Distributors and wholesalers (including mission-driven ones like DCCK)
- Local producers
- Store owners
- City and NGO partners

**Questions to answer**
- **Minimum order and delivery cadence.** What are distributor constraints today for small-volume orders?
- **Cost drivers.** Where do costs spike (transport, storage, middlemen) and which lever is most impactful?
- **Reliability.** How do we ensure consistent supply?

---

## Pitch alignment: why this fits Problem Statement 2

| Problem statement ask | How our solution responds |
|---|---|
| Build on proven models of healthy food access in urban corner stores | Directly extends the DCCK Healthy Corners model by automating manual pricing and scorecard reporting |
| Design the next generation corner store experience for DC | Shelf-edge freshness sensor deployable on a single shelf, within the existing DCCK infrastructure |
| Serve both store owners and residents | Owner gets risk reduction and time savings; resident gets visible fairness and a lower price as freshness declines |
| Consider sustainability, scalability, equity | Low hardware cost, Wi-Fi enabled for fleet scaling, SNAP/SNAP Match compatible by design |
| Solution could be technology platform, service design, policy framework, community engagement, or a combination | We combine a hardware/software platform with a policy-aware pricing framework (affordability ceiling, anti-gouging floor) |

---

## Why this project is open source

**Mission fit.** Corner-store affordability and SNAP-related pricing depend on trust. Open code makes it clear how freshness signals become a price (rules, floors, ceilings) without hidden logic inside a vendor black box.

**The stack is built from open components, not proprietary vision APIs.** That keeps per-store and per-demo cost low and avoids tying the product to a paid cloud OCR or “AI label” contract.

| Layer | What we use | Why it matters for OSS |
|--------|----------------|-------------------------|
| **Web app & API** | [Flask](https://flask.palletsprojects.com/) (BSD-3-Clause) | Small footprint, easy for others to run locally or fork for their own Healthy Corners–style pilots. |
| **Data store** | [MongoDB](https://www.mongodb.com/) via [PyMongo](https://github.com/mongodb/mongo-python-driver) (Apache-2.0 driver) | Document model fits inventory and sensor logs; teams can use Community Edition, Atlas, or another host without buying our stack. |
| **Camera / produce understanding** | [OpenCV](https://opencv.org/) (Apache-2.0), [PyTorch](https://pytorch.org/) + [torchvision](https://github.com/pytorch/vision) (BSD), [Hugging Face Transformers](https://github.com/huggingface/transformers) (Apache-2.0) | Capture and inference run on open tooling; models are pulled from the Hugging Face Hub under each model’s license (e.g. BLIP captioning, DETR detection, ResNet-50 classification). |
| **Label / code reading** | [Tesseract](https://github.com/tesseract-ocr/tesseract) (Apache-2.0) via `pytesseract` | OCR runs locally—no per-image billing from a third-party text API. |
| **HTTP between pieces** | [requests](https://requests.readthedocs.io/) (Apache-2.0) for JSON POSTs (e.g. camera analysis → `/receive-data`) | Simple, inspectable integration; no SDK lock-in. |
| **Hosting & collaboration** | [Render](https://render.com/) for public demo URLs, [GitHub](https://github.com/) for source | Standard student/startup paths; secrets stay in `.env`, not in the repo. |

**What is not “open” in the sense of public-by-default.** Store data, Mongo connection strings, and any future API keys stay private per deployment. Open source here means **the implementation is inspectable and forkable**, not that production tenant data is world-readable.

**Practical outcome.** A TA, NGO engineer, or another school team can clone the repo, install `requirements.txt`, point Tesseract and Mongo at their machine, and reproduce the dashboard and camera pipeline—aligned with GW’s emphasis on replicable urban food access prototypes.

---

## Quick next steps

- **Field interviews.** 3–5 store owners (ideally DCCK Healthy Corners partners) and 5–10 shoppers to validate pain points and the pricing display concept.
- **Define metrics.** Availability of fresh items, affordability, shrink/spoilage rate, healthy item sales mix, SNAP Match redemption rate.
- **Pick the wedge.** Shelf-edge freshness sensor for bananas and apples is our MVP wedge. Everything else is roadmap.
- **Demo plan.** One fresh banana and one pre-aged banana on stage. Live price differential on the LCD. Dashboard shows the freshness curve and a waste-avoided counter.