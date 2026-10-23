# AI-Powered Highway Toll & Transit Pass System

> **Module:** IT6070 – Emerging Topics in Information Technology  
> **Author:** Pramuditha Fernando  
> **Target Industry Professional:** (Toll Operations Supervisor, RDA Expressway Operation Maintenance & Management Division, Sri Lanka)

---

## Executive Summary

Manual ticket dispensing and cash toll handling at Sri Lankan expressway interchanges (e.g., Kottawa on E01, Kadawatha on E02) cause severe peak-hour queueing delays (14–24 seconds per vehicle, tailbacks up to 1.5 km). Over 62% of peak-hour users are daily repetitive commuters traveling identical routes.

This project delivers an **AI-Powered Highway Toll & Transit Pass System**:
* **Edge Computer Vision (ANPR):** Real-time automatic number plate recognition with quality assessment (Laplacian blur, brightness, contrast) and Sri Lankan registration regex parsing.
* **Prepaid Digital Commuter Passes:** Discounted weekly, monthly, corporate, and off-peak subscriptions with automatic trip decrementing.
* **Confidence Gate (≥85%):** High-confidence detections automatically trigger the pneumatic barrier in <300 ms; low-confidence captures seamlessly fall back to an encrypted, dynamic QR pass.
* **Production Containerisation:** Fully Dockerized container deployment orchestrated via Docker Compose and fronted by an Nginx reverse proxy with WebSocket support and persistent volumes.

---

## System Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│               Client Ingress (Web Browser / Gantry Tablet)             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Port 80
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Nginx Reverse Proxy                             │
│       • WebSocket Upgrade (/_stcore/stream)                            │
│       • Security Headers (X-Frame, X-Content-Type, X-XSS)              │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Port 8501 (Internal Docker Network)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     Streamlit Application Service                      │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Edge Computer Vision Pipeline                 │  │
│  │  1. Image Quality Assessment (Laplacian variance, Brightness)    │  │
│  │  2. Bilateral Filter & Adaptive Thresholding                     │  │
│  │  3. EasyOCR Deep Neural Text Recognition (CRAFT + CRNN)          │  │
│  │  4. Sri Lankan Plate Regex Normalisation (WP-CAB-1234)           │  │
│  │  5. Confidence Gate:                                             │  │
│  │     • Conf ≥ 85%  ──►  Pass Verification & Barrier Open          │  │
│  │     • Conf < 85%  ──►  Fail-safe Dynamic QR Fallback             │  │
│  └──────────────────────────────────┬───────────────────────────────┘  │
│                                     │                                  │
│  ┌──────────────────────────────────▼───────────────────────────────┐  │
│  │                      Pass Management Engine                      │  │
│  │  • Active Subscription Verification                              │  │
│  │  • Atomic Trip Decrementing & Expiry Checks                      │  │
│  │  • Real-Time Transit & Security Event Audit Logging              │  │
│  └──────────────────────────────────┬───────────────────────────────┘  │
└─────────────────────────────────────┼──────────────────────────────────┘
                                      │
                 ┌────────────────────┴───────────────────┐
                 ▼                                        ▼
       ┌───────────────────┐                    ┌───────────────────┐
       │     toll_data     │                    │   easyocr_cache   │
       │  (Named Volume)   │                    │  (Named Volume)   │
       │ /app/data/toll.db │                    │   /app/.easyocr   │
       └───────────────────┘                    └───────────────────┘
```

---

## Software Requirements

- **Docker (recommended):** Docker Desktop or Docker Engine with the Docker Compose plugin. The Docker image uses Python 3.11 and installs the system libraries needed by OpenCV and EasyOCR.
- **Local execution:** Python 3.11 recommended, `pip`, and the system libraries required by OpenCV. Install the Python packages listed in [`requirements.txt`](requirements.txt).
- A modern browser. Allow camera access if you want to use the custom webcam capture feature.
- Internet access is required on the first EasyOCR run if its recognition models are not already cached.

## Installation and Execution

### Docker Compose (recommended)

Run these commands from the repository root:

```bash
docker compose up -d --build
```

Wait for the `app` service to become healthy, then open:

- **Nginx reverse proxy:** [http://localhost:8088](http://localhost:8088) (default port)
- **Direct Streamlit access:** [http://localhost:8501](http://localhost:8501)

To see service status and logs:

```bash
docker compose ps
docker compose logs -f app
```

Run the automated tests in the app container:

```bash
docker compose exec app pytest tests/ -v
```

Stop the services while retaining the named database and EasyOCR model volumes:

```bash
docker compose down
```

### Local Python execution

From the repository root, create a virtual environment, install the requirements, and launch Streamlit:

```bash
python3.11 -m venv .venv
source .venv/bin/activate       # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501). Run the tests locally with:

