
import os
import requests
import matplotlib.pyplot as plt
from datetime import datetime, timezone, timedelta
from twilio.rest import Client

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH")
TWILIO_WHATSAPP = "whatsapp:+14155238886"
YOUR_WHATSAPP   = "whatsapp:+31646260683"

BASE = "https://www.wasserstaende.de/webservices/rest-api/v2"

STATIONS = {
    "BONN":        "593647aa-9fea-43ec-a7d6-6476a76ae868",
    "KÖLN":        "a6ee8177-107b-47dd-bcfd-30960ccc6e9c",
    "DÜSSELDORF":  "8f7e5f92-1153-4f93-acba-ca48670c8ca9",
}

HOURS_BACK = 48
GRAPH_DIR = "graphs"

# Hulplijnen (cm)
LOW_LINE  = int(os.getenv("LOW_LINE_CM",  "200"))
HIGH_LINE = int(os.getenv("HIGH_LINE_CM", "500"))

# ---------------------------------------------------------
# TWILIO
# ---------------------------------------------------------
def send_whatsapp_text(text: str):
    if not TWILIO_SID or not TWILIO_AUTH:
        raise RuntimeError("TWILIO_SID/TWILIO_AUTH ontbreken.")
    client = Client(TWILIO_SID, TWILIO_AUTH)
    client.messages.create(body=text, from_=TWILIO_WHATSAPP, to=YOUR_WHATSAPP)

# ---------------------------------------------------------
# UTIL
# ---------------------------------------------------------
def ensure_graph_dir():
    if not os.path.exists(GRAPH_DIR):
        os.makedirs(GRAPH_DIR)

def safe_station_filename(name: str) -> str:
    return (name.lower()
                .replace("ä","ae").replace("ö","oe").replace("ü","ue").replace("ß","ss"))

# ---------------------------------------------------------
# DATA: current + history via officiële endpoints
# ---------------------------------------------------------
def fetch_current(station_uuid: str):
    url = f"{BASE}/stations/{station_uuid}.json?includeTimeseries=true&includeCurrentMeasurement=true"
    r = requests.get(url, timeout=30); r.raise_for_status()
    data = r.json()
    for ts in data.get("timeseries", []) or []:
        cm = ts.get("currentMeasurement")
        if cm and (ts.get("unit") or "").lower() == "cm":
            try: return int(float(cm["value"]))
            except: return None
    return None

def fetch_history(station_uuid: str, hours: int):
    """
    Gebruik station/W endpoint met start=P2D (laatste 2 dagen) zoals in de documentatie.
    Dit levert timestamp/value in cm terug, ideaal voor grafiek.
    """
    # P2D = laatste 2 dagen. (Zie PEGELONLINE REST-API docs)
    url = f"{BASE}/stations/{station_uuid}/W/measurements.json?start=P2D"
    r = requests.get(url, timeout=45); r.raise_for_status()
    arr = r.json() or []
    points = []
    for m in arr:
        try:
            t = datetime.fromisoformat(m["timestamp"].replace("Z","+00:00")).timestamp()
            v = float(m["value"])
            points.append((t, v))
        except:
            continue
    points.sort(key=lambda x: x[0])
    return points

# ---------------------------------------------------------
# GRAFIEK (met hulplijnen 200/500 cm)
# ---------------------------------------------------------
def make_graph(station: str, points, filepath: str):
    MARGIN = 30
    fig, ax = plt.subplots(figsize=(9,4))
    if points:
        times  = [datetime.fromtimestamp(t).astimezone() for t,_ in points]
        values = [v for _,v in points]
        ax.plot(times, values, linewidth=2, color="#1f77b4")

        y_min = min(values + [LOW_LINE])  - MARGIN
        y_max = max(values + [HIGH_LINE]) + MARGIN
        ax.set_ylim(y_min, y_max)
    else:
        y_min = min(0, LOW_LINE) - MARGIN
        y_max = HIGH_LINE + MARGIN
        ax.set_ylim(y_min, y_max)
        ax.text(0.5, 0.5, "Geen data beschikbaar", ha="center", va="center",
                transform=ax.transAxes, fontsize=14)

    ax.axhline(LOW_LINE,  color="orange", linestyle="--", linewidth=1, label=f"{LOW_LINE} cm")
    ax.axhline(HIGH_LINE, color="red",    linestyle="--", linewidth=1, label=f"{HIGH_LINE} cm")
    ax.legend(loc="upper left", frameon=True)

    ax.set_title(f"Rijn – {station} – afgelopen 48 uur")
    ax.set_xlabel("Tijd")
    ax.set_ylabel("Waterstand (cm)")
    ax.grid(True, which="both", linestyle=":", alpha=0.6)
    fig.tight_layout()
    fig.savefig(filepath); plt.close(fig)

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
if __name__ == "__main__":
    ensure_graph_dir()
    now_str = datetime.now().strftime("%d-%m-%Y %H:%M")
    lines = ["🌊 Rijn Waterstanden – laatste 48 uur", f"⏰ {now_str}", ""]

    for station, suid in STATIONS.items():
        try:
            current = fetch_current(suid)
            history = fetch_history(suid, HOURS_BACK)

            fname = f"{GRAPH_DIR}/{safe_station_filename(station)}_48u.png"
            make_graph(station, history, fname)

            if current is not None:
                lines.append(f"*{station}*: {current} cm")
            else:
                lines.append(f"*{station}*: geen actuele waarde")
        except Exception as e:
            lines.append(f"*{station}*: fout bij ophalen data")

    send_whatsapp_text("\n".join(lines))
    print("✅ Tekstbericht verzonden")
    print("📁 Grafieken gegenereerd in ./graphs/")
