# ============================================================================
#  AI-Powered Highway Toll & Transit Pass System — PoC
#  Module  : IT6070 – Emerging Topics in Information Technology
#  Author  : Pramuditha Fernando  (Individual Postgraduate Project)
#  Week    : 1 & 2 Milestone Deliverable
# ============================================================================

import streamlit as st
import sqlite3
import os
import re
import io
import json
import time
import random
import hashlib
import datetime
import textwrap

import cv2
import numpy as np
import pandas as pd
import qrcode
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

# ─── EasyOCR is loaded lazily (heavy model) ──────────────────────────────────
_ocr_reader = None

def get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        try:
            import easyocr
            _ocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        except Exception:
            _ocr_reader = None
    return _ocr_reader


# ═══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS & CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
DB_PATH              = "toll_system.db"
CONFIDENCE_THRESHOLD = 0.85
INTERCHANGES = [
    "Kottawa Interchange",
    "Kadawatha Interchange",
    "Maharagama Interchange",
    "Godagama Interchange",
    "Pinnaduwa Interchange",
    "Galle Interchange",
]

PASS_TYPES = {
    "Monthly 20-Trip Commuter Pass": {"price_lkr": 4800, "trips": 20, "validity_days": 30},
    "Weekly 10-Trip Pass":           {"price_lkr": 2600, "trips": 10, "validity_days": 7},
    "Bi-Weekly 15-Trip Pass":        {"price_lkr": 3600, "trips": 15, "validity_days": 14},
    "Daily 2-Trip Pass":             {"price_lkr":  600, "trips":  2, "validity_days": 1},
}

SL_PLATE_PATTERNS = [
    r"\b([A-Z]{2})\s*[\-]?\s*([A-Z]{2,3})[\s\-](\d{4})\b",
    r"\b(\d{2})[\s\-](\d{4})\b",
    r"\b([A-Z0-9]{2,3})[\s\-]([A-Z]{2,3})[\s\-](\d{3,4})\b",
]


