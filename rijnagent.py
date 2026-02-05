# -*- coding: utf-8 -*-
"""
Rijnagent – Waterstanden + Forecast + Correlatie + Grafieken
Basel forecast via BAFU (station 2289)
Koblenz forecast via ELWIS/WSV JSON
"""

import os
import requests
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()
SEND_PHOTOS        = os.getenv("SEND_PHOTOS", "false").lower() in ("1","true","yes")

PEGEL_BASE = "https://www.wasserstaende.de/webservices/rest-api/v2"

STATIONS = {
    "BASEL-RHEINHALLE":  "94f6eff1-4f3f-4850-82e0-a086198e9ffd",
    "KOBLENZ":           "25900700",
    "BONN":              "593647aa-9fea-43ec-a7d6-6476a76ae868",
    "KÖLN":              "a6ee8177-107b-47dd-bcfd-30960ccc6e9c",
    "DÜSSELDORF":        "8f7e5f92-1153-4f93-acba-ca48670c8ca9",
}

GRAPH_DIR   = "graphs"
LOW_LINE    = int(os.getenv("LOW_LINE_CM","200"))

# ---------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------
def tg_send_text(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }, timeout=30).raise_for_status()

def tg_send_photo(path, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(path, "rb") as f:
        requests.post(url,
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "Markdown"},
            files={"photo": f},
            timeout=60
        ).raise_for_status()

# ---------------------------------------------------------
# UTIL
# ---------------------------------------------------------
def ensure_graph_dir():
    if not os.path.exists(GRAPH_DIR):
        os.makedirs(GRAPH_DIR, exist_ok=True)

def safe_station_filename(name):
    return (name.lower()
            .replace("ä","ae").replace("ö","oe").replace("ü","ue")
            .replace("ß","ss"))

# ---------------------------------------------------------
# REALTIME MEASUREMENTS
# ---------------------------------------------------------
def fetch_current(uuid):
    url = f"{PEGEL_BASE}/stations/{uuid}.json?includeTimeseries=true&includeCurrentMeasurement=true"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()

    for ts in data.get("timeseries",[]):
        cm = ts.get("currentMeasurement")
        if cm and ts.get("unit","").lower()=="cm":
            try: return int(float(cm["value"]))
            except: return None
    return None

def fetch_history(uuid):
    url = f"{PEGEL_BASE}/stations/{uuid}/W/measurements.json?start=P2D"
    r = requests.get(url, timeout=40)
    r.raise_for_status()

    out=[]
    for m in r.json() or []:
        try:
            t = datetime.fromisoformat(m["timestamp"].replace("Z","+00:00")).timestamp()
            v = float(m["value"])
            out.append((t,v))
        except: pass

    out.sort(key=lambda x:x[0])
    return out

# ---------------------------------------------------------
# BASEL FORECAST (BAFU Sonde/Trend)
# ---------------------------------------------------------
def fetch_forecast_basel():
    urls = [
        "https://www.hydrodaten.admin.ch/lhg/Sonde?station=2289&parameter=W",
        "https://www.hydrodaten.admin.ch/lhg/Trend?station=2289&parameter=W",
    ]

    for url in urls:
        try:
            r = requests.get(url, timeout=40)
            r.raise_for_status()
            data = r.json()
        except:
            continue

        out=[]
        # Sonde
        if "series" in data:
            for p in data["series"]:
                try:
                    t = datetime.fromisoformat(p["timestamp"].replace("Z","+00:00")).timestamp()
                    out.append((t,float(p["value"])))
                except: pass

        # Trend
        elif "trend" in data:
            for p in data["trend"]:
                try:
                    t = datetime.fromisoformat(p["timestamp"].replace("Z","+00:00")).timestamp()
                    out.append((t,float(p["value"])))
                except: pass

        if out:
            out.sort(key=lambda x:x[0])
            return out

    return []

# ---------------------------------------------------------
# KOBLENZ FORECAST (ELWIS JSON)
# ---------------------------------------------------------
def fetch_forecast_koblenz():
    url = "https://www.elwis.de/DE/dynamisch/Wasserstaende/Pegeleinzeln/json/_node.json?pegeluuid=25900700"
    try:
        r = requests.get(url, timeout=40)
        r.raise_for_status()
        data = r.json()
    except:
        return []

    out=[]

    if "forecast" in data:
        for p in data["forecast"]:
            try:
                t = datetime.fromisoformat(p["timestamp"].replace("Z","+00:00")).timestamp()
                out.append((t,float(p["value"])))
            except: pass

    if not out and "tendency" in data:
        for p in data["tendency"]:
            try:
                t = datetime.fromisoformat(p["timestamp"].replace("Z","+00:00")).timestamp()
                out.append((t,float(p["value"])))
            except: pass

    out.sort(key=lambda x:x[0])
    return out

