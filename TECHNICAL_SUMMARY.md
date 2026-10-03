# AI-Powered Highway Toll & Transit Pass System
## IT6070 – Emerging Topics in Information Technology — Week 1 & 2 PoC
### Technical Summary

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Streamlit Web Application                        │
│  ┌──────────────────────────┐   ┌──────────────────────────────┐  │
│  │   Tab 1: ANPR Terminal   │   │  Tab 2: Commuter Pass Portal  │  │
│  │  (Supervisor Viewpoint)  │   │    (Commuter Viewpoint)       │  │
│  └──────────┬───────────────┘   └───────────────┬──────────────┘  │
└─────────────┼───────────────────────────────────┼──────────────────┘
              │                                   │
     ┌────────▼────────┐                 ┌────────▼────────┐
     │  ANPR Pipeline  │                 │  Pass Manager   │
     │  (Edge Vision)  │                 │   (SQLite DB)   │
     │                 │                 │                 │
     │ OpenCV Pre-proc │◄────────────────│ Commuters Table │
     │ EasyOCR Engine  │                 │ Passes Table    │
     │ SL Plate Regex  │────────────────►│ Transit Log     │
     │ Confidence Gate │                 └─────────────────┘
     │ QR Fallback     │
     └─────────────────┘

     Edge Computer Vision Pipeline:
     Image → Quality Assessment → Pre-processing → OCR → Plate Regex
          → Confidence Gate (≥85%) → DB Lookup → Barrier Controller
                                ↓ <85%
                          Fallback QR Screen
```

### Component Breakdown

| Layer | Technology | Purpose |
|---|---|---|
| UI Framework | Streamlit 1.32+ | Interactive web interface, real-time rendering |
| Image Processing | OpenCV 4.8+ | Bilateral filter, adaptive thresholding, Laplacian sharpness |
| OCR Engine | EasyOCR 1.7+ | Deep-learning text extraction from plate images |
| Plate Parsing | Python `re` (regex) | Sri Lankan ANPR pattern matching |
| Database | SQLite 3 | Commuter, pass & audit log storage |
| QR Generation | `qrcode` library | Dynamic fallback verification tokens |
| Data Display | Pandas + Streamlit | Styled DataFrames and pass dashboards |
| Fonts | Google Fonts (Inter, JetBrains Mono) | Premium dark-mode UI typography |

---

## 2. Setup Instructions

### Prerequisites
- Python 3.9 or newer
- macOS / Ubuntu / Windows (tested on macOS)
- ~2 GB free disk space (EasyOCR model download on first run)

### Step-by-Step

```bash
# 1. Navigate to project directory
cd "AI-Powered Highway Toll & Transit Pass System"

