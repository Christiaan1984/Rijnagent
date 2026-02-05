# -*- coding: utf-8 -*-
"""
Rijnagent – Telegram-bericht + PNG-grafieken met forecast
Basel: Forecast via BAFU hydrodaten (station 2289)
Koblenz: Forecast via WSV/ELWIS JSON
Andere stations: realtime via PEGELONLINE
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

PEGEL_BASE = "https://www.wasserstaende.de/webservices/rest-api/v2"

# STATIONS in gevraagde volgorde
STATIONS = {
    "BASEL-RHEINHALLE":  "94f6eff1-4f3f-4850-82e0-a086198e9ffd",
    "KOBLENZ":           "25900700",   # WSV / PEGELONLINE Koblenz (waterstand)
    "BONN":              "593647aa-9fea-43ec-a7d6-6476a76ae868",
    "KÖLN":              "a6ee8177-107b-47dd-bcfd-30960ccc6e9c",
    "DÜSSELDORF":        "8f7e5f92-1153-4f93-acba-ca48670c8ca9",
}

GRAPH_DIR = "graphs"
HOURS_BACK = 48
LOW_LINE = int(os.getenv("LOW_LINE_CM", "200"))

# ---------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------
def tg_send_text(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram secrets ontbreken.")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }, timeout=30).raise_for_status()

def tg_send_photo(filepath, caption=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(filepath, "rb") as f:
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption,
            "parse_mode": "Markdown"
        }, files={"photo": f}, timeout=60).raise_for_status()

# ---------------------------------------------------------
# UTIL
# ---------------------------------------------------------
def ensure_graph_dir():
    if not os.path.exists(GRAPH_DIR):
        os.makedirs(GRAPH_DIR, exist_ok=True)

def safe_station_filename(name):
    return (name.lower()
            .replace("ä","ae").replace("ö","oe").replace("ü","ue")
            .replace("ß","ss"))

# ---------------------------------------------------------
# FETCH REALTIME
# ---------------------------------------------------------
def fetch_current(uuid):
    url = f"{PEGEL_BASE}/stations/{uuid}.json?includeTimeseries=true&includeCurrentMeasurement=true"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()

    for ts in data.get("timeseries", []) or []:
        cm = ts.get("currentMeasurement")
        if cm and (ts.get("unit") or "").lower() == "cm":
            try:
                return int(float(cm["value"]))
            except:
                return None
    return None

def fetch_history(uuid):
    url = f"{PEGEL_BASE}/stations/{uuid}/W/measurements.json?start=P2D"
    r = requests.get(url, timeout=40)
    r.raise_for_status()
    arr = r.json() or []

    out = []
    for m in arr:
        try:
            t = datetime.fromisoformat(m["timestamp"].replace("Z","+00:00")).timestamp()
            v = float(m["value"])
            out.append((t,v))
        except:
            pass
    out.sort(key=lambda x: x[0])
    return out

# ---------------------------------------------------------
# BASEL FORECAST (BAFU)
# ---------------------------------------------------------
def fetch_forecast_basel():
    url = "https://www.hydrodaten.admin.ch/lhg/forecast?station=2289"
    r = requests.get(url, timeout=40)
    r.raise_for_status()
    data = r.json()

    out = []
    for p in data.get("predictions", []):
        try:
            t = datetime.fromisoformat(p["timestamp"].replace("Z","+00:00")).timestamp()
            v = float(p["value"])
            out.append((t, v))
        except:
            pass

    out.sort(key=lambda x: x[0])
    return out

# ---------------------------------------------------------
# KOBLENZ FORECAST (WSV / ELWIS)
# ---------------------------------------------------------
def fetch_forecast_koblenz():
    url = f"{PEGEL_BASE}/stations/25900700/W/forecast.json"
    r = requests.get(url, timeout=40)
    r.raise_for_status()
    arr = r.json() or []

    out = []
    for p in arr:
        try:
            t = datetime.fromisoformat(p["timestamp"].replace("Z","+00:00")).timestamp()
            v = float(p["value"])
            out.append((t,v))
        except:
            pass

    out.sort(key=lambda x: x[0])
    return out

# ---------------------------------------------------------
# GRAPH
# ---------------------------------------------------------
def make_graph(station, history, forecast, filepath):
    MARGIN = 30

    fig, ax = plt.subplots(figsize=(9,4))

    if history:
        times  = [datetime.fromtimestamp(t).astimezone() for t,_ in history]
        values = [v for _,v in history]
        ax.plot(times, values, color="#1f77b4", linewidth=2, label="Metingen")
        y_min = min(values+[LOW_LINE]) - MARGIN
        y_max = max(values+[LOW_LINE]) + MARGIN
    else:
        y_min = LOW_LINE - MARGIN
        y_max = LOW_LINE + MARGIN
        ax.text(0.5,0.5,"Geen data beschikbaar", ha="center", va="center",
                fontsize=14, transform=ax.transAxes)

    # Forecast
    if forecast:
        ftimes  = [datetime.fromtimestamp(t).astimezone() for t,_ in forecast]
        fvalues = [v for _,v in forecast]
        ax.plot(ftimes, fvalues, color="orange", linestyle="--",
                label="Voorspelling")

        # y-bounds moeten de forecast ook omvatten
        y_min = min([y_min]+fvalues) - MARGIN
        y_max = max([y_max]+fvalues) + MARGIN

    # As-limieten
    ax.set_ylim(y_min, y_max)

    # Hulplijn
    ax.axhline(LOW_LINE, color="red", linestyle="--", linewidth=1,
               label=f"{LOW_LINE} cm")

    # Opmaak
    ax.set_title(f"Rijn – {station} – laatste 48 uur + forecast")
    ax.set_xlabel("Tijd")
    ax.set_ylabel("Waterstand (cm)")
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="upper left")
    fig.tight_layout()

    fig.savefig(filepath)
    plt.close(fig)

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    ensure_graph_dir()

    now = datetime.now().strftime("%d-%m-%Y %H:%M")
    lines = [
        "🌊 *Rijn Waterstanden*",
        f"⏰ {now}",
        ""
    ]

    for station, uuid in STATIONS.items():
        # Fetch realtime
        current = fetch_current(uuid)

        # History
        history = fetch_history(uuid)

        # Forecast
        if station == "BASEL-RHEINHALLE":
            forecast = fetch_forecast_basel()
        elif station == "KOBLENZ":
            forecast = fetch_forecast_koblenz()
        else:
            forecast = []

        # Logging + berichttekst
        if current is not None:
            lines.append(f"*{station}*: {current} cm")
        else:
            lines.append(f"*{station}*: geen actuele waarde")

        # Grafiek
        fname = f"{GRAPH_DIR}/{safe_station_filename(station)}_48u.png"
        make_graph(station, history, forecast, fname)

    # Telegram tekst
    tg_send_text("\n".join(lines))

    # Foto's
    if SEND_PHOTOS:
        for station in STATIONS.keys():
            fname = f"{GRAPH_DIR}/{safe_station_filename(station)}_48u.png"
            tg_send_photo(fname, caption=f"{station} – 48u + forecast")

if __name__ == "__main__":
    main()
