
import os
import json
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

# =========================================================
# TWILIO HELPERS
# =========================================================

def send_whatsapp_text(message: str):
    client = Client(TWILIO_SID, TWILIO_AUTH)
    client.messages.create(
        body=message,
        from_=TWILIO_WHATSAPP,
        to=YOUR_WHATSAPP
    )

def send_whatsapp_image(image_path: str, caption: str):
    client = Client(TWILIO_SID, TWILIO_AUTH)
    upload = client.media.v1.uploads.create(
        file=open(image_path, "rb"),
        content_type="image/png"
    )
    client.messages.create(
        body=caption,
        media_url=[upload.url],
        from_=TWILIO_WHATSAPP,
        to=YOUR_WHATSAPP
    )

# =========================================================
# DATA OPHALEN
# =========================================================

def fetch_history(uuid: str, hours: int = 48):
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


def fetch_current(uuid: str):
    url = f"{PEGEL_BASE}/{uuid}.json?includeTimeseries=true&includeCurrentMeasurement=true"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()

    for ts in data.get("timeseries", []):
        cm = ts.get("currentMeasurement")
        if cm and ts.get("unit", "").lower() == "cm":
            return int(float(cm["value"]))
    return None

# =========================================================
# GRAFIEK MAKEN
# =========================================================

def make_graph(station: str, points, filename: str):
    times = [datetime.fromtimestamp(t).astimezone() for t, _ in points]
    values = [v for _, v in points]

    plt.figure(figsize=(8, 4))
    plt.plot(times, values, linewidth=2)
    plt.title(f"Rijn – {station} – afgelopen 48 uur")
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

    text_lines = [
        "🌊 *Rijn Waterstanden – laatste 48 uur*",
        f"⏰ {datetime.now().strftime('%d-%m-%Y %H:%M')}",
        ""
    ]

    generated_images = []

    for name, uuid in STATIONS.items():

        current = fetch_current(uuid)
        history = fetch_history(uuid, HOURS_BACK)

        if history:
            img_file = f"{name.lower()}_48u.png"
            make_graph(name, history, img_file)
            generated_images.append((img_file, f"📈 {name} – waterstand afgelopen 48 uur"))

        if current is not None:
            text_lines.append(f"*{name}*: {current} cm")
        else:
            text_lines.append(f"*{name}*: geen actuele waarde")

    # ✅ Tekstbericht versturen
    send_whatsapp_text("\n".join(text_lines))

    # ✅ Per station een grafiek versturen
    for img, caption in generated_images:
        send_whatsapp_image(img, caption)

    print("✅ WhatsApp-tekst + grafieken verzonden")
