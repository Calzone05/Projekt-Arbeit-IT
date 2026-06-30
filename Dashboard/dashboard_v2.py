"""
Wohnungs-Dashboard v2 — optisches Upgrade (Tkinter + MQTT)
Sidebar mit Uhr/Wetter, Kopfzeile, Canvas-Grundriss mit klickbaren
Lampen-Icons und eine Bottom-Bar mit Schnellzugriffen.
"""

import json
import math
import queue
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime

import tkinter as tk
from tkinter import font as tkfont
import paho.mqtt.client as mqtt

MQTT_HOST = "192.168.178.20"   # IP des PCs mit Mosquitto
MQTT_PORT = 1883

# Nuernberg
WEATHER_LAT = 49.4521
WEATHER_LON = 11.0767
WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={WEATHER_LAT}&longitude={WEATHER_LON}"
    "&current_weather=true"
    "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
    "&timezone=Europe%2FBerlin"
)
WEATHER_REFRESH_S = 15 * 60

msg_queue      = queue.Queue()
state_handlers = {}

# ── Farben ────────────────────────────────────────────────────────
C_BG       = "#0b1829"   # Boden / Canvas-Hintergrund
C_PANEL    = "#10253f"   # Sidebar-/Panel-Hintergrund
C_PANELHDR = "#9fc3d9"   # helle Panel-Kopfleiste (wie Referenzbild)
C_WALL     = "#2d5080"   # Wandfarbe
C_WIN      = "#4a9fd4"   # Fenstermarkierung (blau)
C_TEXT     = "#c8dff0"   # Haupttext
C_LABEL    = "#3a6080"   # Raumbezeichnungen
C_SUB      = "#5a85a8"   # Statustext
C_GREEN    = "#3ec97a"   # Licht AN
C_RED      = "#d95060"   # AUS-Button
C_BLUE     = "#4a9fd4"   # Messwerte
C_YELLOW   = "#e8b830"   # PIR aktiv / Lampe AN
C_GRAY     = "#1e3650"   # Licht AUS
C_BULB_OFF = "#3a4a5e"   # Lampe AUS (Glaskolben-Grau)

# ── Grundriss-Geometrie ───────────────────────────────────────────
CW, CH = 660, 490    # Canvas-Größe (Breite x Höhe)
WW     = 5           # Wandstärke in Pixeln

X_MID   = 220
Y_KE    = 185
Y_MID   = 300
X_BU    = 220
X_US    = 375

CX_LEFT   = X_MID // 2
CX_WOHN   = X_MID + (CW - X_MID) // 2
CX_BAD    = X_BU // 2
CX_UEBER  = X_BU + (X_US - X_BU) // 2
CX_SCHLAF = X_US + (CW - X_US) // 2

CY_KUECHE  = Y_KE // 2
CY_EINGANG = Y_KE + (Y_MID - Y_KE) // 2
CY_WOHN    = Y_MID // 2
CY_UNTEN   = Y_MID + (CH - Y_MID) // 2

# Alle Licht-Topics fuer Sammel-Aktionen (Bad ausgenommen, PIR-Automatik)
ALL_LIGHT_CMD_TOPICS = [
    "wohnung/kueche/licht/cmd",
    "wohnung/wohnbereich/licht1/cmd",
    "wohnung/wohnbereich/licht2/cmd",
    "wohnung/eingang/licht/cmd",
    "wohnung/uebergang/licht/cmd",
    "wohnung/schlafzimmer/licht/cmd",
]

# ── MQTT ──────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe("wohnung/#")
        msg_queue.put(("_status", "Verbunden"))
    else:
        msg_queue.put(("_status", f"Verbindung fehlgeschlagen (rc={rc})"))

def on_disconnect(client, userdata, rc):
    msg_queue.put(("_status", "Getrennt – versuche erneut…"))

def on_message(client, userdata, msg):
    msg_queue.put((msg.topic, msg.payload.decode("utf-8", errors="replace").strip()))

def _mqtt_thread(client):
    client.loop_forever()

# ── Wetter ──────────────────────────────────────────────────────────

