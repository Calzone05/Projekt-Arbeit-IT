/*
  Wohnungs-ESP32 — direkter MQTT-Client über WLAN
  Benötigte Bibliotheken (Arduino IDE → Bibliotheken verwalten):
    - "PubSubClient" von Nick O'Leary
    - "DHT sensor library" von Adafruit
    - "ESP32Servo" von Kevin Harrington

  WLAN + MQTT-Zugangsdaten in den drei #define-Blöcken unten eintragen.

  Pin-Belegung (ESP32 DevKit v1):
    GPIO2   LED Küche
    GPIO4   LED Wohnbereich 1
    GPIO5   LED Wohnbereich 2
    GPIO18  LED Eingang
    GPIO19  LED Bad        (wird vom PIR gesteuert)
    GPIO21  LED Übergang
    GPIO22  LED Schlafzimmer
    GPIO23  Servo Rollo    (PWM)
    GPIO15  DHT11 Data
    GPIO13  Taster         (gegen GND, INPUT_PULLUP)
    GPIO14  PIR Sensor
*/

#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <ESP32Servo.h>

// ── WLAN ──────────────────────────────────────────────────────────
#define WIFI_SSID  "De MorganLANd"
#define WIFI_PASS  "Ki30Si05"

// ── MQTT-Broker ───────────────────────────────────────────────────
#define MQTT_HOST  "192.168.178.20"   // IP des PCs mit Mosquitto
#define MQTT_PORT  1883
#define MQTT_ID    "esp32-wohnung"

// ── Pins ──────────────────────────────────────────────────────────
#define PIN_LED_KUECHE     2
#define PIN_LED_WOHN1      4
#define PIN_LED_WOHN2      5
#define PIN_LED_EINGANG    18
#define PIN_LED_BAD        19
#define PIN_LED_UEBERGANG  21
#define PIN_LED_SCHLAF     22
#define PIN_SERVO          23
#define PIN_DHT            15
#define PIN_TASTER         13
#define PIN_PIR            14

// ── Objekte ───────────────────────────────────────────────────────
DHT          dht(PIN_DHT, DHT11);
Servo        rollo;
WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

// ── Zustand ───────────────────────────────────────────────────────
bool licht_kueche    = false;
bool licht_wohn1     = false;
bool licht_wohn2     = false;
bool licht_eingang   = false;
bool licht_uebergang = false;
bool licht_schlaf    = false;
bool rollo_auf       = false;

bool pir_prev    = false;
bool taster_prev = HIGH;

unsigned long letztesSenden  = 0;
unsigned long letzterReconnect = 0;
const unsigned long SEND_INTERVAL     = 2000;
const unsigned long RECONNECT_INTERVAL = 5000;

// ── Hilfsfunktionen ───────────────────────────────────────────────

void setLicht(int pin, bool &zustand, bool an) {
  zustand = an;
  digitalWrite(pin, an ? HIGH : LOW);
}

void setAlleLichter(bool an) {
  setLicht(PIN_LED_KUECHE,    licht_kueche,    an);
  setLicht(PIN_LED_WOHN1,     licht_wohn1,     an);
  setLicht(PIN_LED_WOHN2,     licht_wohn2,     an);
  setLicht(PIN_LED_EINGANG,   licht_eingang,   an);
  setLicht(PIN_LED_UEBERGANG, licht_uebergang, an);
  setLicht(PIN_LED_SCHLAF,    licht_schlaf,    an);
}

bool irgendeinLichtAn() {
  return licht_kueche || licht_wohn1 || licht_wohn2 ||
         licht_eingang || licht_uebergang || licht_schlaf;
}

void mqttPublish(const char* topic, const char* value) {
  mqtt.publish(topic, value);
}

void sendeAlleZustaende() {
  mqttPublish("wohnung/kueche/licht/state",               licht_kueche    ? "1" : "0");
  mqttPublish("wohnung/wohnbereich/licht1/state",         licht_wohn1     ? "1" : "0");
  mqttPublish("wohnung/wohnbereich/licht2/state",         licht_wohn2     ? "1" : "0");
  mqttPublish("wohnung/eingang/licht/state",              licht_eingang   ? "1" : "0");
  mqttPublish("wohnung/bad/licht/state",                  digitalRead(PIN_LED_BAD) ? "1" : "0");
  mqttPublish("wohnung/uebergang/licht/state",            licht_uebergang ? "1" : "0");
  mqttPublish("wohnung/schlafzimmer/licht/state",         licht_schlaf    ? "1" : "0");
  mqttPublish("wohnung/fenster/rollo/state",              rollo_auf       ? "AUF" : "ZU");

  float temp = dht.readTemperature();
  if (!isnan(temp)) {
    char buf[8];
    dtostrf(temp, 4, 1, buf);
    mqttPublish("wohnung/schlafzimmer/temperatur/state", buf);
  }
}

