
import os
import json
from datetime import datetime, timezone
import requests
from twilio.rest import Client

# =========================================================
# CONFIG
# =========================================================

TWILIO_SID = os.getenv("TWILIO_SID", "").strip()
TWILIO_AUTH = os.getenv("TWILIO_AUTH", "").strip()

TWILIO_WHATSAPP = os.getenv(
    "TWILIO_WHATSAPP",
    "whatsapp:+14155238886"  # Twilio sandbox
)
YOUR_WHATSAPP = os.getenv(
    "YOUR_WHATSAPP",
    "whatsapp:+31646260683"
)

PEGEL_BASE = "https://www.wasserstaende.de/webservices/rest-api/v2/stations"

STATIONS = {
    "BONN": "593647aa-9fea-43ec-a7d6-6476a76ae868",
    "KÖLN": "a6ee8177-107b-47dd-bcfd-30960ccc6e9c",
    "DÜSSELDORF": "8f7e5f92-1153-4f93-acba-ca48670c8ca9"
}

HIGH_WATER_CM = int(os.getenv("HIGH_WATER_CM", "500"))
LOW_WATER_CM = int(os.getenv("LOW_WATER_CM", "200"))
TREND_THRESHOLD_CM = int(os.getenv("TREND_THRESHOLD_CM", "5"))

LAST_VALUES_FILE = "last_values.json"

# =========================================================
# HULPFUNCTIES
# =========================================================

def validate_twilio():
    if not TWILIO_SID or not TWILIO_AUTH:
        raise RuntimeError("❌ TWILIO_SID of TWILIO_AUTH ontbreken")

def send_whatsapp(message: str):
    validate_twilio()
    client = Client(TWILIO_SID, TWILIO_AUTH)
    client.messages.create(
        body=message,
        from_=TWILIO_WHATSAPP,
        to=YOUR_WHATSAPP
    )

def load_last_values():
    if not os.path.exists(LAST_VALUES_FILE):
        return {}
    try:
        with open(LAST_VALUES_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_last_values(values):
    with open(LAST_VALUES_FILE, "w") as f:
        json.dump(values, f)

def iso_to_local(iso_ts):
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%d-%m-%Y %H:%M")
    except Exception:
        return iso_ts

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
            return float(cm["value"]), cm["timestamp"]
    return None, None

def fetch_forecast(uuid):
    url = f"{PEGEL_BASE}/{uuid}.json?includeForecastTimeseries=true&hasTimeseries=WV"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()

    out = []
    for ts in data.get("timeseries", []):
        if ts.get("shortname", "").upper() == "WV":
            for p in ts.get("forecast", []) or []:
                out.append((p["timestamp"], float(p["value"])))
    return out

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    last_values = load_last_values()
    new_values = {}

    lines = [
        "🌊 *Rijn Waterstanden (ELWIS / PEGELONLINE)*",
        f"⏰ {datetime.now().strftime('%d-%m-%Y %H:%M')}",
        ""
    ]

    trend_lines = []
    forecast_alerts = []

    for name, uuid in STATIONS.items():
        try:
            value, ts = fetch_current(uuid)

            if value is not None:
                new_values[name] = value
                lines.append(f"*{name}*")
                lines.append(f"Waterstand: {int(value)} cm")
                lines.append(f"Gemeten: {iso_to_local(ts)}")
                lines.append("")

                # Trend check
                if name in last_values:
                    diff = value - last_values[name]
                    if diff > TREND_THRESHOLD_CM:
                        trend_lines.append(
                            f"📈 *{name}* snelle stijging: +{int(diff)} cm / uur"
                        )
                    elif diff < -TREND_THRESHOLD_CM:
                        trend_lines.append(
                            f"📉 *{name}* snelle daling: {int(diff)} cm / uur"
                        )

                # Forecast check (24 uur)
                now = datetime.now(timezone.utc).timestamp()
                for f_ts, f_val in fetch_forecast(uuid):
                    t = datetime.fromisoformat(
                        f_ts.replace("Z", "+00:00")
                    ).timestamp()
                    if t <= now + 24*3600:
                        if f_val >= HIGH_WATER_CM:
                            forecast_alerts.append(
                                f"🚨 *{name}* HOOGWATER verwacht: {int(f_val)} cm"
                            )
                        if f_val <= LOW_WATER_CM:
                            forecast_alerts.append(
                                f"⚠️ *{name}* LAAGWATER verwacht: {int(f_val)} cm"
                            )

            else:
                lines.append(f"*{name}*: geen actuele data\n")

        except Exception as e:
            lines.append(f"*{name}* fout: {e}\n")

    # Extra meldingen toevoegen
    if forecast_alerts:
        lines.append("🚨 *VOORSPELLINGEN (24u)*")
        lines.extend(forecast_alerts)
        lines.append("")

    if trend_lines:
        lines.append("📊 *SNELLE TRENDS*")
        lines.extend(trend_lines)
        lines.append("")

    # =====================================================
    # ✅ VEILIGE AFSLUITER – ALTIJD VERZENDEN
    # =====================================================

    save_last_values(new_values)

    message = "\n".join(lines).strip()

    if not message:
        message = "ℹ️ Rijnagent draaide succesvol, maar er waren geen gegevens om te melden."

    print("DEBUG – WhatsApp-bericht dat wordt verzonden:\n")
    print(message)

    send_whatsapp(message)

    print("✅ WhatsApp-bericht succesvol verzonden vanuit rijnagent.py")
