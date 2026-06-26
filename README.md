# Projekt-Arbeit-IT — Wohnungs-Smart-Home

IT-Projektarbeit von Kilian Simonis und Markus Böhls.

Eine Wohnung wird über einen **ESP32-Mikrocontroller** automatisiert: Lichter,
ein Rollo (Servo), ein Temperatursensor (DHT11) und ein Bewegungsmelder (PIR)
werden per **MQTT** gesteuert.

---

## Architektur

```
┌─────────────┐   WLAN / MQTT   ┌──────────────────┐   MQTT   ┌──────────────┐
│   ESP32     │◄───────────────►│ Mosquitto Broker │◄────────►│ Dashboard.py │
│ (WLAN-Modul)│                 │  (lokaler PC)    │    │     │  (Tkinter)   │
└─────────────┘                 └──────────────────┘    │     └──────────────┘
                                                         │     ┌──────────────┐
                                                         └────►│ Gesture-     │
                                                               │ Control.py   │
                                                               └──────────────┘
```

Der ESP32 verbindet sich direkt per WLAN mit dem MQTT-Broker — es ist keine
zusätzliche Bridge oder ein Kabel zum PC nötig. Dashboard und Gestensteuerung
sind gewöhnliche MQTT-Clients und können auch auf einem anderen Gerät im
selben Netzwerk laufen.

---

## Projektstruktur

| Ordner/Datei | Inhalt |
|---|---|
| [`ESP32/esp32_mqtt/esp32_mqtt.ino`](ESP32/esp32_mqtt/esp32_mqtt.ino) | Arduino-Sketch für den ESP32 (WLAN + MQTT) |
| [`ESP32/schaltplan.svg`](ESP32/schaltplan.svg) | Schaltplan der Verkabelung |
| [`mosquitto/mosquitto.conf`](mosquitto/mosquitto.conf) | Konfiguration für den lokalen MQTT-Broker |
| `requirements.txt` | Python-Abhängigkeiten |

---

## Hardware

- ESP32-WROOM-32 Entwicklungsboard
- 6× LED + Vorwiderstand (Lichter)
- 1× Servo SG90 (Rollo)
- 1× DHT11 (Temperatursensor)
- 1× HC-SR501 (PIR-Bewegungsmelder)
- 1× Taster (zentrales An/Aus)
- Externe 5V-Spannungsversorgung für Servo/Sensoren (z. B. Elegoo Power MB V2),
  **nicht** über den ESP32 selbst

Details siehe [Schaltplan](ESP32/schaltplan.svg).

---

## Einrichtung

### 1. Voraussetzungen herunterladen

| Software | Link |
|---|---|
| Python 3.x | https://www.python.org/downloads/ |
| Arduino IDE | https://www.arduino.cc/en/software |
| Mosquitto MQTT-Broker | https://mosquitto.org/download/ |
| ESP32 Board-Treiber (CP210x) | https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers |
| ESP32 Board-Treiber (CH340) | https://www.wch.cn/downloads/CH341SER_EXE.html |

### 2. Python-Abhängigkeiten installieren

```powershell
pip install -r requirements.txt
```

### 3. Mosquitto-Broker starten

```powershell
& "C:\Program Files\mosquitto\mosquitto.exe" -c "mosquitto\mosquitto.conf" -v
```

### 4. ESP32 flashen

1. Arduino IDE öffnen → `Werkzeuge → Board → Boardverwalter` → `esp32` von Espressif installieren
2. Bibliotheken installieren: `PubSubClient`, `DHT sensor library` (Adafruit), `ESP32Servo`
3. In [`esp32_mqtt.ino`](ESP32/esp32_mqtt/esp32_mqtt.ino) WLAN-Zugangsdaten und Broker-IP eintragen
4. Board auf `ESP32 Dev Module` stellen, Sketch hochladen

---

## MQTT-Topic-Schema

```
wohnung/<raum>/<gerät>/cmd      ← Befehl senden
wohnung/<raum>/<gerät>/state    ← Zustand lesen
```