WEATHER_GROUPS = {
    "clear": {0, 1},
    "cloud": {2, 3, 45, 48},
    "rain":  {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82},
    "snow":  {71, 73, 75, 77, 85, 86},
    "storm": {95, 96, 99},
}

def weather_group(code):
    for group, codes in WEATHER_GROUPS.items():
        if code in codes:
            return group
    return "cloud"

weather_queue = queue.Queue()

def fetch_weather_loop():
    while True:
        try:
            with urllib.request.urlopen(WEATHER_URL, timeout=10) as resp:
                data = json.loads(resp.read())
            cw = data["current_weather"]
            daily = data["daily"]
            result = {
                "temp": round(cw["temperature"]),
                "code": cw["weathercode"],
                "tmax": round(daily["temperature_2m_max"][0]),
                "tmin": round(daily["temperature_2m_min"][0]),
                "rain": daily["precipitation_probability_max"][0],
            }
            weather_queue.put(result)
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError) as e:
            weather_queue.put({"error": str(e)})
        time.sleep(WEATHER_REFRESH_S)


def draw_weather_icon(canvas, group):
    canvas.delete("all")
    if group == "clear":
        canvas.create_oval(22, 12, 50, 40, fill="#f5a623", outline="")
        for i in range(8):
            import math
            ang = i * math.pi / 4
            x1 = 36 + 22 * math.cos(ang)
            y1 = 26 + 22 * math.sin(ang)
            x2 = 36 + 30 * math.cos(ang)
            y2 = 26 + 30 * math.sin(ang)
            canvas.create_line(x1, y1, x2, y2, fill="#f5a623", width=2)
    elif group == "storm":
        canvas.create_oval(8, 22, 64, 50, fill="#7d8fa3", outline="")
        canvas.create_polygon(38, 28, 28, 48, 38, 48, 32, 64, 50, 40, 40, 40,
                              fill="#f5d020", outline="")
    elif group == "snow":
        canvas.create_oval(8, 18, 64, 44, fill="#cfd8dc", outline="")
        for x in (22, 36, 50):
            canvas.create_text(x, 56, text="*", fill="#ffffff",
                               font=("Segoe UI", 14, "bold"))
    elif group == "rain":
        canvas.create_oval(8, 14, 64, 40, fill="#90a4ae", outline="")
        for x in (22, 36, 50):
            canvas.create_line(x, 44, x - 4, 60, fill="#4a9fd4", width=2)
    else:  # cloud
        canvas.create_oval(18, 8, 46, 36, fill="#f5a623", outline="")
        canvas.create_oval(6, 22, 64, 50, fill="#cfd8dc", outline="")


class WeatherPanel(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=C_PANEL)

        hdr = tk.Label(self, text="Wetter heute", bg=C_PANELHDR, fg="#0b1829",
                       font=tkfont.Font(family="Segoe UI", size=10, weight="bold"),
                       anchor="w", padx=8, pady=4)
        hdr.pack(fill="x")

        body = tk.Frame(self, bg=C_PANEL, padx=10, pady=10)
        body.pack(fill="x")

        self._icon = tk.Canvas(body, width=72, height=68, bg=C_PANEL, highlightthickness=0)
        self._icon.pack(anchor="w")
        draw_weather_icon(self._icon, "cloud")

        row = tk.Frame(body, bg=C_PANEL)
        row.pack(anchor="w", pady=(4, 2))
        self._temp = tk.StringVar(value="—°")
        tk.Label(row, textvariable=self._temp, bg=C_PANEL, fg=C_TEXT,
                font=tkfont.Font(family="Segoe UI", size=24, weight="bold")).pack(side="left")

        minmax = tk.Frame(row, bg=C_PANEL)
        minmax.pack(side="left", padx=(10, 0))
        self._tmax = tk.StringVar(value="Max —°")
        self._tmin = tk.StringVar(value="Min —°")
        tk.Label(minmax, textvariable=self._tmax, bg=C_PANEL, fg=C_TEXT,
                font=tkfont.Font(family="Segoe UI", size=10)).pack(anchor="w")
        tk.Label(minmax, textvariable=self._tmin, bg=C_PANEL, fg=C_SUB,
                font=tkfont.Font(family="Segoe UI", size=10)).pack(anchor="w")

        self._rain = tk.StringVar(value="Regenrisiko —")
        tk.Label(body, textvariable=self._rain, bg=C_PANEL, fg=C_SUB,
                font=tkfont.Font(family="Segoe UI", size=9)).pack(anchor="w", pady=(4, 0))

    def update_weather(self, data):
        if "error" in data:
            self._rain.set("Wetterdaten nicht erreichbar")
            return
        self._temp.set(f"{data['temp']}°")
        self._tmax.set(f"Max {data['tmax']}°")
        self._tmin.set(f"Min {data['tmin']}°")
        self._rain.set(f"Regenrisiko {data['rain']:.0f} %")
        draw_weather_icon(self._icon, weather_group(data["code"]))


