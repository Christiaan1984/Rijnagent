
import os
import requests
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from twilio.rest import Client

# =========================================================
# CONFIG
# =========================================================

TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH")

TWILIO_WHATSAPP = "whatsapp:+14155238886"   # Twilio Sandbox
YOUR_WHATSAPP = "whatsapp:+31646260683"     # Jouw nummer

PEGEL_BASE = "https://www.wasserstaende.de/webservices/rest-api/v2/stations"

STATIONS = {
    "BONN": "593647aa-9fea-43ec-a7d6-6476a76ae868",
    "KÖLN": "a6ee8177-107b-47dd-bcfd-30960ccc6e9c",
    "DÜSSELDORF": "8f7e5f92-1153-4f93-acba-ca48670c8ca9",
}

HOURS_BACK = 48
GRAPH_DIR = "graphs"

# =========================================================
# TWILIO
# =========================================================

def send_whatsapp_text(text: str):
    client = Client(TWILIO_SID, TWILIO_AUTH)
    client.messages.create(
        body=text,
        from_=TWILIO_WHATSAPP,
        to=YOUR_WHATSAPP
    )

# =========================================================
# UTILITIES
# =========================================================

def ensure_graph_dir():
    """Zorg dat grafiekmap altijd bestaat."""
    if not os.path.exists(GRAPH_DIR):
        os.makedirs(GRAPH_DIR)

def safe_station_filename(name: str) -> str:
    """Zorgt voor ASCII bestandsnamen."""
    return (
        name.lower()
        .replace("ü", "u")
        .replace("ö", "o")
        .replace("ä", "a")
    )

# =========================================================
# DATA OPHALEN
# =========================================================

def fetch_current(uuid: str):
    """Haalt actuele waterstand (cm)."""
    url = f"{PEGEL_BASE}/{uuid}.json?includeTimeseries=true&includeCurrentMeasurement=true"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()

    for ts in data.get("timeseries", []):
        m = ts.get("currentMeasurement")
        if m and ts.get("unit", "").lower() == "cm":
            return int(float(m["value"]))
    return None

def fetch_history(uuid: str, hours: int):
    """Haalt historische waterstanden voor grafiek."""
    url = f"{PEGEL_BASE}/{uuid}.json?includeTimeseries=true"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()

    cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
    points = []

    for ts in data.get("timeseries", []):
        if ts.get("unit", "").lower() == "cm":
            for m in ts.get("measurements", []) or []:
                t = datetime.fromisoformat(
                    m["timestamp"].replace("Z", "+00:00")
                ).timestamp()
                if t >= cutoff:
                    points.append((t, float(m["value"])))

    return sorted(points)

# =========================================================
# GRAFIEK MAKEN
# =========================================================

def make_graph(station: str, points, filepath: str):
    times = [
        datetime.fromtimestamp(t).astimezone()
        for t, _ in points
    ]
    values = [v for _, v in points]

    plt.figure(figsize=(9, 4))
    plt.plot(times, values, linewidth=2)
    plt.title(f"Rijn – {station} – afgelopen 48 uur")
    plt.xlabel("Tijd")
    plt.ylabel("Waterstand (cm)")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(filepath)
    plt.close()

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    ensure_graph_dir()

    now_str = datetime.now().strftime("%d-%m-%Y %H:%M")

    message_lines = [
        "🌊 *Rijn Waterstanden – laatste 48 uur*",
        f"⏰ {now_str}",
        ""
    ]

    for station, uuid in STATIONS.items():
        try:
            current = fetch_current(uuid)
            history = fetch_history(uuid, HOURS_BACK)

            # Grafiek maken (indien data)
            if history:
                filename = (
                    f"{GRAPH_DIR}/"
                    f"{safe_station_filename(station)}_48u.png"
                )
                make_graph(station, history, filename)

            # Tekstregel
            if current is not None:
                message_lines.append(f"*{station}*: {current} cm")
            else:
                message_lines.append(f"*{station}*: geen actuele waarde")

        except Exception as e:
            message_lines.append(f"*{station}*: fout bij ophalen data")

    # ✅ Tekstbericht altijd versturen
    message = "\n".join(message_lines)
    send_whatsapp_text(message)

    print("✅ Tekstbericht verzonden")
    print("📁 Grafieken gegenereerd in ./graphs/")
``
