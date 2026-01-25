
# -*- coding: utf-8 -*-
"""
Rijnagent – WhatsApp-bericht + PNG-grafieken (48 uur) per station.
- WhatsApp tekst via Twilio (SID/AUTH uit omgevingsvariabelen)
- Historische data (48 uur) via PEGELONLINE:
    /stations/{UUID}/W/measurements.json?start=P2D
- Grafieken per station in ./graphs/
- Hulplijnen: alleen 200 cm (5 m lijn is verwijderd)

Opzet:
- Dit script verstuurt ALLEEN het tekstbericht.
- De workflow stuurt de grafieken als media-berichten (1 per bericht).

Benodigde ENV (GitHub Secrets/locaal):
- TWILIO_SID
- TWILIO_AUTH
Optioneel:
- LOW_LINE_CM (default 200)
"""

import os
import requests
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from twilio.rest import Client

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
TWILIO_SID = os.getenv("TWILIO_SID", "").strip()
TWILIO_AUTH = os.getenv("TWILIO_AUTH", "").strip()

TWILIO_WHATSAPP = "whatsapp:+14155238886"     # Twilio Sandbox
YOUR_WHATSAPP   = "whatsapp:+31646260683"     # Jouw nummer

# PEGELONLINE v2 (officiële WSV API)
BASE = "https://www.wasserstaende.de/webservices/rest-api/v2"

# Officiële station-UUID's (Rijn)
STATIONS = {
    "BONN":        "593647aa-9fea-43ec-a7d6-6476a76ae868",
    "KÖLN":        "a6ee8177-107b-47dd-bcfd-30960ccc6e9c",
    "DÜSSELDORF":  "8f7e5f92-1153-4f93-acba-ca48670c8ca9",
}

HOURS_BACK = 48
GRAPH_DIR = "graphs"

# Hulplijn (cm) – 5 m lijn verwijderd
LOW_LINE  = int(os.getenv("LOW_LINE_CM",  "200"))  # 200 cm

# ---------------------------------------------------------
# TWILIO
# ---------------------------------------------------------
def send_whatsapp_text(text: str):
    """Verstuur 1 WhatsApp-tekstbericht via Twilio."""
    if not TWILIO_SID or not TWILIO_AUTH:
        raise RuntimeError("TWILIO_SID/TWILIO_AUTH ontbreken (Secrets/Env).")
    client = Client(TWILIO_SID, TWILIO_AUTH)
    client.messages.create(body=text, from_=TWILIO_WHATSAPP, to=YOUR_WHATSAPP)

# ---------------------------------------------------------
# UTIL
# ---------------------------------------------------------
def ensure_graph_dir():
    """Zorg dat ./graphs/ bestaat."""
    if not os.path.exists(GRAPH_DIR):
        os.makedirs(GRAPH_DIR)

def safe_station_filename(name: str) -> str:
    """Veilige bestandsnaam (ASCII) op basis van station-naam."""
    return (name.lower()
                .replace("ä", "ae")
                .replace("ö", "oe")
                .replace("ü", "ue")
                .replace("ß", "ss"))

# ---------------------------------------------------------
# DATA: current + history via officiële endpoints
# ---------------------------------------------------------
def fetch_current(station_uuid: str):
    """
    Haal actuele waterstand (cm) op via station-endpoint:
      /stations/{uuid}.json?includeTimeseries=true&includeCurrentMeasurement=true
    """
    url = f"{BASE}/stations/{station_uuid}.json?includeTimeseries=true&includeCurrentMeasurement=true"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    for ts in data.get("timeseries", []) or []:
        cm = ts.get("currentMeasurement")
        if cm and (ts.get("unit") or "").lower() == "cm":
            try:
                return int(float(cm["value"]))
            except Exception:
                return None
    return None