class ClockPanel(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=C_PANEL, padx=12, pady=14)
        self._time = tk.StringVar()
        self._date = tk.StringVar()
        tk.Label(self, textvariable=self._time, bg=C_PANEL, fg=C_TEXT,
                font=tkfont.Font(family="Segoe UI", size=30, weight="bold")).pack(anchor="w")
        tk.Label(self, textvariable=self._date, bg=C_PANEL, fg=C_SUB,
                font=tkfont.Font(family="Segoe UI", size=11)).pack(anchor="w")
        self._tick()

    def _tick(self):
        now = datetime.now()
        self._time.set(now.strftime("%H:%M"))
        self._date.set(now.strftime("%d.%m.%Y"))
        self.after(1000, self._tick)


class StatusPanel(tk.Frame):
    """Ersetzt den Muellkalender aus dem Referenzbild durch echte Projektdaten:
    MQTT-Verbindungsstatus und letztes Ereignis."""
    def __init__(self, parent):
        super().__init__(parent, bg=C_PANEL)
        hdr = tk.Label(self, text="Status", bg=C_PANELHDR, fg="#0b1829",
                       font=tkfont.Font(family="Segoe UI", size=10, weight="bold"),
                       anchor="w", padx=8, pady=4)
        hdr.pack(fill="x")

        body = tk.Frame(self, bg=C_PANEL, padx=10, pady=10)
        body.pack(fill="x")

        self.status_var = tk.StringVar(value="Verbinde…")
        tk.Label(body, textvariable=self.status_var, bg=C_PANEL, fg=C_SUB,
                font=tkfont.Font(family="Courier New", size=9),
                wraplength=190, justify="left").pack(anchor="w")


# ── Steuer-Widgets ──────────────────────────────────────────────────

