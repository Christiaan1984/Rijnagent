
import os
import requests
import matplotlib.pyplot as plt
from datetime import datetime, timezone, timedelta
from twilio.rest import Client

# =========================================================
# CONFIG
# =========================================================

TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH")

TWILIO_WHATSAPP = "whatsapp:+14155238886"   # Twilio Sandbox
YOUR_WHATSAPP = "whatsapp:+31646260683"     # Jouw nummer

# PEGELONLINE v2 (officiële WSV API)
BASE = "https://www.wasserstaende.de/webservices/rest-api/v2"

# Officiële station-UUID's
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
    if not TWILIO_SID or not TWILIO_AUTH:
        raise RuntimeError("TWILIO_SID/TWILIO_AUTH ontbreken (Secrets/Env).")
    client = Client(TWILIO_SID, TWILIO_AUTH)
    client.messages.create(body=text, from_=TWILIO_WHATSAPP, to=YOUR_WHATSAPP)

# =========================================================
# UTILITIES
# =========================================================

def ensure_graph_dir():
    if not os.path.exists(GRAPH_DIR):
        os.makedirs(GRAPH_DIR)


def safe_station_filename(name: str) -> str:
    return (name.lower()
                .replace("ä", "ae")
                .replace("ö", "oe")
                .replace("ü", "ue")
                .replace("ß", "ss"))

def iso_z(dt: datetime) -> str:
    """ISO8601 met Z, in UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

# =========================================================
# DATA OPHALEN (PEGELONLINE)
# =========================================================

def fetch_current(station_uuid: str):
    """
    Haal de actuele meting (cm) op via de station-endpoint.
    """
    url = f"{BASE}/stations/{station_uuid}.json?includeTimeseries=true&includeCurrentMeasurement=true"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()

    # zoek een tijdreeks met unit 'cm' en currentMeasurement
    for ts in data.get("timeseries", []) or []:
        cm = ts.get("currentMeasurement")
        unit = (ts.get("unit") or "").lower()
        if cm and unit == "cm":
            try:
                return int(float(cm["value"]))
            except Exception:
                return None
    return None

def get_waterlevel_timeseries_uuid(station_uuid: str) -> str | None:
    """
    Haal de UUID van de waterstand-tijdreeks (unit cm) van een station op.
    """
    url = f"{BASE}/stations/{station_uuid}.json?includeTimeseries=true"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()

    # Kies de waterstand-reeks: unit 'cm'
    for ts in data.get("timeseries", []) or []:
        unit = (ts.get("unit") or "").lower()
        if unit == "cm":
            ts_uuid = ts.get("uuid")
            if ts_uuid:
                return ts_uuid
    return None

from datetime import timedelta  # bovenin staat dit waarschijnlijk al geïmporteerd

def fetch_history(station_uuid: str, hours: int):
    """
    Haalt de waterstands-metingen (W) van de afgelopen 'hours' uren op
    via de officiële PEGELONLINE endpoint:
      /stations/{station_uuid}/W/measurements.json
    We gebruiken hier start=P2D om 2 dagen historie op te halen.
    Documentatie: https://www.wasserstaende.de/webservice/dokuRestapi
    """

    # Gebruik een ISO-8601 periode i.p.v. absolute tijden:
    # P2D = laatste 2 dagen (48 uur); dit dekt jouw use-case precies.
    # Je kunt eventueel dynamisch afleiden uit 'hours', maar P2D is duidelijk en robuust.
    url = f"{BASE}/stations/{station_uuid}/W/measurements.json?start=P2D"

    r = requests.get(url, timeout=45)
    r.raise_for_status()
    measurements = r.json() or []

    points = []
    for m in measurements:
        try:
            # JSON: {"timestamp":"2026-01-21T04:00:00+01:00", "value": "312", ...}
            t = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")).timestamp()
            v = float(m["value"])
            points.append((t, v))
        except Exception:
            continue

    points.sort(key=lambda x: x[0])

    # Debug-logging in Actions: aantal punten + eerste/laatste tijdstempel
    if points:
        ts_first = datetime.fromtimestamp(points[0][0]).astimezone().strftime("%d-%m %H:%M")
        ts_last  = datetime.fromtimestamp(points[-1][0]).astimezone().strftime("%d-%m %H:%M")
        print(f"[DEBUG] Historie {station_uuid}: {len(points)} punten, van {ts_first} t/m {ts_last}")
    else:
        print(f"[DEBUG] Historie {station_uuid}: GEEN punten ontvangen")

    return points

# =========================================================
# GRAFIEK
# =========================================================

def make_graph(station: str, points, filepath: str):
    if not points:
        # Maak een placeholder zodat de workflow niet stokt
        plt.figure(figsize=(9, 4))
        plt.title(f"Rijn – {station} – afgelopen 48 uur")
        plt.text(0.5, 0.5, "Geen data beschikbaar", ha="center", va="center", fontsize=14)
        plt.axis("off")
        plt.tight_layout()
        plt.savefig(filepath)
        plt.close()
        return

    times = [datetime.fromtimestamp(t).astimezone() for t, _ in points]
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

    for station, st_uuid in STATIONS.items():
        try:
            current = fetch_current(st_uuid)
            # logische debug-regel voor Actions
            print(f"[DEBUG] Fetch current {station}: {current} cm")

            history = fetch_history(st_uuid, HOURS_BACK)
            print(f"[DEBUG] History punten {station} (laatste {HOURS_BACK}u): {len(history)}")

            # Grafiek bestandsnaam (ASCII)
            filename = f"{GRAPH_DIR}/{safe_station_filename(station)}_48u.png"
            make_graph(station, history, filename)

            # Tekst
            if current is not None:
                message_lines.append(f"*{station}*: {current} cm")
            else:
                message_lines.append(f"*{station}*: geen actuele waarde")

        except Exception as e:
            message_lines.append(f"*{station}*: fout bij ophalen data")
            print(f"[ERROR] {station}: {e}")

    # Altijd een tekstbericht sturen
    message = "\n".join(message_lines)
    send_whatsapp_text(message)

    print("✅ Tekstbericht verzonden")
    print("📁 Grafieken gegenereerd in ./graphs/")