def fetch_history(station_uuid: str, hours: int):
    """
    Historische metingen (cm) laatste 48 uur (P2D) via:
      /stations/{uuid}/W/measurements.json?start=P2D
    Geeft list[(timestamp_seconds, value_cm)].
    """
    url = f"{BASE}/stations/{station_uuid}/W/measurements.json?start=P2D"
    r = requests.get(url, timeout=45)
    r.raise_for_status()
    arr = r.json() or []

    points = []
    for m in arr:
        try:
            t = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")).timestamp()
            v = float(m["value"])
            points.append((t, v))
        except Exception:
            continue

    points.sort(key=lambda x: x[0])
    return points

# ---------------------------------------------------------
# GRAFIEK (alleen 200 cm hulplijn)
# ---------------------------------------------------------
def make_graph(station: str, points, filepath: str):
    """
    Tekent waterstand (cm) over laatste 48 uur + hulplijn op 200 cm.
    5 m-lijn is verwijderd. Y-as schaalt zodat 200 cm altijd zichtbaar is.
    """
    MARGIN = 30  # cm extra marge

    if points:
        times  = [datetime.fromtimestamp(t).astimezone() for t, _ in points]
        values = [v for _, v in points]

        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(times, values, linewidth=2, color="#1f77b4")

        # Y-as: altijd 200 cm in beeld
        y_min = min(values + [LOW_LINE])  - MARGIN
        y_max = max(values + [LOW_LINE])  + MARGIN
        ax.set_ylim(y_min, y_max)

        ax.set_title(f"Rijn – {station} – afgelopen 48 uur")
        ax.set_xlabel("Tijd")
        ax.set_ylabel("Waterstand (cm)")
        ax.grid(True, which="both", linestyle=":", alpha=0.6)

        # Alleen 200 cm hulplijn
        ax.axhline(LOW_LINE, color="orange", linestyle="--", linewidth=1, label=f"{LOW_LINE} cm")
        ax.legend(loc="upper left", frameon=True)

        fig.tight_layout()
        fig.savefig(filepath)
        plt.close(fig)

    else:
        # Placeholder-grafiek als (tijdelijk) geen punten
        fig, ax = plt.subplots(figsize=(9, 4))

        y_min = min(0, LOW_LINE) - MARGIN
        y_max = LOW_LINE + MARGIN
        ax.set_ylim(y_min, y_max)

        ax.set_title(f"Rijn – {station} – afgelopen 48 uur")
        ax.set_xlabel("Tijd")
        ax.set_ylabel("Waterstand (cm)")
        ax.grid(True, which="both", linestyle=":", alpha=0.6)

        ax.text(0.5, 0.5, "Geen data beschikbaar",
                ha="center", va="center", transform=ax.transAxes, fontsize=14)

        # Alleen 200 cm hulplijn
        ax.axhline(LOW_LINE, color="orange", linestyle="--", linewidth=1, label=f"{LOW_LINE} cm")
        ax.legend(loc="upper left", frameon=True)

        fig.tight_layout()
        fig.savefig(filepath)
        plt.close(fig)

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
if __name__ == "__main__":
    ensure_graph_dir()

    now_str = datetime.now().strftime("%d-%m-%Y %H:%M")
    message_lines = [
        "🌊 *Rijn Waterstanden – laatste 48 uur*",
        f"⏰ {now_str}",
        ""
    ]

    for station, suid in STATIONS.items():
        try:
            current = fetch_current(suid)
            history = fetch_history(suid, HOURS_BACK)

            # PNG-bestandsnaam per station (ASCII, vaste namen voor workflow)
            fname = f"{GRAPH_DIR}/{safe_station_filename(station)}_48u.png"
            make_graph(station, history, fname)

            if current is not None:
                message_lines.append(f"*{station}*: {current} cm")
            else:
                message_lines.append(f"*{station}*: geen actuele waarde")

            # Debug-hints in Actions-log
            print(f"[DEBUG] {station}: current={current} | punten={len(history)} | png={fname}")

        except Exception as e:
            message_lines.append(f"*{station}*: fout bij ophalen data")
            print(f"[ERROR] {station}: {e}")

    # WhatsApp-tekst sturen (grafieken stuurt de workflow als media)
    send_whatsapp_text("\n".join(message_lines))
    print("✅ Tekstbericht verzonden")
    print("📁 Grafieken gegenereerd in ./graphs/")