class BulbWidget(tk.Frame):
    """Klickbarer runder Lichtschalter mit Gluehbirnen-Symbol (Strahlen,
    Glaskolben, gerippter Sockel) in der Mitte: gelb = an, grau = aus."""
    PULSE_MIN_R   = 25   # kleinster Radius des Glow-Scheins waehrend des Pulsierens
    PULSE_MAX_R   = 29   # groesster Radius
    PULSE_COLOR_A = "#2a1f08"   # dunklerer Pulston
    PULSE_COLOR_B = "#5a4010"   # hellerer Pulston
    PULSE_STEP_MS = 60          # Animationsgeschwindigkeit

    def __init__(self, parent, label, state_topic, cmd_topic=None, mqtt_client=None):
        super().__init__(parent, bg=C_BG)
        self._mqtt = mqtt_client
        self._cmd  = cmd_topic
        self._on   = False
        self._pulse_phase   = 0.0
        self._pulse_running = False
        state_handlers[state_topic] = self._update

        self._cv = tk.Canvas(self, width=56, height=56, bg=C_BG, highlightthickness=0,
                             cursor="hand2" if cmd_topic else "arrow")
        self._cv.pack()

        cx, cy = 28, 28

        # Glow-Schein hinter dem runden Schalter (nur sichtbar wenn an)
        self._glow = self._cv.create_oval(2, 2, 54, 54, fill="", outline="")
        # runder Schalter
        self._bulb = self._cv.create_oval(8, 8, 48, 48, fill=C_BULB_OFF, outline=C_WALL, width=2)

        # Strahlen rund um den Glaskolben, nur sichtbar wenn an
        ICON = "#1a2540"
        self._rays = []
        for dx, dy in ((0, -1), (1, -1), (1, 0), (1, 1),
                       (0, 1), (-1, 1), (-1, 0), (-1, -1)):
            x1, y1 = cx + dx * 21, cy + dy * 21
            x2, y2 = cx + dx * 26, cy + dy * 26
            ray = self._cv.create_line(x1, y1, x2, y2, fill=ICON, width=2,
                                       capstyle="round", state="hidden")
            self._rays.append(ray)

        # Gluehbirne: runder Glaskolben + gerippter Sockel
        self._cv.create_oval(cx - 8, cy - 9, cx + 8, cy + 7,
                             fill="", outline=ICON, width=2)
        self._cv.create_arc(cx - 4, cy - 6, cx + 5, cy + 3,
                            start=300, extent=120, style="arc",
                            outline=ICON, width=1)
        for i in range(3):
            y = cy + 7 + i * 3
            self._cv.create_line(cx - 5, y, cx + 5, y, fill=ICON, width=2)

        if cmd_topic:
            self._cv.bind("<Button-1>", lambda e: self._toggle())

    def _toggle(self):
        self._send("0" if self._on else "1")

    def _update(self, v):
        was_on = self._on
        self._on = v in ("1", "ON", "on")
        state = "normal" if self._on else "hidden"
        for ray in self._rays:
            self._cv.itemconfig(ray, state=state)

        if self._on:
            self._cv.itemconfig(self._bulb, fill=C_YELLOW, outline="#fcd34d")
            if not was_on:
                self._start_pulse()
        else:
            self._cv.itemconfig(self._bulb, fill=C_BULB_OFF, outline=C_WALL)
            self._cv.coords(self._glow, 2, 2, 54, 54)
            self._cv.itemconfig(self._glow, fill="", outline="")

    @staticmethod
    def _lerp_color(c1, c2, t):
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _start_pulse(self):
        if self._pulse_running:
            return
        self._pulse_running = True
        self._pulse_phase = 0.0
        self._pulse_step()

    def _pulse_step(self):
        if not self._on or not self.winfo_exists():
            self._pulse_running = False
            return

        self._pulse_phase += 0.22
        t = (math.sin(self._pulse_phase) + 1) / 2   # pendelt zwischen 0 und 1
        r = self.PULSE_MIN_R + (self.PULSE_MAX_R - self.PULSE_MIN_R) * t
        cx, cy = 28, 28
        self._cv.coords(self._glow, cx - r, cy - r, cx + r, cy + r)
        self._cv.itemconfig(self._glow,
                            fill=self._lerp_color(self.PULSE_COLOR_A, self.PULSE_COLOR_B, t),
                            outline="")
        self.after(self.PULSE_STEP_MS, self._pulse_step)

    def _send(self, v):
        if self._mqtt and self._cmd:
            self._mqtt.publish(self._cmd, v)


class RolloWidget(tk.Frame):
    def __init__(self, parent, state_topic, cmd_topic, mqtt_client=None):
        super().__init__(parent, bg=C_BG)
        self._mqtt = mqtt_client
        self._cmd  = cmd_topic
        state_handlers[state_topic] = self._update

        fl = tkfont.Font(family="Segoe UI",   size=9)
        fv = tkfont.Font(family="Courier New", size=9, weight="bold")
        fb = tkfont.Font(family="Segoe UI",   size=9)

        row = tk.Frame(self, bg=C_BG)
        row.pack(pady=4)
        tk.Label(row, text="Rollo:", font=fl, bg=C_BG, fg=C_WIN).pack(side="left", padx=(0, 6))
        self._val = tk.StringVar(value="—")
        tk.Label(row, textvariable=self._val, font=fv,
                 bg=C_BG, fg=C_TEXT, width=4, anchor="w").pack(side="left", padx=(0, 8))
        tk.Button(row, text="↑ AUF", font=fb, bg=C_WIN, fg="#06111a",
                  relief="flat", padx=8, pady=2, cursor="hand2",
                  command=lambda: self._send("auf")).pack(side="left", padx=(0, 3))
        tk.Button(row, text="↓ ZU",  font=fb, bg=C_LABEL, fg="#c8dff0",
                  relief="flat", padx=8, pady=2, cursor="hand2",
                  command=lambda: self._send("zu")).pack(side="left")

    def _update(self, v):
        self._val.set(v.upper())

    def _send(self, v):
        if self._mqtt and self._cmd:
            self._mqtt.publish(self._cmd, v)


