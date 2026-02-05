# -*- coding: utf-8 -*-
"""
Rijnagent – Telegram-bericht + PNG-grafieken (48 uur) per station.
"""

import os
import requests
import matplotlib.pyplot as plt
from datetime import datetime

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()
SEND_PHOTOS        = os.getenv("SEND_PHOTOS", "false").strip().lower() in ("1", "true", "yes")

BASE = "https://www.wasserstaende.de/webservices/rest-api/v2"

STATIONS = {
    "BONN":              "593647aa-9fea-43ec-a7d6-6476a76ae868",
    "KÖLN":              "a6ee8177-107b-47dd-bcfd-30960ccc6e9c",
    "DÜSSELDORF":        "8f7e5f92-1153-4f93-acba-ca48670c8ca9",

    # ➕ Toegevoegd:
    "MANNHEIM":          "57090802-c51a-4d09-8340-b4453cd0e1f5",
    "BASEL-RHEINHALLE":  "94f6eff1-4f3f-4850-82e0-a086198e9ffd",
}

HOURS_BACK = 48
GRAPH_DIR = "graphs"
LOW_LINE  = int(os.getenv("LOW_LINE_CM", "200"))

# ---------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------
def tg_send_text(text, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()

def tg_send_photo(filepath, caption=None, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(filepath, "rb") as f:
        r = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": parse_mode},
            files={"photo": f},
            timeout=60
        )
    r.raise_for_status()

# ---------------------------------------------------------
# UTILS
# ---------------------------------------------------------
def ensure_graph_dir():
    if not os.path.exists(GRAPH_DIR):
        os.makedirs(GRAPH_DIR, exist_ok=True)

def safe_station_filename(name):
    return (name.lower()
            .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            .replace("ß", "ss"))

# ---------------------------------------------------------
# DATA
# ---------------------------------------------------------
def fetch_current(station_uuid):
    url = f"{BASE}/stations/{station_uuid}.json?includeTimeseries=true&includeCurrentMeasurement=true"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    for ts in data.get("timeseries", []) or []:
        cm = ts.get("currentMeasurement")
        if cm and (ts.get("unit") or "").lower() == "cm":
            return int(float(cm["value"]))
    return None

def fetch_history(station_uuid):
    url = f"{BASE}/stations/{station_uuid}/W/measurements.json?start=P2D"
    r = requests.get(url, timeout=45)
    r.raise_for_status()
    arr = r.json() or []

    out = []
    for m in arr:
        try:
            t = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")).timestamp()
            v = float(m["value"])
            out.append((t, v))
        except:
            pass

    out.sort(key=lambda x: x[0])
    return out

# ---------------------------------------------------------
# GRAPH
# ---------------------------------------------------------
def make_graph(station, points, filepath):
    MARGIN = 30

    if points:
        times  = [datetime.fromtimestamp(t).astimezone() for t, _ in points]
        values = [v for _, v in points]
        y_min = min(values + [LOW_LINE]) - MARGIN
        y_max = max(values + [LOW_LINE]) + MARGIN

        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(times, values, color="#1f77b4", linewidth=2)
        ax.set_ylim(y_min, y_max)
    else:
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.text(0.5, 0.5, "Geen data beschikbaar", ha="center", va="center", fontsize=14)
        y_min = min(0, LOW_LINE) - MARGIN
        y_max = LOW_LINE + MARGIN
        ax.set_ylim(y_min, y_max)

    ax.set_title(f"Rijn – {station} – laatste 48 uur")
    ax.set_xlabel("Tijd")
    ax.set_ylabel("Waterstand (cm)")
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.axhline(LOW_LINE, color="orange", linestyle="--", linewidth=1, label=f"{LOW_LINE} cm")
    ax.legend()

    fig.tight_layout()
    fig.savefig(filepath)
    plt.close(fig)

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    ensure_graph_dir()

    now = datetime.now().strftime("%d-%m-%Y %H:%M")
    lines = ["🌊 *Rijn Waterstanden*", f"⏰ {now}", ""]

    for station, uuid in STATIONS.items():
        current = fetch_current(uuid)
        history = fetch_history(uuid)

        fname = f"{GRAPH_DIR}/{safe_station_filename(station)}_48u.png"
        make_graph(station, history, fname)

        if current is not None:
            lines.append(f"*{station}*: {current} cm")
        else:
            lines.append(f"*{station}*: geen actuele waarde")

    tg_send_text("\n".join(lines))

    # --- FOTO’S STUREN (alle 5 stations, incl. Basel & Mannheim!) ---
    if SEND_PHOTOS:
        for station in STATIONS.keys():
            fname = f"{GRAPH_DIR}/{safe_station_filename(station)}_48u.png"
            tg_send_photo(fname, caption=f"{station} – laatste 48 uur")

if __name__ == "__main__":
    main()