// ── MQTT-Callback (eingehende Befehle) ────────────────────────────

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String t = String(topic);
  String v = "";
  for (unsigned int i = 0; i < length; i++) v += (char)payload[i];

  bool an = (v == "1");

  if      (t == "wohnung/kueche/licht/cmd")         setLicht(PIN_LED_KUECHE,    licht_kueche,    an);
  else if (t == "wohnung/wohnbereich/licht1/cmd")   setLicht(PIN_LED_WOHN1,     licht_wohn1,     an);
  else if (t == "wohnung/wohnbereich/licht2/cmd")   setLicht(PIN_LED_WOHN2,     licht_wohn2,     an);
  else if (t == "wohnung/eingang/licht/cmd")        setLicht(PIN_LED_EINGANG,   licht_eingang,   an);
  else if (t == "wohnung/uebergang/licht/cmd")      setLicht(PIN_LED_UEBERGANG, licht_uebergang, an);
  else if (t == "wohnung/schlafzimmer/licht/cmd")   setLicht(PIN_LED_SCHLAF,    licht_schlaf,    an);
  else if (t == "wohnung/fenster/rollo/cmd") {
    if (v == "auf") {
      rollo.write(90);
      rollo_auf = true;
      mqttPublish("wohnung/fenster/rollo/state", "AUF");
    } else if (v == "zu") {
      rollo.write(0);
      rollo_auf = false;
      mqttPublish("wohnung/fenster/rollo/state", "ZU");
    }
    return;  // Zustand schon gesendet, kein sendeAlleZustaende nötig
  }

  // Nach Lichtbefehl aktuellen State rückmelden
  sendeAlleZustaende();
}

// ── WLAN & MQTT verbinden ─────────────────────────────────────────

void verbindeWLAN() {
  Serial.print("[WiFi] Verbinde mit ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.print("\n[WiFi] Verbunden, IP: ");
  Serial.println(WiFi.localIP());
}

bool verbindeMQTT() {
  if (mqtt.connect(MQTT_ID)) {
    Serial.println("[MQTT] Verbunden");
    mqtt.subscribe("wohnung/+/+/cmd");
    sendeAlleZustaende();
    return true;
  }
  Serial.print("[MQTT] Fehler rc=");
  Serial.println(mqtt.state());
  return false;
}

// ── Setup ─────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);

  pinMode(PIN_LED_KUECHE,    OUTPUT);
  pinMode(PIN_LED_WOHN1,     OUTPUT);
  pinMode(PIN_LED_WOHN2,     OUTPUT);
  pinMode(PIN_LED_EINGANG,   OUTPUT);
  pinMode(PIN_LED_BAD,       OUTPUT);
  pinMode(PIN_LED_UEBERGANG, OUTPUT);
  pinMode(PIN_LED_SCHLAF,    OUTPUT);

  rollo.attach(PIN_SERVO);
  rollo.write(0);

  dht.begin();

  pinMode(PIN_TASTER, INPUT_PULLUP);
  pinMode(PIN_PIR,    INPUT);

  verbindeWLAN();

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(mqttCallback);
  verbindeMQTT();

  delay(2000);  // DHT11 Aufwärmzeit
}

// ── Loop ──────────────────────────────────────────────────────────

void loop() {

  // ── 1. WLAN + MQTT Reconnect ───────────────────────────────────
  if (WiFi.status() != WL_CONNECTED) {
    verbindeWLAN();
  }
  if (!mqtt.connected()) {
    unsigned long jetzt = millis();
    if (jetzt - letzterReconnect >= RECONNECT_INTERVAL) {
      letzterReconnect = jetzt;
      verbindeMQTT();
    }
  }
  mqtt.loop();

  // ── 2. Taster: zentrales An/Aus (Flankenerkennung) ─────────────
  bool taster_jetzt = digitalRead(PIN_TASTER);
  if (taster_jetzt == LOW && taster_prev == HIGH) {
    setAlleLichter(!irgendeinLichtAn());
    sendeAlleZustaende();
  }
  taster_prev = taster_jetzt;

  // ── 3. PIR: Bad-Licht automatisch steuern ──────────────────────
  bool pir_jetzt = digitalRead(PIN_PIR);
  if (pir_jetzt != pir_prev) {
    digitalWrite(PIN_LED_BAD, pir_jetzt ? HIGH : LOW);
    mqttPublish("wohnung/bad/pir/state",   pir_jetzt ? "1" : "0");
    mqttPublish("wohnung/bad/licht/state", pir_jetzt ? "1" : "0");
    pir_prev = pir_jetzt;
  }

  // ── 4. Alle Zustände periodisch senden ─────────────────────────
  if (millis() - letztesSenden >= SEND_INTERVAL) {
    if (mqtt.connected()) sendeAlleZustaende();
    letztesSenden = millis();
  }
}