class SensorWidget(tk.Frame):
    def __init__(self, parent, label, state_topic, unit="", is_pir=False):
        super().__init__(parent, bg=C_BG)
        self._unit   = unit
        self._is_pir = is_pir
        state_handlers[state_topic] = self._update

        fl = tkfont.Font(family="Segoe UI",   size=10)
        fv = tkfont.Font(family="Courier New", size=10, weight="bold")

        row = tk.Frame(self, bg=C_BG)
        row.pack(anchor="w", pady=(3, 1))

        if is_pir:
            self._cv  = tk.Canvas(row, width=11, height=11, bg=C_BG, highlightthickness=0)
            self._dot = self._cv.create_oval(1, 1, 10, 10, fill=C_GRAY, outline=C_WALL)
            self._cv.pack(side="left", padx=(0, 5))

        tk.Label(row, text=label + ":", font=fl, bg=C_BG, fg=C_TEXT).pack(side="left", padx=(0, 5))
        self._val = tk.StringVar(value="—")
        tk.Label(row, textvariable=self._val, font=fv,
                 bg=C_BG, fg=C_YELLOW if is_pir else C_BLUE).pack(side="left")

    def _update(self, v):
        if self._is_pir:
            a = v == "1"
            self._cv.itemconfig(self._dot, fill=C_YELLOW if a else C_GRAY)
            self._val.set("Bewegung!" if a else "Ruhig")
        else:
            self._val.set(f"{v} {self._unit}".strip())

# ── Canvas-Grundriss ──────────────────────────────────────────────

