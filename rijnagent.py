
import requests
from twilio.rest import Client
from datetime import datetime
import json
import os

# ------------------------------------------
# CONFIG
# ------------------------------------------

TWILIO_SID = ""
TWILIO_AUTH = ""
TWILIO_WHATSAPP = "whatsapp:+14155238886"
YOUR_WHATSAPP = "whatsapp:+31646260683"

PEGEL_BASE = "https://www.wasserstaende.de/webservices/rest-api/v2/stations"

STATIONS = {
    "BONN": "593647aa-9fea-43ec-a7d6-6476a76ae868",
    "KÖLN": "a6ee8177-107b-47dd-bcfd-30960ccc6e9c",
    "DÜSSELDORF": "8f7e5f92-1153-4f93-acba-ca48670c8ca9"
}

# ------------------------------------------
# HELPERS: OPSLAAN / LADEN VAN VORIGE METINGEN
# ------------------------------------------

def load_last_values(path="last_values.json"):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return {}

def save_last_values(values, path="last_values.json"):
    with open(path, "w") as f:
        json.dump(values, f)

# ------------------------------------------
# ACTUELE WATERSTAND OPHALEN
# ------------------------------------------

def fetch_waterlevel(uuid):
    url = f"{PEGEL_BASE}/{uuid}.json?includeTimeseries=true&includeCurrentMeasurement=true"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()

    for ts in data.get("timeseries", []):
        cm = ts.get("currentMeasurement")
        if cm and ts.get("unit", "").lower() == "cm":
            return {
                "station": data.get("shortname", "Onbekend"),
                "value": cm.get("value"),
                "timestamp": cm.get("timestamp")
            }
    return None

# ------------------------------------------
# VOORSPELLING (FORECAST) OPHALEN
# ------------------------------------------

def fetch_forecast(uuid):
    url = f"{PEGEL_BASE}/{uuid}.json?includeForecastTimeseries=true&hasTimeseries=WV"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()

    forecasts = []

    for ts in data.get("timeseries", []):
        if ts.get("shortname", "").upper() == "WV":
            for value in ts.get("forecast", []):
                forecasts.append({
                    "timestamp": value.get("timestamp"),
                    "value": value.get("value")
                })

    return forecasts

# ------------------------------------------
# CHECK: ALARM BIJ 24-UURS VOORSPELLING
# ------------------------------------------

def check_alarm(forecasts):
    if not forecasts:
        return None

    now = datetime.now().astimezone()
    limit = now.timestamp() + 24*3600

    for f in forecasts:
        try:
            t = datetime.fromisoformat(f["timestamp"].replace("Z", "+00:00"))
        except:
            continue

        if t.timestamp() <= limit:
            cm = f["value"]
            if cm > 500:
                return f"🚨 *HOOGWATER ALERT!* Verwacht > 5.00 m ({cm} cm) binnen 24 uur."
            if cm < 200:
                return f"⚠️ *LAAGWATER ALERT!* Verwacht < 2.00 m ({cm} cm) binnen 24 uur."

    return None

# ------------------------------------------
# CHECK: SNELLE STIJGING / DALING
# ------------------------------------------

def check_trend(station_name, current_value, last_values, threshold=5):
    if station_name not in last_values:
        return None

    try:
        prev = last_values[station_name]
    except:
        return None

    diff = current_value - prev

    if diff > threshold:
        return f"📈 *SNELLE STIJGING* bij {station_name}: +{diff} cm sinds vorige meting."
    elif diff < -threshold:
        return f"📉 *SNELLE DALING* bij {station_name}: {diff} cm sinds vorige meting."

    return None

# ------------------------------------------
# WHATSAPP VERZENDEN
# ------------------------------------------

def send_whatsapp(message):
    client = Client(TWILIO_SID, TWILIO_AUTH)
    client.messages.create(
        body=message,
        from_=TWILIO_WHATSAPP,
        to=YOUR_WHATSAPP
    )

# ------------------------------------------
# MAIN
# ------------------------------------------

if __name__ == "__main__":

    # VOORBEREIDING
    last_values = load_last_values()
    new_values = {}

    lines = [
        "🌊 *Rijn Waterstanden (ELWIS/PEGELONLINE)*",
        f"⏰ {datetime.now().strftime('%d-%m-%Y %H:%M')}\n"
    ]

    alarm_lines = []
    trend_lines = []

    # --------------------------------------
    # PER STATION (BONN, KÖLN, DÜSSELDORF)
    # --------------------------------------

    for name, uuid in STATIONS.items():
        try:
            # ACTUEEL
            d = fetch_waterlevel(uuid)

            if d:
                try:
                    dt = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00"))
                    t = dt.strftime("%d-%m-%Y %H:%M")
                except:
                    t = d["timestamp"]

                # Berichtregel
                lines.append(
                    f"*{name}*\n"
                    f"Waterstand: {d['value']} cm\n"
                    f"Gemeten: {t}\n"
                )

                # TREND
                new_values[name] = d['value']
                trend_msg = check_trend(name, d['value'], last_values)
                if trend_msg:
                    trend_lines.append(trend_msg)

            else:
                lines.append(f"*{name}*: ❌ Geen actuele waarde.\n")

            # VOORSPELLING
            forecasts = fetch_forecast(uuid)
            alarm = check_alarm(forecasts)
            if alarm:
                alarm_lines.append(f"*{name}*: {alarm}")

        except Exception as e:
            lines.append(f"*{name}*: ❌ Fout: {e}\n")

    # --------------------------------------
    # SAMENVOEGEN VAN MELDINGEN
    # --------------------------------------

    if alarm_lines:
        lines.append("\n🚨 *VOORSPELLING-ALARMEN*")
        lines.extend(alarm_lines)
    else:
        lines.append("\nGeen bijzondere voorspellingen binnen 24 uur.")

    if trend_lines:
        lines.append("\n📊 *SNELLE TREND MELDINGEN*")
        lines.extend(trend_lines)
    else:
        lines.append("\nGeen opvallende stijging of daling sinds vorige meting.")

    # Opslaan voor volgende run
    save_last_values(new_values)

    # Bericht versturen
    message = "\n".join(lines)
    send_whatsapp(message)

    print("WhatsApp-bericht verzonden.")
