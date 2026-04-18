## Track 2: GW Global Food Institute

## Problem Statement 2
### Reimagining the Corner Store as a Healthy Food Hub

The George Washington University — Global Food Institute

## Our solution (working concept)

**Core insight**
- **Fresh food has a shelf life** (freshness/ripeness changes daily), but corner stores often **price manually** and don’t have an easy way to “push” items before they spoil.

**Proposed solution**
- Build **software + supporting hardware** (specific hardware list TBD) that **tracks freshness/ripeness / remaining shelf life** and **automatically updates prices**.
- Use **dynamic pricing** to **move food faster** (sell items earlier at a higher price, then markdown as shelf life declines) to reduce spoilage and increase affordability.

**How it works (draft workflow)**
- **Identify items**: Detect or scan each fresh item/lot when it arrives (produce, dairy, etc.).
- **Estimate remaining shelf life**: Use signals like delivery date, storage conditions, and hardware-derived freshness indicators.
- **Set pricing rules**: Configure floors/ceilings, margin targets, and fairness guardrails.
- **Update labels/prices**: Automatically recommend or push price changes to labels/POS on a schedule (e.g., daily, twice daily).
- **Learn over time**: Adjust shelf-life estimates and markdown cadence based on sell-through and waste.

**Value proposition**
- **Store owners**: Less waste, better margins, less manual work, clearer replenishment decisions.
- **Community**: More affordable fresh food, fewer “bad” purchases, higher availability.

**Open questions / needs**
- **Hardware list**: What sensors/devices are feasible + affordable for corner stores?
- **Integration**: POS integration vs. standalone labeling?
- **Operations**: Who applies labels / confirms markdowns in-store?
- **Guardrails**: Minimum price thresholds, anti-gouging rules, and SNAP/WIC considerations.

**Hardware (current inventory / ordered)**

**Ordered (confirmed)**
- **Core system**
  - Elegoo UNO R3 starter kit (Arduino compatible)
  - Inland ESP32-WROOM-32D module (recommended as main board for MVP due to Wi‑Fi)
- **Sensors (inputs)**
  - Inland electronic scale kit: **5kg load cell + HX711**
  - Inland **CCS811** air quality sensor module (VOC/CO2 equivalent; exploratory signal)
- **Output / interface**
  - Inland **2-channel 5V relay** module
- **Wiring**
  - Inland Dupont jumper wires (20cm, 3 pack)

**Not yet confirmed (still needed / optional for MVP)**
- **Temp/humidity sensor** (for storage conditions). If you have DHT11 already, it can work for first tests; otherwise consider DHT22/SHT31/BME280 later.
- **LCD display** (+ optional I2C backpack to simplify wiring) and/or LEDs for a simple in-store UI.
- **Breadboard** (if not included in the Uno kit) for quick prototyping.

**Hardware notes / gaps to fill**
- **Timekeeping**: either use **Wi‑Fi/NTP (ESP32)** or add an **RTC module** for stable timestamps.
- **Item identification**: need a low-friction way to tie readings to an item/lot (QR/barcode scan, NFC, or simple manual selection).
- **Data logging** (optional but useful): microSD module or Wi‑Fi upload to the software backend.

**Recommended “minimum viable hardware MVP” (fastest to demo)**
- **ESP32 + Load cell + HX711 + temp/humidity sensor + LCD**
- Use **weight trend + storage conditions (temp/humidity) + delivery date** to compute a simple shelf-life score and show a **markdown tier / recommended price** on the LCD (later sync to the app/POS).

## Opportunity Areas

### 1) Technology for Healthy Inventory
Build tools that help store owners source, price, and manage fresh and nutritious food efficiently.

**Brainstorm ideas**
- **Smart ordering**: Suggested order quantities for produce/dairy based on past sales, seasonality, and local demand.
- **Spoilage + shrink tracking**: Simple daily “waste log” → auto-learns spoilage rates and adjusts future ordering.
- **Dynamic pricing**: Markdown recommendations for soon-to-expire items (with guardrails so pricing stays fair).
- **Healthy SKU starter kits**: Curated list of affordable, culturally relevant “healthy essentials” with supplier links.
- **Scan-to-manage inventory**: Phone camera barcode/receipt scan to update inventory without extra hardware.
- **Nutrition + margin view**: Combine profit margin + “healthy score” so owners can stock items that work financially.

**Key users**
- **Store owners/managers**
- **Cashiers/staff**
- **Local suppliers/distributors**

**Questions to answer**
- **Data availability**: Do stores have POS data? If not, what’s the lowest-friction way to capture sales/inventory?
- **Cold chain**: What refrigeration/storage capacity constraints exist?
- **Pricing constraints**: What are acceptable margins and price points for the neighborhood?

---

### 2) Community-Centered Store Design
Create solutions that make corner stores more engaging, culturally relevant, and responsive to local needs.

**Brainstorm ideas**
- **Community preference board**: In-store QR survey + lightweight voting on new items; share results with owners.
- **Culturally relevant healthy swaps**: Recipe cards and ingredient bundles reflecting local cuisines.
- **Healthy “grab-and-go” zone**: Layout guidance + signage templates; small footprint planograms for tight spaces.
- **Loyalty program**: Rewards that emphasize healthy purchases (e.g., points multipliers on produce/water).
- **Community partner hours**: Schedule tool for hosting pop-ups (WIC/SNAP support, nutrition demos, clinics).
- **In-store education**: Simple shelf tags (“high fiber”, “low sugar”) and price-per-serving labels.

**Key users**
- **Community members/shoppers**
- **Store owners**
- **Community organizations (clinics, schools, nonprofits)**

**Questions to answer**
- **Trust + engagement**: What incentives actually drive repeat healthy purchases?
- **Language + accessibility**: Which languages and literacy levels must signage/UX support?
- **Space constraints**: What’s the minimum viable layout change a store can adopt?

---

### 3) Supply Chain Innovation
Design systems that improve access to affordable fresh food through better distribution and partnerships.

**Brainstorm ideas**
- **Group purchasing**: Co-op ordering across multiple corner stores to hit distributor minimums and reduce costs.
- **Micro-distribution**: Local “hub” that breaks down bulk produce into store-sized orders.
- **Demand aggregation dashboard**: Show distributors consistent demand patterns to justify routes and better pricing.
- **Local producer partnerships**: Connect stores with nearby farms/urban gardens; predictable weekly order cycles.
- **Last-mile delivery coordination**: Optimize delivery windows and consolidate shipments to reduce spoilage.
- **SNAP/WIC optimization**: Highlight items that are eligible and move reliably; reduce risk for owners.

**Key users**
- **Distributors/wholesalers**
- **Local producers**
- **Store owners**
- **City/NGO partners**

**Questions to answer**
- **Minimum order + delivery cadence**: What are distributor constraints today?
- **Pricing**: Where do costs spike (transport, storage, middlemen) and which lever is most impactful?
- **Reliability**: How do we ensure consistent supply (and avoid “one good week, then nothing”)?

---

## Quick next steps (to refine the problem)
- **Field interviews**: 3–5 store owners + 5–10 shoppers to validate pain points and constraints.
- **Define metrics**: Availability of fresh items, affordability, shrink/spoilage rate, healthy item sales mix.
- **Pick a wedge**: Inventory tool, community engagement feature, or supply-chain coordination MVP.
