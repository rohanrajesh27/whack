# whack

DPG Alignment Statement
Track 2 — GW Global Food Institute | Problem Statement 2: The Corner Store of the Future
Project: Shelf-edge freshness sensor and dynamic pricing system for urban corner stores
Our solution is designed from day one to meet the Digital Public Goods Alliance's 9-indicator DPG Standard, making it replicable by any food-access program in any food desert — not just DC.
Impact & Relevance (SDG Alignment — DPG Indicator 1)
Food deserts are an SDG problem, and our solution maps directly to four UN Sustainable Development Goals:

SDG 2 (Zero Hunger) — Target 2.1: Ending hunger and ensuring access by all people, in particular the poor and people in vulnerable situations, to safe, nutritious, and sufficient food year-round. By giving corner store owners a low-risk way to stock fresh produce, we extend nutritious food access into the 33%+ of DC neighborhoods that the USDA classifies as food deserts.
SDG 3 (Good Health and Well-being) — Target 3.4: Reducing premature mortality from non-communicable diseases. Diet-related disease (diabetes, hypertension, cardiovascular illness) is disproportionately concentrated in low-income, low-access neighborhoods. Making fresh produce reliably available and visibly fairly priced is a direct upstream intervention.
SDG 10 (Reduced Inequalities) — Target 10.2: Empowering and promoting the social and economic inclusion of all. The solution is explicitly SNAP- and SNAP Match-compatible, with an affordability ceiling tied to big-box grocery benchmarks and an anti-gouging floor that protects low-income shoppers.
SDG 12 (Responsible Consumption and Production) — Target 12.3: Halving per capita global food waste. Dynamic freshness-based pricing converts spoilage risk into sold inventory, cutting shrink for small retailers who cannot absorb waste the way chains can.

The Healthy Corners program at DC Central Kitchen has already proven demand exists; our tool removes the last operational barrier — manual pricing risk — that keeps stores from scaling fresh inventory.
Innovation
The innovation is not the sensors — it's the fit to context. Existing dynamic pricing technology is built for supermarket chains with POS integration, produce managers, and IT budgets. A DC corner store has one shelf, one fridge, one owner, and often a basic cash register. Our system is deliberately re-engineered for that reality:

Shelf-edge, not enterprise. An ESP32 + load cell + VOC sensor + LCD runs independently of any POS. Total bill of materials is low enough to be subsidized per store.
Policy-aware pricing logic. Prices only move downward from an anchor tied to a mission-aligned benchmark, with a SNAP Match-compatible floor. This is a novel pricing framework, not just a novel device.
Automates the Healthy Corners Scorecard. Data that program operators currently collect manually (sales, waste, variety, deliveries) is auto-populated, turning each installation into a research instrument for food-access policy.
Open replication path. Because the hardware is commodity and the software is open-source, any city running a Healthy Corners-style program can deploy it without licensing or vendor lock-in.

Alignment to the Remaining DPG Indicators
DPG IndicatorOur Commitment2. Open LicensingAll firmware, backend, and dashboard code released under MIT or Apache 2.0. Hardware schematics and bill of materials released under CERN-OHL or CC BY-SA.3. Clear OwnershipOwnership of the codebase and documentation will be clearly assigned to the team and any partner organization (e.g., GW GFI or DCCK) in the repository.4. Platform IndependenceBuilt on open hardware (ESP32, standard I²C sensors) and open protocols (HTTP, MQTT). No proprietary cloud dependencies — backend can run on Firebase, a self-hosted Flask server, or any equivalent.5. DocumentationPublic repository with setup guides, wiring diagrams, calibration instructions, and a deployment playbook for program operators, not just developers.6. Mechanism for Extracting DataAll sensor data and pricing history exportable in open formats (CSV, JSON) through a documented API. Store owners and program operators retain full data portability.7. Privacy & Applicable LawsNo personally identifiable customer data is collected. The system senses produce, not people. SNAP transaction data is never touched; pricing guardrails are enforced in logic, not by reading benefit status.8. Standards & Best PracticesUses open web standards (REST, JSON), standard embedded protocols (I²C, SPI), and follows accessibility guidance for in-store signage (plain language, high-contrast display).9. Do No Harm by DesignThe anti-gouging floor, affordability ceiling, and downward-only price movement are explicit harm-prevention mechanisms. Prices cannot surge on supply shocks, cannot exceed the reference benchmark, and cannot undercut SNAP Match economics. No facial recognition, no shopper tracking, no behavioral profiling.

## License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.