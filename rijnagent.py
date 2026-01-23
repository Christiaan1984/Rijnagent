
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

TWILIO_WHATSAPP = "whatsapp:+14155238886"
YOUR_WHATSAPP = "whatsapp:+31646260683"

PEGEL_BASE = "https://www.wasserstaende.de/webservices/rest-api/v2/stations"

STATIONS = {
    "BONN": "593647aa-9fea-43ec-a7d6-6476a76ae868",
    "KÖLN": "a6ee8177-107b-47dd-bcfd-30960ccc6e9c",
    "DÜSSELDORF": "8f7e5f92-1153-4f93-acba-ca48670c8ca9"
}

HOURS_BACK = 48
GRAPH_DIR = "graphs"

# =========================================================
# TWILIO HELPERS
# =========================================================

def send_whatsapp_text(text):
    client = Client(TWILIO_SID, TWILIO_AUTH)
    client.messages.create(
        body=text,
        from_=TWILIO_WHATSAPP,
        to=YOUR_WHATSAPP
    )

# =========================================================
# DATA OPHALEN
# =========================================================

def fetch_current(uuid):
    url = f"{PEGEL_BASE}/{uuid}.json?includeTimeseries=true&includeCurrentMeasurement=true"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()

    for ts in data.get("timeseries", []):
        cm = ts.get("currentMeasurement")
        if cm and ts.get("unit", "").lower() == "cm":
            return int(float(cm["value"]))
    return None

def fetch_history(uuid, hours=48):
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

def ensure_graph_dir():
    if not os.path.exists(GRAPH_DIR):
        os.makedirs(GRAPH_DIR)

def make_graph(name, points, filename):
    times = [datetime.fromtimestamp(t).astimezone() for t, _ in points]
    values = [v for _, v in points]

    plt.figure(figsize=(9, 4))
    plt.plot(times, values, linewidth=2)
    plt.title(f"Rijn – {name} – afgelopen 48 uur")
    plt.xlabel("Tijd")
    plt.ylabel("Waterstand (cm)")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    ensure_graph_dir()

    text_lines = [
        "🌊 *Rijn Waterstanden – laatste 48 uur*",
        f"⏰ {datetime.now().strftime('%d-%m-%Y %H:%M')}",
        ""
    ]

    for name, uuid in STATIONS.items():
        current = fetch_current(uuid)
        history = fetch_history(uuid, HOURS_BACK)

        # Grafiek maken
        if history:
            file_name = f"{GRAPH_DIR}/{name.lower().replace('ü','u').replace('ö','o')}_48u.png"
            make_graph(name, history, file_name)

        # Tekstregel
        if current is not None:
            text_lines.append(f"*{name}*: {current} cm")
        else:
            text_lines.append(f"*{name}*: geen actuele waarde")

    # ✅ Tekstbericht versturen
    send_whatsapp_text("\n".join(text_lines))

    print("✅ Tekstbericht verzonden")