# ---------------------------------------------------------
# CORRELATIE-MODULE
# ---------------------------------------------------------
def interpolate_series(points, step_seconds=3600):
    if not points:
        return [],[]
    points = sorted(points, key=lambda x:x[0])
    t = np.array([p[0] for p in points], dtype=float)
    v = np.array([p[1] for p in points], dtype=float)

    t_min, t_max = int(t[0]), int(t[-1])
    t_grid = np.arange(t_min, t_max+1, step_seconds)
    v_grid = np.interp(t_grid, t, v)
    return t_grid, v_grid

def compute_lag_hours(basel_points, target_points, max_lag=72):
    if not basel_points or not target_points:
        return None

    tb, vb = interpolate_series(basel_points)
    tt, vt = interpolate_series(target_points)

    if len(vb)<10 or len(vt)<10: return None

    t_start = max(tb[0], tt[0])
    t_end   = min(tb[-1], tt[-1])
    if t_end - t_start < 6*3600: return None

    mask_b = (tb>=t_start)&(tb<=t_end)
    mask_t = (tt>=t_start)&(tt<=t_end)
    vb = vb[mask_b]
    vt = vt[mask_t]

    if np.std(vb)==0 or np.std(vt)==0: return None

    vb = (vb-np.mean(vb))/np.std(vb)
    vt = (vt-np.mean(vt))/np.std(vt)

    best_lag=0
    best_corr=-999

    for lag in range(0,max_lag+1):
        if lag >= len(vt): break
        v_shift = vt[lag:]
        v_base  = vb[:len(v_shift)]
        if len(v_shift)<6: break
        corr = np.corrcoef(v_base, v_shift)[0,1]
        if corr>best_corr:
            best_corr=corr
            best_lag=lag

    return best_lag

# ---------------------------------------------------------
# GRAPH
# ---------------------------------------------------------
def make_graph(station, history, forecast, path):
    MARGIN=30
    fig, ax = plt.subplots(figsize=(9,4))

    if history:
        times=[datetime.fromtimestamp(t).astimezone() for t,_ in history]
        vals=[v for _,v in history]
        ax.plot(times, vals, color="#1f77b4", linewidth=2, label="Metingen")
        y_min=min(vals+[LOW_LINE])-MARGIN
        y_max=max(vals+[LOW_LINE])+MARGIN
    else:
        y_min=LOW_LINE-MARGIN
        y_max=LOW_LINE+MARGIN
        ax.text(0.5,0.5,"Geen data",ha="center",va="center")

    if forecast:
        ft=[datetime.fromtimestamp(t).astimezone() for t,_ in forecast]
        fv=[v for _,v in forecast]
        ax.plot(ft, fv, color="orange", linestyle="--", linewidth=2, label="Voorspelling")
        y_min=min([y_min]+fv)-MARGIN
        y_max=max([y_max]+fv)+MARGIN

    ax.set_ylim(y_min,y_max)
    ax.axhline(LOW_LINE, color="red", linestyle="--", label=f"{LOW_LINE} cm")

    ax.set_title(f"Rijn – {station} – 48u + forecast")
    ax.set_xlabel("Tijd")
    ax.set_ylabel("Waterstand (cm)")
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="upper left")

    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    ensure_graph_dir()

    now = datetime.now().strftime("%d-%m-%Y %H:%M")
    msg=["🌊 *Rijn Waterstanden + Forecast + Correlatie*", f"⏰ {now}", ""]

    # eerst Basel-history voor correlatie
    basel_hist = fetch_history(STATIONS["BASEL-RHEINHALLE"])

    # correlatie-doelen
    corr_text=[]

    def add_corr(label, target_hist):
        lag=compute_lag_hours(basel_hist, target_hist)
        if lag is not None:
            corr_text.append(f"{label}: ~{lag} uur")

    # per station
    for station, uuid in STATIONS.items():

        current = fetch_current(uuid)
        history = fetch_history(uuid)

        # welke forecast?
        if station=="BASEL-RHEINHALLE":
            forecast=fetch_forecast_basel()
        elif station=="KOBLENZ":
            forecast=fetch_forecast_koblenz()
        else:
            forecast=[]

        # telegramtekst
        if current is not None:
            msg.append(f"*{station}*: {current} cm")
        else:
            msg.append(f"*{station}*: geen actuele waarde")

        # correlatie
        if station=="DÜSSELDORF":
            add_corr("Basel → Düsseldorf", history)
        elif station=="KÖLN":
            add_corr("Basel → Köln", history)
        elif station=="BONN":
            add_corr("Basel → Bonn", history)

        # grafiek
        fname=f"{GRAPH_DIR}/{safe_station_filename(station)}_48u.png"
        make_graph(station, history, forecast, fname)

    # correlatieblok toevoegen
    if corr_text:
        msg.append("")
        msg.append("⏱ *Reistijd-correlatie (48u)*")
        msg += corr_text

    # verzenden
    tg_send_text("\n".join(msg))

    if SEND_PHOTOS:
        for station in STATIONS:
            fname=f"{GRAPH_DIR}/{safe_station_filename(station)}_48u.png"
            tg_send_photo(fname, f"{station} – 48u + forecast")

if __name__=="__main__":
    main()
