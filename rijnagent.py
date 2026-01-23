
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