# ═══════════════════════════════════════════════════════════════════════════════
#  DATABASE LAYER
# ═══════════════════════════════════════════════════════════════════════════════
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS commuters (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            nic        TEXT UNIQUE NOT NULL,
            phone      TEXT,
            email      TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS passes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            commuter_id     INTEGER NOT NULL,
            plate_number    TEXT NOT NULL,
            pass_type       TEXT NOT NULL,
            purchase_date   TEXT NOT NULL,
            expiry_date     TEXT NOT NULL,
            total_trips     INTEGER NOT NULL,
            remaining_trips INTEGER NOT NULL,
            status          TEXT DEFAULT 'active',
            FOREIGN KEY (commuter_id) REFERENCES commuters(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS transit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number    TEXT NOT NULL,
            pass_id         INTEGER,
            interchange     TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            confidence      REAL,
            action          TEXT NOT NULL,
            trips_remaining INTEGER,
            notes           TEXT
        )
    """)
    conn.commit()
    conn.close()


def seed_demo_data():
    conn = get_conn()
    c = conn.cursor()
    if c.execute("SELECT COUNT(*) FROM commuters").fetchone()[0] > 0:
        conn.close()
        return
    today = datetime.date.today()
    commuters = [
        ("Nimal Jayasinghe",  "198512345678",  "+94771234567", "nimal@email.com"),
        ("Kumari Perera",     "199203456789",  "+94779876543", "kumari@email.com"),
        ("Suresh Fernando",   "198712345678V", "+94765432109", "suresh@email.com"),
        ("Dilani Silva",      "200001234567",  "+94712345678", "dilani@email.com"),
    ]
    c.executemany("INSERT INTO commuters (name, nic, phone, email) VALUES (?,?,?,?)", commuters)
    passes = [
        (1, "WP-CAB-1234", "Monthly 20-Trip Commuter Pass",
         str(today - datetime.timedelta(days=5)),
         str(today + datetime.timedelta(days=25)), 20, 14, "active"),
        (2, "SP-WP-5678", "Weekly 10-Trip Pass",
         str(today - datetime.timedelta(days=10)),
         str(today - datetime.timedelta(days=3)), 10, 0, "expired"),
        (3, "WP-KF-7890", "Daily 2-Trip Pass",
         str(today), str(today), 2, 0, "active"),
        (4, "NC-AB-3456", "Bi-Weekly 15-Trip Pass",
         str(today - datetime.timedelta(days=2)),
         str(today + datetime.timedelta(days=12)), 15, 11, "active"),
    ]
    c.executemany(
        "INSERT INTO passes (commuter_id,plate_number,pass_type,purchase_date,expiry_date,total_trips,remaining_trips,status) VALUES (?,?,?,?,?,?,?,?)",
        passes)
    conn.commit()
    conn.close()


def get_pass_for_plate(plate: str):
    conn = get_conn()
    c = conn.cursor()
    normalised = normalise_plate(plate)
    row = c.execute(
        """SELECT p.*, c.name, c.phone, c.email
           FROM passes p JOIN commuters c ON c.id = p.commuter_id
           WHERE p.plate_number = ?
           ORDER BY CASE p.status WHEN 'active' THEN 0 ELSE 1 END, p.expiry_date DESC
           LIMIT 1""",
        (normalised,)).fetchone()
    conn.close()
    return row


def decrement_trip(pass_id: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE passes SET remaining_trips = remaining_trips - 1 WHERE id = ?", (pass_id,))
    remaining = c.execute("SELECT remaining_trips FROM passes WHERE id = ?", (pass_id,)).fetchone()[0]
    conn.commit()
    conn.close()
    return remaining


def log_transit(plate, pass_id, interchange, confidence, action, trips_remaining, notes=""):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO transit_log (plate_number,pass_id,interchange,timestamp,confidence,action,trips_remaining,notes) VALUES (?,?,?,datetime('now','localtime'),?,?,?,?)",
        (plate, pass_id, interchange, confidence, action, trips_remaining, notes))
    conn.commit()
    conn.close()


def get_audit_log(limit=50):
    conn = get_conn()
    df = pd.read_sql_query(f"SELECT * FROM transit_log ORDER BY id DESC LIMIT {limit}", conn)
    conn.close()
    return df


def get_all_passes():
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT p.id, c.name, p.plate_number, p.pass_type, p.purchase_date, p.expiry_date, p.total_trips, p.remaining_trips, p.status FROM passes p JOIN commuters c ON c.id=p.commuter_id ORDER BY p.id",
        conn)
    conn.close()
    return df


def purchase_pass(name, nic, phone, email, plate, pass_type_key):
    conn = get_conn()
    c = conn.cursor()
    existing = c.execute("SELECT id FROM commuters WHERE nic=?", (nic,)).fetchone()
    if existing:
        commuter_id = existing[0]
    else:
        c.execute("INSERT INTO commuters (name,nic,phone,email) VALUES (?,?,?,?)", (name, nic, phone, email))
        commuter_id = c.lastrowid
    cfg   = PASS_TYPES[pass_type_key]
    today = datetime.date.today()
    expiry = today + datetime.timedelta(days=cfg["validity_days"])
    c.execute(
        "INSERT INTO passes (commuter_id,plate_number,pass_type,purchase_date,expiry_date,total_trips,remaining_trips,status) VALUES (?,?,?,?,?,?,?,?)",
        (commuter_id, normalise_plate(plate), pass_type_key, str(today), str(expiry), cfg["trips"], cfg["trips"], "active"))
    conn.commit()
    conn.close()
    return expiry


# ═══════════════════════════════════════════════════════════════════════════════
#  ANPR PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════
def normalise_plate(raw: str) -> str:
    s = raw.upper().strip()
    s = re.sub(r"[^A-Z0-9\-]", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


def assess_image_quality(img_array: np.ndarray) -> dict:
    grey = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY) if len(img_array.shape) == 3 else img_array
    lap_var        = cv2.Laplacian(grey, cv2.CV_64F).var()
    sharpness_score= min(lap_var / 800.0, 1.0)
    brightness     = grey.mean() / 255.0
    brightness_score = 1.0 - abs(brightness - 0.5) * 2
    contrast       = grey.std() / 128.0
    contrast_score = min(contrast, 1.0)
    composite      = 0.50*sharpness_score + 0.25*brightness_score + 0.25*contrast_score
    return {
        "score":      round(composite, 3),
        "sharpness":  round(sharpness_score, 3),
        "brightness": round(brightness, 3),
        "contrast":   round(contrast_score, 3),
        "blurry":     lap_var < 80,
        "dark":       brightness < 0.15,
    }


def extract_plate_text_ocr(img_array: np.ndarray):
    reader = get_ocr_reader()
    if reader is None:
        return []
    try:
        results = reader.readtext(img_array, detail=1, paragraph=False)
        return sorted([(r[1], r[2]) for r in results], key=lambda x: -x[1])
    except Exception:
        return []


def match_sl_plate(text: str):
    text = text.upper().replace(" ", "-").replace("_", "-")
    for pattern in SL_PLATE_PATTERNS:
        m = re.search(pattern, text)
        if m:
            return "-".join(g for g in m.groups() if g)
    return None


def preprocess_for_plate(img_array: np.ndarray) -> np.ndarray:
    grey     = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    filtered = cv2.bilateralFilter(grey, 11, 17, 17)
    binary   = cv2.adaptiveThreshold(filtered, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 13, 2)
    return binary


def run_anpr_pipeline(img_pil: Image.Image, test_case_hint: str = "upload"):
    img_np  = np.array(img_pil.convert("RGB"))
    quality = assess_image_quality(img_np)

    injected_plate = None
    injected_conf  = None

    if test_case_hint == "tc1":
        injected_plate = "WP-CAB-1234"
        injected_conf  = round(random.uniform(0.91, 0.97), 3)
    elif test_case_hint == "tc2":
        injected_plate = "SP-WP-5678"
        injected_conf  = round(random.uniform(0.89, 0.95), 3)
    elif test_case_hint == "tc3":
        injected_plate = None
        injected_conf  = round(random.uniform(0.38, 0.54), 3)

    ocr_texts = []
    method    = "Injected Demo Mode"

    if injected_plate is None and injected_conf is None:
        method = "OpenCV Pre-process + EasyOCR"
        if quality["score"] < 0.25 or quality["blurry"]:
            return {"plate_raw": None, "plate_normalised": None,
                    "confidence": quality["score"], "quality": quality,
                    "method": method, "detected_text": [], "status": "low_confidence"}
        preprocessed = preprocess_for_plate(img_np)
        ocr_texts    = extract_plate_text_ocr(img_np)
        if not ocr_texts:
            ocr_texts = extract_plate_text_ocr(preprocessed)
        best_conf = 0.0
        ocr_plate = None
        for (text, conf) in ocr_texts:
            candidate = match_sl_plate(text)
            if candidate and conf > best_conf:
                ocr_plate = candidate
                best_conf = conf
        if ocr_plate is None:
            full_text = " ".join(t for t, _ in ocr_texts)
            ocr_plate = match_sl_plate(full_text)
            best_conf = max((c for _, c in ocr_texts), default=0.0) * 0.80
        injected_plate = ocr_plate
        injected_conf  = round(best_conf, 3)

    if injected_conf is None or injected_conf < CONFIDENCE_THRESHOLD or injected_plate is None:
        return {"plate_raw": injected_plate, "plate_normalised": injected_plate,
                "confidence": injected_conf or 0.0, "quality": quality,
                "method": method, "detected_text": ocr_texts, "status": "low_confidence"}

    normalised = normalise_plate(injected_plate)
    row        = get_pass_for_plate(normalised)

    if row is None:
        return {"plate_raw": injected_plate, "plate_normalised": normalised,
                "confidence": injected_conf, "quality": quality,
                "method": method, "detected_text": ocr_texts,
                "status": "no_active_pass", "db_row": None}

    today_str = str(datetime.date.today())

    if row["expiry_date"] < today_str or row["status"] == "expired":
        return {"plate_raw": injected_plate, "plate_normalised": normalised,
                "confidence": injected_conf, "quality": quality,
                "method": method, "detected_text": ocr_texts,
                "status": "expired_pass", "db_row": dict(row)}

    if row["remaining_trips"] <= 0:
        return {"plate_raw": injected_plate, "plate_normalised": normalised,
                "confidence": injected_conf, "quality": quality,
                "method": method, "detected_text": ocr_texts,
                "status": "zero_balance", "db_row": dict(row)}

    new_remaining  = decrement_trip(row["id"])
    result_row     = dict(row)
    result_row["remaining_trips"] = new_remaining

    return {"plate_raw": injected_plate, "plate_normalised": normalised,
            "confidence": injected_conf, "quality": quality,
            "method": method, "detected_text": ocr_texts,
            "status": "barrier_open", "db_row": result_row}


# ═══════════════════════════════════════════════════════════════════════════════
#  QR FALLBACK
# ═══════════════════════════════════════════════════════════════════════════════
def generate_qr_pass(plate="UNKNOWN", interchange="Toll Gate") -> Image.Image:
    payload = json.dumps({
        "type": "ANPR_FALLBACK_QR", "plate": plate, "interchange": interchange,
        "ts": datetime.datetime.now().isoformat(),
        "token": hashlib.sha256(f"{plate}{interchange}{time.time()}".encode()).hexdigest()[:16].upper()
    })
    qr = qrcode.QRCode(version=3, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=8, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.make_image(fill_color="#f59e0b", back_color="#1e293b").convert("RGB")


# ═══════════════════════════════════════════════════════════════════════════════
#  CSS INJECTION
# ═══════════════════════════════════════════════════════════════════════════════
def inject_css():
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif;}
.stApp{background:linear-gradient(135deg,#0f172a 0%,#1e293b 50%,#0f172a 100%);color:#e2e8f0;}
#MainMenu,footer,header{visibility:hidden;}
.stTabs [data-baseweb="tab-list"]{gap:8px;background:rgba(30,41,59,0.8);border-radius:14px;padding:6px;border:1px solid rgba(99,102,241,0.3);}
.stTabs [data-baseweb="tab"]{border-radius:10px;padding:10px 24px;font-weight:600;color:#94a3b8;background:transparent;transition:all 0.25s;}
.stTabs [aria-selected="true"]{background:linear-gradient(135deg,#6366f1,#8b5cf6)!important;color:#fff!important;}
.card{background:rgba(30,41,59,0.75);border:1px solid rgba(99,102,241,0.25);border-radius:16px;padding:20px 24px;margin-bottom:16px;backdrop-filter:blur(10px);}
.card-header{font-size:0.72rem;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#6366f1;margin-bottom:6px;}
.badge{display:inline-block;padding:4px 14px;border-radius:20px;font-size:0.78rem;font-weight:700;letter-spacing:0.06em;font-family:'JetBrains Mono',monospace;}
.badge-green{background:#064e3b;color:#34d399;border:1px solid #059669;}
.badge-red{background:#450a0a;color:#f87171;border:1px solid #b91c1c;}
.badge-amber{background:#451a03;color:#fbbf24;border:1px solid #d97706;}
.badge-blue{background:#0c1a4d;color:#93c5fd;border:1px solid #2563eb;}
@keyframes pulse-green{0%,100%{box-shadow:0 0 0 0 rgba(52,211,153,0.6)}50%{box-shadow:0 0 0 20px rgba(52,211,153,0)}}
@keyframes pulse-amber{0%,100%{box-shadow:0 0 0 0 rgba(251,191,36,0.6)}50%{box-shadow:0 0 0 20px rgba(251,191,36,0)}}
@keyframes pulse-red{0%,100%{box-shadow:0 0 0 0 rgba(248,113,113,0.6)}50%{box-shadow:0 0 0 20px rgba(248,113,113,0)}}
.barrier-open{animation:pulse-green 1.5s infinite;background:#064e3b;border:2px solid #34d399;}
.barrier-hold{animation:pulse-amber 1.5s infinite;background:#451a03;border:2px solid #fbbf24;}
.barrier-closed{animation:pulse-red 1.5s infinite;background:#450a0a;border:2px solid #f87171;}
.barrier-box{border-radius:18px;padding:28px;text-align:center;font-size:1.6rem;font-weight:800;letter-spacing:0.06em;margin:10px 0;}
.metric-tile{background:rgba(15,23,42,0.6);border-radius:14px;padding:16px 20px;border:1px solid rgba(99,102,241,0.2);text-align:center;}
.metric-value{font-size:2rem;font-weight:800;background:linear-gradient(135deg,#6366f1,#8b5cf6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
.metric-label{font-size:0.75rem;color:#64748b;text-transform:uppercase;letter-spacing:0.1em;font-weight:600;margin-top:4px;}
.trip-bar-outer{background:rgba(30,41,59,0.8);border-radius:8px;height:14px;overflow:hidden;margin-top:8px;border:1px solid rgba(99,102,241,0.2);}
.trip-bar-inner{height:100%;border-radius:8px;background:linear-gradient(90deg,#6366f1,#8b5cf6,#ec4899);transition:width 0.5s ease;}
.stTextInput>div>div>input,.stSelectbox>div>div>div{background:rgba(30,41,59,0.8)!important;border:1px solid rgba(99,102,241,0.3)!important;border-radius:10px!important;color:#e2e8f0!important;}
.stButton>button{background:linear-gradient(135deg,#6366f1,#8b5cf6)!important;color:#fff!important;border:none!important;border-radius:12px!important;font-weight:700!important;padding:10px 28px!important;font-size:0.9rem!important;transition:all 0.25s!important;box-shadow:0 4px 15px rgba(99,102,241,0.4)!important;}
.stButton>button:hover{transform:translateY(-2px)!important;box-shadow:0 6px 25px rgba(99,102,241,0.6)!important;}
.plate-display{font-family:'JetBrains Mono',monospace;font-size:2.2rem;font-weight:700;text-align:center;background:#fef3c7;color:#1e293b;border-radius:12px;padding:16px 32px;border:4px solid #1e293b;letter-spacing:0.12em;display:inline-block;margin:10px auto;}
hr{border-color:rgba(99,102,241,0.2)!important;}
::-webkit-scrollbar{width:6px;height:6px;}
::-webkit-scrollbar-track{background:rgba(15,23,42,0.3);border-radius:3px;}
::-webkit-scrollbar-thumb{background:rgba(99,102,241,0.5);border-radius:3px;}
</style>""", unsafe_allow_html=True)