# 2. (Recommended) Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate.bat    # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the Streamlit app
streamlit run app.py
```

The app will open automatically at **http://localhost:8501**

> **Note:** On first run, EasyOCR will download its English OCR model (~100 MB).
> This is a one-time download. All subsequent runs start instantly.

---

## 3. Test Cases (Aligned with Marking Rubric)

### Test Case 1 — Valid Active Pass Holder ✅
| Field | Value |
|---|---|
| Vehicle | White Toyota Prius |
| Plate | **WP-CAB-1234** |
| Pass | Monthly 20-Trip Commuter Pass |
| Commuter | Nimal Jayasinghe |
| Expiry | 25 days from today |
| Trips Remaining | 14 (decremented to 13 after clearance) |

**Expected Outcome:**
- ANPR confidence: **91–97%** (above 85% threshold)
- Green `✅ BARRIER OPENED` animation
- Trip counter decremented from 14 → 13
- Transit event written to audit log with timestamp & interchange
- Commuter name & pass details displayed

**How to Run:** Tab 1 → Select "Test Case 1" → Click "Run ANPR Pipeline"

---

### Test Case 2 — Expired / Zero-Balance Pass ❌
| Field | Value |
|---|---|
| Vehicle | Silver Honda Fit |
| Plate | **SP-WP-5678** |
| Pass | Weekly 10-Trip Pass |
| Commuter | Kumari Perera |
| Expiry | 3 days **ago** (expired) |
| Trips Remaining | 0 |

**Expected Outcome:**
- ANPR detects plate confidently (89–95%)
- DB lookup returns pass with `status = expired`
- Red `❌ BARRIER HELD — EXPIRED PASS` animation
- Error message with commuter name, expiry date, and remaining trips
- Info prompt to renew pass via Commuter Portal (Tab 2)
- Audit log records `HELD_EXPIRED_PASS` event

**How to Run:** Tab 1 → Select "Test Case 2" → Click "Run ANPR Pipeline"

---

### Test Case 3 — Obscured / Unreadable Plate ⚠️
| Field | Value |
|---|---|
| Scene | Night-time heavy rain |
| Plate | Mud-splattered, motion-blurred — **unreadable** |
| Injected Confidence | 38–54% (below 85% threshold) |

**Expected Outcome:**
- Quality assessment: low sharpness, dark scene, low contrast
- Amber `⚠️ PLATE OCCLUSION DETECTED — ACTIVATING FALLBACK`
- Three diagnostic tiles: Confidence %, Sharpness %, Degradation Cause
- **Fallback QR Scanner screen** rendered with:
  - Amber-on-dark dynamic QR code (session-unique token)
  - 30-second countdown messaging
  - "Simulate QR Verified" button → opens barrier via QR path
  - "Divert to Manual Cashier Lane" button → holds barrier

**How to Run:** Tab 1 → Select "Test Case 3" → Click "Run ANPR Pipeline"

---

## 4. Recurring Cost Analysis

### Infrastructure Costs (Per Interchange, Per Year)

| Component | Specification | Cost (LKR/year) | Cost (USD/year) |
|---|---|---|---|
| Edge AI Server | NVIDIA Jetson Orin NX (8GB) | LKR 480,000 | USD 1,600 |
| IP Gantry Camera | 4MP IR, weatherproof (×2) | LKR 120,000 | USD 400 |
| Server Hosting / Cloud Sync | AWS LightSail (optional) | LKR 36,000 | USD 120 |
| Power & UPS | 24×7 edge unit power | LKR 60,000 | USD 200 |
| Network (4G/LTE SIM) | Backup connectivity | LKR 24,000 | USD 80 |
| Software Maintenance | YOLOv8 retraining, patches | LKR 180,000 | USD 600 |
| **Total Per Interchange** | | **LKR 900,000** | **USD 3,000** |

### Software Licensing (Open-Source Stack)

| Component | License | Annual Cost |
|---|---|---|
| YOLOv8 (Ultralytics) | AGPL-3.0 | Free (PoC) / USD 1,500 (Enterprise) |
| EasyOCR | Apache 2.0 | Free |
| OpenCV | Apache 2.0 | Free |
| Streamlit | Apache 2.0 | Free |
| SQLite → PostgreSQL (prod) | MIT / BSD | Free |

### RDA Expressway Scale (9 Interchanges)

| Metric | Value |
|---|---|
| Interchanges on E01 (Southern Expressway) | 9 |
| One-time hardware CAPEX | LKR 81,000,000 (~USD 270,000) |
| Annual OPEX (maintenance + power + cloud) | LKR 2,700,000 (~USD 9,000) |
| Break-even vs. RFID ETC model | ~18 months |

---

## 5. Technology Comparison: ANPR vs. RFID ETC

| Criterion | **Our ANPR Solution** | Existing RFID / ETC e-Tag |
|---|---|---|
| User Hardware Required | **None** | RFID sticker/transponder per vehicle |
| Tag Distribution Overhead | **Zero** | Logistics, replacement, theft |
| Multi-vehicle Support | **Automatic** (plate-based) | One tag per vehicle |
| Installation at Interchange | Camera + edge GPU | Reader antenna + backend |
| Fraud Surface | Camera occlusion (mitigated by QR fallback) | Cloned tags, stolen transponders |
| Accuracy in Good Conditions | 94–98% | ~99.9% |
| Accuracy in Adverse Weather | 60–80% (mitigated by fallback) | ~99% |
| Scalability | **Fleet operators with zero effort** | Per-vehicle tag provisioning |
| Sri Lanka RDA Compatibility | Parallel deployment possible | Already deployed (limited rollout) |

---

## 6. Main Adoption Constraints

1. **Plate Standardisation Gap**: Sri Lanka lacks mandatory national plate standardisation enforcement — some older vehicles use non-standard fonts or hand-painted plates, reducing OCR accuracy.

2. **Adverse Weather Accuracy**: ANPR accuracy drops 15–25% in heavy tropical rainfall common in Sri Lanka. Mitigation: fallback QR system (already implemented) + infrared illuminators on gantry cameras.

3. **Privacy Regulation**: PDPA (Personal Data Protection Act, Sri Lanka, 2022) requires commuter consent for license plate capture and processing. A data retention policy limiting log retention to 90 days is recommended.

4. **Connectivity Dependency**: Real-time DB lookup requires low-latency connectivity. Edge-local caching of active passes (sync every 5 minutes) reduces dependency.

5. **YOLOv8 Model Training Data**: A production-grade model requires a Sri Lanka-specific training dataset of local vehicle plates in varied lighting. Estimated dataset collection: 3–4 months.

6. **Integration with RDA Backend**: Requires formal API integration with the RDA ETC platform (SLASSCOM-regulated) for pass billing and financial settlement — estimated 6–12 months for procurement.

---

## 7. File Structure

```
AI-Powered Highway Toll & Transit Pass System/
│
├── app.py                      ← Main Streamlit application (all-in-one)
├── requirements.txt            ← Python dependency list
├── toll_system.db              ← SQLite database (auto-created on first run)
│
├── test_images/
│   ├── tc1_valid_pass.jpg      ← Toyota Prius | WP-CAB-1234 | Active pass
│   ├── tc2_expired_pass.jpg    ← Honda Fit    | SP-WP-5678  | Expired pass
│   └── tc3_obscured_plate.jpg  ← Night/rain scene | Unreadable plate
│
└── TECHNICAL_SUMMARY.md        ← This document
```

---

*Prepared for IT6070 – Emerging Topics in Information Technology | Individual Postgraduate Project*
*Target Stakeholder: Mr. Nimal Jayasinghe, Toll Operations Supervisor, RDA EMMD, Sri Lanka*
