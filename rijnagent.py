
# Rijnagent – WhatsApp meldingen voor actuele en verwachte waterstanden Rijn
# Features:
#  - Actuele waterstanden (PEGELONLINE, officiële bron voor ELWIS)
#  - 24u voorspellings-alarmering (>500 cm of <200 cm)
#  - Trendmeldingen snelle stijging/daling (default 5 cm/uur)
#  - Persistente opslag vorige waarden in last_values.json
#
# Let op (GitHub Actions):
#  - Zet TWILIO_SID en TWILIO_AUTH als Secrets in je repo
#  - Workflow kan last_values.json ophalen/opslaan via artifacts

import os
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests
from twilio.rest import Client

# ------------------------------------------
# CONFIG
# ------------------------------------------

# Twilio-credentials uit omgevingsvariabelen (veilig voor GitHub Actions)
TWILIO_SID = os.getenv("TWILIO_SID", "").strip()
TWILIO_AUTH = os.getenv("TWILIO_AUTH", "").strip()

# Twilio WhatsApp zender (Sandbox) en jouw nummer
TWILIO_WHATSAPP = os.getenv("TWILIO_WHATSAPP", "whatsapp:+14155238886").strip()
YOUR_WHATSAPP = os.getenv("YOUR_WHATSAPP", "whatsapp:+31646260683").strip()

# PEGELONLINE basis-URL (officiële REST-API van WSV)
PEGEL_BASE = "https://www.wasserstaende.de/webservices/rest-api/v2/stations"

# Officiële PEGELONLINE UUID's voor de stations
STATIONS: Dict[str, str] = {
    "BONN": "593647aa-9fea-43ec-a7d6-6476a76ae868",
    "KÖLN": "a6ee8177-107b-47dd-bcfd-30960ccc6e9c",
    "DÜSSELDORF": "8f7e5f92-1153-4f93-acba-ca48670c8ca9",
}

# Alarmdrempels (in cm) – aanpasbaar via env
HIGH_WATER_CM = int(os.getenv("HIGH_WATER_CM", "500"))   # 5.00 m
LOW_WATER_CM  = int(os.getenv("LOW_WATER_CM",  "200"))   # 2.00 m

# Trenddrempel (in cm per uur) – aanpasbaar via env
TREND_THRESHOLD_CM = int(os.getenv("TREND_THRESHOLD_CM", "5"))

# Bestand voor trendvergelijking
LAST_VALUES_FILE = os.getenv("LAST_VALUES_FILE", "last_values.json")

# Request-timeout (seconden)
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "20"))


# ------------------------------------------
# HULPFUNCTIES (bestanden)
# ------------------------------------------

def load_last_values(path: str = LAST_VALUES_FILE) -> Dict[str, float]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            # forceer numeriek
            return {k: float(v) for k, v in data.items()}
    except Exception:
        return {}

def save_last_values(values: Dict[str, float], path: str = LAST_VALUES_FILE) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(values, f)
    except Exception:
        # In Actions is het geen ramp als dit faalt; workflow vangt artifacts af
        pass


# ------------------------------------------
# HULP: tijd formatteren
# ------------------------------------------

def iso_to_local_str(iso_ts: str) -> str:
    """
    Converteer ISO8601 (met Z of +offset) naar locale tijdstring "dd-mm-YYYY HH:MM".
    """
    try:
        ts = iso_ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        # Zet om naar lokale tijdzone van runner
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc).astimezone()
        else:
            dt = dt.astimezone()
        return dt.strftime("%d-%m-%Y %H:%M")
    except Exception:
        return iso_ts


# ------------------------------------------
# DATA-OPHALING (PEGELONLINE)
# ------------------------------------------