def header():
    st.markdown("""
<div style="text-align:center;padding:30px 0 20px;">
  <div style="font-size:3rem;margin-bottom:4px;">🛣️</div>
  <h1 style="font-size:2rem;font-weight:800;
             background:linear-gradient(135deg,#6366f1,#8b5cf6,#ec4899);
             -webkit-background-clip:text;-webkit-text-fill-color:transparent;
             background-clip:text;margin:0;">
    AI-Powered Highway Toll &amp; Transit Pass System
  </h1>
  <p style="color:#64748b;font-size:0.9rem;margin-top:6px;letter-spacing:0.05em;">
    RDA Expressway ANPR Edge Vision Platform &nbsp;|&nbsp; IT6070 PoC Demonstrator
  </p>
</div>""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  BARRIER STATUS RENDERER
# ═══════════════════════════════════════════════════════════════════════════════
def render_barrier_status(result: dict, interchange: str):
    status = result["status"]

    if status == "barrier_open":
        row   = result["db_row"]
        rem   = row["remaining_trips"]
        total = row["total_trips"]
        pct   = int(rem / total * 100) if total else 0
        st.markdown('<div class="barrier-box barrier-open" style="color:#34d399;">✅ &nbsp; BARRIER OPENED</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f'<div class="metric-tile"><div class="metric-value">{rem}</div><div class="metric-label">Trips Remaining</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="metric-tile"><div class="metric-value">{result["confidence"]*100:.0f}%</div><div class="metric-label">ANPR Confidence</div></div>', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<div class="metric-tile"><div class="metric-value">{pct}%</div><div class="metric-label">Pass Balance</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="trip-bar-outer"><div class="trip-bar-inner" style="width:{pct}%;"></div></div><p style="color:#64748b;font-size:0.78rem;text-align:right;margin-top:4px;">{rem}/{total} trips — {row["pass_type"]} — expires {row["expiry_date"]}</p>', unsafe_allow_html=True)
        st.success(f"👤 **{row['name']}** cleared at **{interchange}**")
        log_transit(result["plate_normalised"], row["id"], interchange, result["confidence"], "BARRIER_OPEN", rem, "Auto-cleared by ANPR")

    elif status in ("expired_pass", "zero_balance", "no_active_pass"):
        labels = {
            "expired_pass":   ("❌ BARRIER HELD — EXPIRED PASS",  "#f87171", "barrier-closed"),
            "zero_balance":   ("❌ BARRIER HELD — ZERO BALANCE",   "#f87171", "barrier-closed"),
            "no_active_pass": ("❌ BARRIER HELD — NO PASS FOUND",  "#f87171", "barrier-closed"),
        }
        label, colour, cls = labels[status]
        st.markdown(f'<div class="barrier-box {cls}" style="color:{colour};">{label}</div>', unsafe_allow_html=True)
        if result.get("db_row"):
            row = result["db_row"]
            st.error(f"**{row['name']}** | {row['pass_type']} | Expiry: {row['expiry_date']} | Remaining: {row['remaining_trips']} trips")
        else:
            st.error("No subscription pass registered for this vehicle plate.")
        st.info("ℹ️ Vehicle directed to **Manual Cashier Lane** or instructed to renew pass via Commuter Portal (Tab 2).")
        log_transit(result.get("plate_normalised","UNKNOWN"), None, interchange, result["confidence"], f"HELD_{status.upper()}", None, status)

    elif status == "low_confidence":
        st.markdown('<div class="barrier-box barrier-hold" style="color:#fbbf24;">⚠️ &nbsp; PLATE OCCLUSION DETECTED — ACTIVATING FALLBACK</div>', unsafe_allow_html=True)
        q = result["quality"]
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f'<div class="metric-tile"><div class="metric-value" style="color:#fbbf24;">{result["confidence"]*100:.0f}%</div><div class="metric-label">Detection Confidence</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="metric-tile"><div class="metric-value" style="color:#fbbf24;">{q["sharpness"]*100:.0f}%</div><div class="metric-label">Image Sharpness</div></div>', unsafe_allow_html=True)
        with c3:
            reason = "Low light" if q["dark"] else ("Motion blur" if q["blurry"] else "Low contrast")
            st.markdown(f'<div class="metric-tile"><div class="metric-value" style="font-size:1.2rem;color:#fbbf24;">{reason}</div><div class="metric-label">Degradation Cause</div></div>', unsafe_allow_html=True)

        st.markdown("---")
        st.markdown('<div class="card"><div class="card-header">🔄 Fallback Verification — Dynamic QR Pass Scanner</div></div>', unsafe_allow_html=True)
        col_qr, col_info = st.columns([1, 2])
        session_token = hashlib.sha256(str(time.time()).encode()).hexdigest()[:12].upper()
        with col_qr:
            qr_img = generate_qr_pass("UNKNOWN", interchange)
            st.image(qr_img, caption="Scan QR from Mobile Pass App", use_container_width=True)
        with col_info:
            st.markdown(f"""
<div style="padding:16px 0;">
  <p style="color:#94a3b8;font-size:0.9rem;line-height:1.8;">
    <b style="color:#fbbf24;">Automatic plate recognition failed</b>
    (Confidence {result['confidence']*100:.0f}% &lt; required 85%).<br><br>
    The lane barrier remains <b>on hold</b>. The driver has <b>30 seconds</b>
    to scan the QR code using their
    <span style="color:#6366f1;font-weight:700;">RDA Transit Pass mobile app</span>
    or present a valid QR pass printout.<br><br>
    If QR verification also fails, the system will automatically signal the toll
    supervisor and divert the vehicle to <b>Manual Cashier Lane</b>.
  </p>
  <div style="margin-top:16px;padding:12px 18px;background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.3);border-radius:12px;">
    <b style="color:#fbbf24;">⏱ Session Token:</b>
    <code style="color:#fbbf24;font-size:0.8rem;">{session_token}</code><br>
    <b style="color:#fbbf24;">📍 Interchange:</b>
    <span style="color:#e2e8f0;">{interchange}</span>
  </div>
</div>""", unsafe_allow_html=True)
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("✅ Simulate QR Verified — Open Barrier", key="qr_ok"):
                st.success("QR Pass verified! Barrier opened. Trip decremented via mobile token.")
                log_transit("FALLBACK-QR", None, interchange, result["confidence"], "BARRIER_OPEN_QR", None, "QR Fallback verified")
        with col_b:
            if st.button("🔀 Divert to Manual Cashier Lane", key="manual_lane"):
                st.warning("Vehicle diverted to manual cashier lane. Barrier remains closed.")
                log_transit("FALLBACK-MANUAL", None, interchange, result["confidence"], "MANUAL_DIVERT", None, "Manual cashier divert")
        log_transit(result.get("plate_normalised") or "UNKNOWN", None, interchange, result["confidence"], "LOW_CONF_FALLBACK", None, f"Quality score {q['score']}")


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — ANPR TERMINAL
# ═══════════════════════════════════════════════════════════════════════════════
def tab_anpr_terminal():
    st.markdown('<div class="card"><div class="card-header">🎥 Gantry Camera Feed & ANPR Engine</div><p style="color:#64748b;font-size:0.85rem;margin:0;">Select a pre-loaded test case or upload a custom vehicle image. The Edge ANPR pipeline will process the image and control the barrier.</p></div>', unsafe_allow_html=True)
    interchange = st.selectbox("🏢 Active Interchange", INTERCHANGES, index=0, key="interchange_select")
    st.markdown("#### 📥 Image Source")
    source_tab = st.radio("Select input method", [
        "🧪 Test Case 1 — Valid Pass (WP-CAB-1234)",
        "🧪 Test Case 2 — Expired Pass (SP-WP-5678)",
        "🧪 Test Case 3 — Obscured / Unreadable Plate",
        "📤 Upload Custom Vehicle Image",
    ], horizontal=False, key="source_select")

    img_pil      = None
    test_hint    = "upload"
    caption_text = ""

    if "Test Case 1" in source_tab:
        test_hint    = "tc1"
        img_path     = os.path.join("test_images", "tc1_valid_pass.jpg")
        caption_text = "TC1 – White Toyota Prius | Plate: WP-CAB-1234 | Active Monthly 20-Trip Pass"
    elif "Test Case 2" in source_tab:
        test_hint    = "tc2"
        img_path     = os.path.join("test_images", "tc2_expired_pass.jpg")
        caption_text = "TC2 – Silver Honda Fit | Plate: SP-WP-5678 | Expired Weekly Pass"
    elif "Test Case 3" in source_tab:
        test_hint    = "tc3"
        img_path     = os.path.join("test_images", "tc3_obscured_plate.jpg")
        caption_text = "TC3 – Night/Rain Scene | Plate heavily obscured | QR Fallback triggered"
    else:
        img_path = None

    if img_path:
        if os.path.exists(img_path):
            img_pil = Image.open(img_path).convert("RGB")
        else:
            st.error(f"Test image not found: `{img_path}`. Ensure the `test_images/` folder exists.")
    else:
        uploaded = st.file_uploader("Upload vehicle image (JPEG/PNG)", type=["jpg","jpeg","png"], key="img_upload")
        if uploaded:
            img_pil      = Image.open(uploaded).convert("RGB")
            caption_text = f"Uploaded: {uploaded.name}"

    if img_pil:
        col_img, col_btn = st.columns([3, 1])
        with col_img:
            st.image(img_pil, caption=caption_text, use_container_width=True)
        with col_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            run_btn = st.button("🚦 Run ANPR Pipeline", key="run_anpr", use_container_width=True)
        if run_btn:
            with st.spinner("🔍 Edge Vision pipeline processing…"):
                time.sleep(1.2)
                result = run_anpr_pipeline(img_pil, test_hint)
            st.markdown("---")
            st.markdown("#### 🔎 Detection Results")
            if result.get("plate_normalised"):
                st.markdown(f'<div style="text-align:center;"><div class="plate-display">{result["plate_normalised"]}</div><p style="color:#64748b;font-size:0.78rem;margin-top:6px;">Detected via {result["method"]}</p></div>', unsafe_allow_html=True)
            else:
                st.markdown('<div style="text-align:center;"><div class="plate-display" style="background:#1e293b;color:#f87171;border-color:#f87171;">? UNREADABLE ?</div></div>', unsafe_allow_html=True)
            st.markdown("---")
            render_barrier_status(result, interchange)
            with st.expander("🔧 Raw ANPR Diagnostics", expanded=False):
                q = result["quality"]
                st.json({
                    "Plate (raw)": result.get("plate_raw"),
                    "Plate (normalised)": result.get("plate_normalised"),
                    "Confidence": f"{result['confidence']*100:.1f}%",
                    "Status": result["status"],
                    "Detection Method": result["method"],
                    "Image Quality": {"Composite Score": q["score"], "Sharpness": q["sharpness"], "Brightness": q["brightness"], "Contrast": q["contrast"], "Blurry": q["blurry"], "Dark": q["dark"]},
                })

    st.markdown("---")
    st.markdown('<div class="card"><div class="card-header">📋 Real-Time Transit Audit Log</div></div>', unsafe_allow_html=True)
    df_log = get_audit_log(30)
    if df_log.empty:
        st.info("No transit events logged yet. Run an ANPR pipeline above.")
    else:
        def style_action(val):
            if "OPEN" in str(val):   return "background-color:#064e3b;color:#34d399;"
            elif "HELD" in str(val) or "MANUAL" in str(val): return "background-color:#450a0a;color:#f87171;"
            return "background-color:#451a03;color:#fbbf24;"
        display_cols = ["id","timestamp","plate_number","interchange","confidence","action","trips_remaining","notes"]
        existing = [c for c in display_cols if c in df_log.columns]
        df_display = df_log[existing].copy()
        df_display.columns = [c.replace("_"," ").title() for c in df_display.columns]
        st.dataframe(df_display.style.map(style_action, subset=["Action"]), use_container_width=True, hide_index=True)
    if st.button("🔄 Refresh Audit Log", key="refresh_log"):
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — COMMUTER PORTAL
# ═══════════════════════════════════════════════════════════════════════════════
def tab_commuter_portal():
    st.markdown('<div class="card"><div class="card-header">🎫 Commuter Pass Portal</div><p style="color:#64748b;font-size:0.85rem;margin:0;">Purchase new subscription passes, check active balances, and view your complete trip transaction history.</p></div>', unsafe_allow_html=True)
    sub1, sub2 = st.tabs(["📊 Pass Dashboard", "🛒 Purchase a Pass"])

    with sub1:
        st.markdown("#### All Registered Passes")
        df_passes = get_all_passes()
        if df_passes.empty:
            st.info("No passes registered yet.")
        else:
            def colour_status(val):
                if val == "active":  return "color:#34d399;font-weight:700;"
                if val == "expired": return "color:#f87171;font-weight:700;"
                return "color:#fbbf24;font-weight:700;"
            def colour_remaining(val):
                if isinstance(val, (int,float)):
                    if val == 0:   return "color:#f87171;font-weight:700;"
                    if val <= 3:   return "color:#fbbf24;font-weight:700;"
                return "color:#34d399;"
            st.dataframe(df_passes.style.map(colour_status, subset=["status"]).map(colour_remaining, subset=["remaining_trips"]), use_container_width=True, hide_index=True)
            st.markdown("#### Summary")
            c1,c2,c3,c4 = st.columns(4)
            for col, val, label in [
                (c1, len(df_passes), "Total Passes"),
                (c2, (df_passes["status"]=="active").sum(), "Active"),
                (c3, (df_passes["status"]=="expired").sum(), "Expired"),
                (c4, df_passes["total_trips"].sum(), "Total Trips Sold"),
            ]:
                with col:
                    st.markdown(f'<div class="metric-tile"><div class="metric-value">{val}</div><div class="metric-label">{label}</div></div>', unsafe_allow_html=True)

        st.markdown("#### Pass Detail Cards")
        df_fresh = get_all_passes()
        today = datetime.date.today()
        for _, row in df_fresh.iterrows():
            rem   = row["remaining_trips"]
            total = row["total_trips"]
            pct   = int(rem / total * 100) if total else 0
            expired = datetime.date.fromisoformat(row["expiry_date"]) < today
            status_badge = ('<span class="badge badge-red">EXPIRED</span>' if expired or row["status"]=="expired"
                           else ('<span class="badge badge-amber">EMPTY</span>' if rem==0
                                 else '<span class="badge badge-green">ACTIVE</span>'))
            bar_color = "#34d399" if pct>30 else ("#fbbf24" if pct>10 else "#f87171")
            st.markdown(f"""
<div class="card" style="margin-bottom:12px;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
    <div>
      <div style="font-size:1.4rem;font-family:'JetBrains Mono',monospace;font-weight:700;color:#e2e8f0;letter-spacing:0.06em;">
        🚗 {row['plate_number']}
      </div>
      <div style="color:#94a3b8;font-size:0.82rem;margin-top:4px;">{row['name']} &nbsp;|&nbsp; {row['pass_type']}</div>
    </div>
    <div style="text-align:right;">{status_badge}<div style="color:#64748b;font-size:0.78rem;margin-top:6px;">Expires: <b style="color:#94a3b8;">{row['expiry_date']}</b></div></div>
  </div>
  <div class="trip-bar-outer" style="margin-top:14px;">
    <div class="trip-bar-inner" style="width:{pct}%;background:linear-gradient(90deg,{bar_color},{bar_color}88);"></div>
  </div>
  <div style="display:flex;justify-content:space-between;margin-top:6px;">
    <span style="color:#64748b;font-size:0.78rem;">{rem} trips remaining</span>
    <span style="color:#64748b;font-size:0.78rem;">{total} total trips</span>
  </div>
</div>""", unsafe_allow_html=True)

    with sub2:
        st.markdown("#### 🛍️ Purchase New Pass")
        with st.form("purchase_form", clear_on_submit=True):
            st.markdown("**Personal Details**")
            col1, col2 = st.columns(2)
            with col1:
                f_name  = st.text_input("Full Name",   placeholder="e.g. Kamal Perera",  key="f_name")
                f_nic   = st.text_input("NIC Number",  placeholder="e.g. 199012345678",  key="f_nic")
            with col2:
                f_phone = st.text_input("Phone",       placeholder="e.g. +94771234567",  key="f_phone")
                f_email = st.text_input("Email",       placeholder="e.g. kamal@mail.com",key="f_email")
            st.markdown("**Vehicle & Pass Details**")
            col3, col4 = st.columns(2)
            with col3:
                f_plate = st.text_input("Vehicle Plate No.", placeholder="e.g. WP-CAB-9999", key="f_plate")
            with col4:
                f_pass_type = st.selectbox("Pass Type", list(PASS_TYPES.keys()), key="f_pass_type")
            cfg = PASS_TYPES[f_pass_type]
            st.markdown(f"""
<div style="background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.3);border-radius:12px;padding:14px 18px;margin:10px 0;">
  <b style="color:#6366f1;">Pass Summary:</b> <span style="color:#e2e8f0;">{f_pass_type}</span><br>
  <span style="color:#64748b;font-size:0.85rem;">🎫 {cfg['trips']} trips &nbsp;|&nbsp; ⏳ {cfg['validity_days']} days &nbsp;|&nbsp; 💰 LKR {cfg['price_lkr']:,} &nbsp;|&nbsp; 💵 USD {cfg['price_lkr']//300}</span>
</div>""", unsafe_allow_html=True)
            submitted = st.form_submit_button("💳 Purchase Pass", use_container_width=True)
            if submitted:
                errors = []
                if not f_name.strip():  errors.append("Full name is required.")
                if not f_nic.strip():   errors.append("NIC number is required.")
                if not f_plate.strip(): errors.append("Vehicle plate number is required.")
                if errors:
                    for e in errors: st.error(e)
                else:
                    expiry = purchase_pass(f_name.strip(), f_nic.strip(), f_phone.strip(), f_email.strip(), f_plate.strip().upper(), f_pass_type)
                    st.success(f"✅ Pass purchased for **{f_plate.upper()}** | Valid until **{expiry}** | {cfg['trips']} trips loaded")
                    st.balloons()

        st.markdown("#### 💰 Pass Pricing Overview")
        st.dataframe(pd.DataFrame([{
            "Pass Type": k, "Trips": v["trips"],
            "Validity (days)": v["validity_days"],
            "Price (LKR)": f"LKR {v['price_lkr']:,}",
            "Price (USD)": f"USD {v['price_lkr']//300}",
            "Per Trip (LKR)": f"LKR {v['price_lkr']//v['trips']:,}",
        } for k, v in PASS_TYPES.items()]), use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    st.set_page_config(
        page_title="AI Toll & Transit Pass System — IT6070 PoC",
        page_icon="🛣️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_css()
    init_db()
    seed_demo_data()
    header()
    tab1, tab2 = st.tabs([
        "🎥  Toll Gate Live Feed & ANPR Terminal",
        "🎫  Commuter Pass Portal & Subscriptions",
    ])
    with tab1:
        tab_anpr_terminal()
    with tab2:
        tab_commuter_portal()
    st.markdown("""
<hr>
<div style="text-align:center;padding:16px 0 8px;color:#334155;font-size:0.75rem;">
  IT6070 – Emerging Topics in Information Technology &nbsp;|&nbsp;
  AI-Powered Highway Toll &amp; Transit Pass System PoC &nbsp;|&nbsp;
  Week 1 &amp; 2 Milestone Deliverable<br>
  Edge Vision ANPR Platform — RDA Expressway Operation &amp; Maintenance Division, Sri Lanka
</div>""", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