```bash
python -m pytest tests/ -v
```

## API and Configuration

- The application is a Streamlit web app. **It does not provide a public REST API and does not require third-party API keys or credentials.**
- The default Docker Compose configuration publishes Streamlit on port `8501` and Nginx on port `8088`. To change the Nginx host port, set `NGINX_PORT` before starting Compose or define it in a root-level `.env` file, for example `NGINX_PORT=8090`.
- `DB_PATH` selects the SQLite database file. It defaults to `toll_system.db` for local execution; Compose sets it to `/app/data/toll_system.db` on the persistent `toll_data` volume.
- `EASYOCR_MODULE_PATH` selects the EasyOCR model cache directory. Compose sets it to `/app/.easyocr` on the persistent `easyocr_cache` volume.
- Demo commuter and pass records are inserted automatically when the database has no commuters. Existing database contents are retained; startup does not replace an existing database with the sample records.

For local overrides, set environment variables before running Streamlit. For example:

```bash
export DB_PATH=./data/toll_system.db
export EASYOCR_MODULE_PATH=./.easyocr
streamlit run app.py
```

## Sample Login Details

There is **no login or authentication screen**, so no username or password is required. The demo scenarios in the ANPR tab use these sample plates:

| Scenario | Sample plate | Expected result |
|---|---|---|
| TC1: Valid active pass | `WP-CAB-1234` | Demo authorization and trip decrement |
| TC2: Expired pass | `SP-WP-5678` | Barrier held; pass is expired |
| TC3: Obscured plate | No readable plate | Low-confidence fallback demonstration |

These are demonstration records and are not credentials for a real toll account.

## Known Limitations

- This is an academic proof of concept, not a production tolling service. It does not control a physical toll barrier or connect to RDA systems.
- The three built-in ANPR scenarios inject predetermined demo outcomes; they do not measure recognition accuracy on their sample images. Custom uploads use EasyOCR and may return no plate or an incorrect result depending on image quality and plate format.
- The QR fallback is a UI demonstration. Its “simulate scan” action does not integrate with a real mobile app, QR scanner, or payment/verification service.
- Pass purchase records a pass in SQLite but does not process payments. The app has no user authentication, role-based access, or account privacy boundary; do not expose it to untrusted networks or enter real personal information.
- SQLite and the single Streamlit app instance are intended for local demonstration, not concurrent or horizontally scaled production use.
- Camera capture depends on browser permission and device support. First-time EasyOCR model downloads can take time and require network access; recognition runs on CPU in the supplied configuration.
- The app has no public REST API, notification service, or integration with live traffic sensors.

---

## Interactive Test Scenarios

The ANPR Terminal includes 3 pre-configured vehicle scenarios aligned with the project milestones:

| Scenario | Plate | Commuter | Expected Pipeline Outcome |
|---|---|---|---|
| **TC1: Valid Active Pass** | `WP-CAB-1234` | Nimal Jayasinghe | Confidence $94\%$ $\rightarrow$ Barrier Opens $\rightarrow$ Trip balance decrements ($14 \rightarrow 13$) $\rightarrow$ Audit logged |
| **TC2: Expired Subscription** | `SP-WP-5678` | Kumari Perera | Confidence $91\%$ $\rightarrow$ Barrier Holds Closed $\rightarrow$ "Pass Expired" warning $\rightarrow$ Balance unchanged |
| **TC3: Obscured / Weather Glare** | Unreadable | Commuter | Confidence $54\%$ (<85%) $\rightarrow$ Barrier Holds Closed $\rightarrow$ Dynamic QR Fallback screen triggered |

---

## Project Structure

```
├── app.py                    # Complete 4-tab Streamlit application
├── requirements.txt          # Python dependencies (Streamlit, OpenCV, EasyOCR, Pytest)
├── Dockerfile                # Production Docker build with non-root security user
├── docker-compose.yml        # Orchestration for app and Nginx reverse proxy
├── nginx/
│   └── nginx.conf            # Reverse proxy configuration with WebSocket routing
├── tests/
│   └── test_app.py           # 32 automated unit & integration tests
├── test_images/              # Bundled test vehicles for immediate demonstration
└── logs/                     # Application logs and backup storage
```

---

## License & Academic Integrity
Developed as an individual postgraduate coursework submission for **IT6070: Emerging Topics in Information Technology**. All rights reserved.