class FloorPlan(tk.Canvas):
    def __init__(self, parent, mqtt_client):
        super().__init__(parent, width=CW, height=CH,
                         bg=C_BG, highlightthickness=0)
        self._mqtt = mqtt_client
        self._draw_walls()
        self._draw_labels()
        self._place_widgets()

    def _draw_walls(self):
        G = 48
        H = G // 2

        d_kw = Y_KE // 2
        d_ew = Y_KE + (Y_MID - Y_KE) // 2
        d_wu = X_MID + (X_US - X_MID) // 2
        d_bu = Y_MID + (CH - Y_MID) // 2
        d_us = Y_MID + (CH - Y_MID) // 2

        # Aussenwaende um die halbe Wandstaerke nach innen gerueckt,
        # damit sie nicht vom Canvas-Rand abgeschnitten werden
        o = WW // 2
        self.create_line(o,      o,      CW - o, o,      fill=C_WALL, width=WW)
        self.create_line(o,      CH - o, CW - o, CH - o, fill=C_WALL, width=WW)
        self.create_line(o,      o,      o,      CH - o, fill=C_WALL, width=WW)
        self.create_line(CW - o, o,      CW - o, CH - o, fill=C_WALL, width=WW)

        # Oberstes Stueck (an der Fenster-/Rollo-Seite) bleibt erhalten,
        # der Rest auf Kueche-Hoehe faellt weg
        self.create_line(X_MID, 0,          X_MID, d_kw - H, fill=C_WALL, width=WW)
        self.create_line(X_MID, Y_KE - WW // 2, X_MID, d_ew - H, fill=C_WALL, width=WW)
        self.create_line(X_MID, d_ew + H,   X_MID, d_bu - H, fill=C_WALL, width=WW)
        self.create_line(X_MID, d_bu + H,   X_MID, CH,       fill=C_WALL, width=WW)

        self.create_line(0, Y_KE, X_MID, Y_KE, fill=C_WALL, width=WW)

        # Uebergang geht offen in den Wohnbereich ueber: keine Wand zwischen X_MID und X_US
        self.create_line(0,    Y_MID, X_MID, Y_MID, fill=C_WALL, width=WW)
        self.create_line(X_US, Y_MID, CW,    Y_MID, fill=C_WALL, width=WW)

        self.create_line(X_US, Y_MID - WW // 2, X_US, d_us - H, fill=C_WALL, width=WW)
        self.create_line(X_US, d_us + H, X_US, CH,       fill=C_WALL, width=WW)

        self.create_line(X_MID, WW // 2, CW, WW // 2,
                         fill=C_WIN, width=WW + 3)

    def _draw_labels(self):
        fn = tkfont.Font(family="Courier New", size=9, weight="bold")
        labels = [
            ("KÜCHE",        CX_LEFT,  WW + 8),
            ("EINGANG",      CX_LEFT,  Y_KE + WW + 8),
            ("WOHNBEREICH",  CX_WOHN,  WW + 8),
            ("BAD",          CX_BAD,   Y_MID + WW + 8),
            ("ÜBERGANG",     CX_UEBER, Y_MID + WW + 8),
            ("SCHLAFZIMMER", CX_SCHLAF,Y_MID + WW + 8),
        ]
        for name, x, y in labels:
            self.create_text(x, y, text=name, font=fn,
                             fill=C_LABEL, anchor="n")

    def _place_widgets(self):
        c = self._mqtt

        f = tk.Frame(self, bg=C_BG)
        BulbWidget(f, "Küche",
                   state_topic="wohnung/kueche/licht/state",
                   cmd_topic  ="wohnung/kueche/licht/cmd",
                   mqtt_client=c).pack()
        self.create_window(CX_LEFT, CY_KUECHE + 15, window=f, anchor="center")

        f = tk.Frame(self, bg=C_BG)
        BulbWidget(f, "Eingang",
                   state_topic="wohnung/eingang/licht/state",
                   cmd_topic  ="wohnung/eingang/licht/cmd",
                   mqtt_client=c).pack()
        self.create_window(CX_LEFT, CY_EINGANG + 10, window=f, anchor="center")

        f = tk.Frame(self, bg=C_BG)
        RolloWidget(f,
                    state_topic="wohnung/fenster/rollo/state",
                    cmd_topic  ="wohnung/fenster/rollo/cmd",
                    mqtt_client=c).pack(anchor="center")
        tk.Frame(f, bg=C_WALL, height=1, width=260).pack(pady=(2, 4))
        row = tk.Frame(f, bg=C_BG)
        row.pack()
        BulbWidget(row, "Licht 1",
                   state_topic="wohnung/wohnbereich/licht1/state",
                   cmd_topic  ="wohnung/wohnbereich/licht1/cmd",
                   mqtt_client=c).pack(side="left", padx=10)
        BulbWidget(row, "Licht 2",
                   state_topic="wohnung/wohnbereich/licht2/state",
                   cmd_topic  ="wohnung/wohnbereich/licht2/cmd",
                   mqtt_client=c).pack(side="left", padx=10)
        self.create_window(CX_WOHN, WW + 30, window=f, anchor="n")

        f = tk.Frame(self, bg=C_BG)
        BulbWidget(f, "Bad",
                   state_topic="wohnung/bad/licht/state",
                   cmd_topic  =None,
                   mqtt_client=c).pack()
        SensorWidget(f, "PIR",
                     state_topic="wohnung/bad/pir/state",
                     is_pir=True).pack(anchor="center")
        self.create_window(CX_BAD, CY_UNTEN + 10, window=f, anchor="center")

        f = tk.Frame(self, bg=C_BG)
        BulbWidget(f, "Übergang",
                   state_topic="wohnung/uebergang/licht/state",
                   cmd_topic  ="wohnung/uebergang/licht/cmd",
                   mqtt_client=c).pack()
        self.create_window(CX_UEBER, CY_UNTEN + 10, window=f, anchor="center")

        f = tk.Frame(self, bg=C_BG)
        BulbWidget(f, "Schlaf",
                   state_topic="wohnung/schlafzimmer/licht/state",
                   cmd_topic  ="wohnung/schlafzimmer/licht/cmd",
                   mqtt_client=c).pack()
        SensorWidget(f, "Temperatur",
                     state_topic="wohnung/schlafzimmer/temperatur/state",
                     unit="°C").pack(anchor="center")
        self.create_window(CX_SCHLAF, CY_UNTEN + 10, window=f, anchor="center")


# ── Bottom-Bar ──────────────────────────────────────────────────────

class BottomBar(tk.Frame):
    """Ersetzt die Kamera-/Auto-/Notfall-Icons aus dem Referenzbild durch
    Schnellzugriffe, die im Projekt tatsaechlich existieren."""
    def __init__(self, parent, mqtt_client):
        super().__init__(parent, bg=C_BG, pady=10)
        self._mqtt = mqtt_client

        actions = [
            ("Alle\nAN",  self._all_on),
            ("Alle\nAUS", self._all_off),
        ]
        for text, cmd in actions:
            self._make_icon(text, cmd).pack(side="left", padx=10)

    def _make_icon(self, text, command):
        btn = tk.Button(self, text=text, command=command,
                        bg=C_PANEL, fg=C_TEXT, activebackground=C_WALL,
                        font=tkfont.Font(family="Segoe UI", size=9, weight="bold"),
                        relief="flat", width=8, height=2, cursor="hand2")
        return btn

    def _all_on(self):
        for t in ALL_LIGHT_CMD_TOPICS:
            self._mqtt.publish(t, "1")

    def _all_off(self):
        for t in ALL_LIGHT_CMD_TOPICS:
            self._mqtt.publish(t, "0")


# ── Hauptfenster ──────────────────────────────────────────────────

class Dashboard(tk.Tk):
    def __init__(self, client):
        super().__init__()
        self.title("Wohnungs-Dashboard")
        self.configure(bg=C_BG)
        self.resizable(False, False)

        # Sidebar links
        sidebar = tk.Frame(self, bg=C_PANEL, width=230)
        sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(14, 8), pady=14)

        ClockPanel(sidebar).pack(fill="x")
        tk.Frame(sidebar, bg=C_BG, height=8).pack()
        self._weather = WeatherPanel(sidebar)
        self._weather.pack(fill="x")
        tk.Frame(sidebar, bg=C_BG, height=8).pack()
        self._status_panel = StatusPanel(sidebar)
        self._status_panel.pack(fill="x")

        # Kopfzeile ueber dem Grundriss
        header = tk.Label(self, text="Erdgeschoss", bg=C_PANELHDR, fg="#0b1829",
                          font=tkfont.Font(family="Segoe UI", size=11, weight="bold"),
                          anchor="w", padx=10, pady=6)
        header.grid(row=0, column=1, sticky="ew", padx=(0, 14), pady=(14, 0))

        FloorPlan(self, client).grid(row=1, column=1, padx=(0, 14), pady=(2, 0))

        BottomBar(self, client).grid(row=2, column=0, columnspan=2, sticky="ew")

        self._status = self._status_panel.status_var
        self.after(100, self._poll)
        self.after(200, self._poll_weather)

    def _poll(self):
        try:
            while True:
                topic, value = msg_queue.get_nowait()
                if topic == "_status":
                    self._status.set(value)
                elif topic in state_handlers:
                    state_handlers[topic](value)
                    parts = topic.split("/")
                    if len(parts) >= 3:
                        self._status.set(f"{parts[1]}/{parts[2]}: {value}")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _poll_weather(self):
        try:
            while True:
                data = weather_queue.get_nowait()
                self._weather.update_weather(data)
        except queue.Empty:
            pass
        self.after(1000, self._poll_weather)

# ── Start ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    except ConnectionRefusedError:
        print("Broker nicht erreichbar. Läuft Mosquitto?")
        raise SystemExit(1)

    threading.Thread(target=_mqtt_thread, args=(client,), daemon=True).start()
    threading.Thread(target=fetch_weather_loop, daemon=True).start()
    Dashboard(client).mainloop()