def fetch_waterlevel(uuid: str) -> Optional[Dict[str, str]]:
    """
    Haal actuele waterstand (cm) + timestamp op voor een station-UUID.
    """
    url = f"{PEGEL_BASE}/{uuid}.json?includeTimeseries=true&includeCurrentMeasurement=true"
    r = requests.get(url, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    data = r.json()

    for ts in data.get("timeseries", []):
        cm = ts.get("currentMeasurement")
        unit = (ts.get("unit") or "").lower()
        if cm and unit == "cm":
            value = cm.get("value")
            # Zorg dat value numeriek is
            try:
                value_num = float(value)
            except Exception:
                continue
            return {
                "station": data.get("shortname") or data.get("longname") or "Onbekend",
                "value_cm": value_num,
                "timestamp": cm.get("timestamp"),
            }
    return None


def fetch_forecast(uuid: str) -> List[Dict[str, float]]:
    """
    Haal voorspellingsreeks (WV = Wasserstandvorhersage) op.
    Geeft lijst met dicts: {"timestamp": str, "value": float}
    """
    url = f"{PEGEL_BASE}/{uuid}.json?includeForecastTimeseries=true&hasTimeseries=WV"
    r = requests.get(url, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    data = r.json()

    out: List[Dict[str, float]] = []
    for ts in data.get("timeseries", []):
        # Sommige timeseries kunnen meerdere velden hebben; we zoeken WV/forecast
        if (ts.get("shortname") or "").upper() == "WV":
            # Documentatie geeft een forecast-veld met punten
            for point in ts.get("forecast", []) or []:
                try:
                    val = float(point.get("value"))
                    out.append({
                        "timestamp": point.get("timestamp"),
                        "value": val
                    })
                except Exception:
                    continue
    return out


# ------------------------------------------
# ALARM-LOGICA
# ------------------------------------------

def check_forecast_alarm(forecasts: List[Dict[str, float]]) -> Optional[str]:
    """
    Checkt of er binnen 24 uur een waarde > HIGH_WATER_CM of < LOW_WATER_CM voorkomt.
    """
    if not forecasts:
        return None

    now = datetime.now(timezone.utc)
    horizon = now.timestamp() + 24 * 3600

    for f in forecasts:
        ts = f.get("timestamp")
        if not ts:
            continue
        try:
            ts_parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if ts_parsed.tzinfo is None:
                ts_parsed = ts_parsed.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        if ts_parsed.timestamp() <= horizon:
            v = f.get("value")
            if v is None:
                continue
            if v > HIGH_WATER_CM:
                return f"🚨 *HOOGWATER ALERT!* Verwacht > {HIGH_WATER_CM/100:.2f} m ({int(v)} cm) binnen 24 uur."
            if v < LOW_WATER_CM:
                return f"⚠️ *LAAGWATER ALERT!* Verwacht < {LOW_WATER_CM/100:.2f} m ({int(v)} cm) binnen 24 uur."

    return None


def check_trend(name: str, current_value_cm: float, last_values: Dict[str, float],
                threshold_cm: float = TREND_THRESHOLD_CM) -> Optional[str]:
    """
    Trendmelding bij snelle stijging/daling t.o.v. vorige meting (per uur).
    """
    if name not in last_values:
        return None
    try:
        prev = float(last_values[name])
    except Exception:
        return None

    diff = current_value_cm - prev
    if diff > threshold_cm:
        return f"📈 *SNELLE STIJGING* bij {name}: +{int(diff)} cm sinds vorige meting."
    if diff < -threshold_cm:
        return f"📉 *SNELLE DALING* bij {name}: {int(diff)} cm sinds vorige meting."
    return None


# ------------------------------------------
# NOTIFICATIE (Twilio WhatsApp)
# ------------------------------------------

def validate_twilio_creds():
    if not TWILIO_SID or not TWILIO_AUTH:
        raise RuntimeError(
            "Twilio-credentials ontbreken. Zorg voor TWILIO_SID en TWILIO_AUTH "
            "(env of GitHub Secrets)."
        )

def send_whatsapp(message: str) -> None:
    validate_twilio_creds()
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
    last_values = load_last_values()
    new_values: Dict[str, float] = {}

    header_time = datetime.now().astimezone().strftime("%d-%m-%Y %H:%M")
    lines: List[str] = [
        "🌊 *Rijn Waterstanden (ELWIS/PEGELONLINE)*",
        f"⏰ {header_time}\n"
    ]

    forecast_alarms: List[str] = []
    trend_msgs: List[str] = []

    for name, uuid in STATIONS.items():
        try:
            # Actuele waterstand
            cur = fetch_waterlevel(uuid)
            if cur:
                t_local = iso_to_local_str(cur["timestamp"])
                val = float(cur["value_cm"])
                new_values[name] = val

                lines.append(
                    f"*{name}*\n"
                    f"Waterstand: {int(val)} cm\n"
                    f"Gemeten: {t_local}\n"
                )

                # Trendmelding
                tr = check_trend(name, val, last_values)
                if tr:
                    trend_msgs.append(tr)
            else:
                lines.append(f"*{name}*: ❌ Geen actuele waarde.\n")

            # Voorspelling (24u)
            fc = fetch_forecast(uuid)
            alarm = check_forecast_alarm(fc)
            if alarm:
                forecast_alarms.append(f"*{name}*: {alarm}")

        except Exception as e:
            lines.append(f"*{name}*: ❌ Fout: {e}\n")

    # Secties toevoegen
    if forecast_alarms:
        lines.append("\n🚨 *VOORSPELLING-ALARMEN*")
        lines.extend(forecast_alarms)
    else:
        lines.append("\nGeen bijzondere voorspellingen binnen 24 uur.")

    if trend_msgs:
        lines.append("\n📊 *SNELLE TREND MELDINGEN*")
        lines.extend(trend_msgs)
    else:
        lines.append("\nGeen opvallende stijging of daling sinds vorige meting.")

    # Opslaan voor volgende run
    save_last_values(new_values)

send_whatsapp("✅ TEST vanuit rijnagent.py – Python verstuurt dit bericht correct.")
print("TEST WhatsApp verstuurd vanuit Python")
exit(0)


