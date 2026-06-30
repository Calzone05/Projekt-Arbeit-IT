import cv2
import mediapipe as mp
import paho.mqtt.client as mqtt
import time
import math

class UltimateSmartHomeController:
    def __init__(self):
        # --- MQTT Konfiguration ---
        self.broker = "192.168.178.20"
        self.port = 1883
        
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2, 
            client_id="UltimateSmartHomeGestureController"
        )
        
        # --- Räume & Funktionen laut neuer Spezifikation ---
        self.rooms = [
            {"name": "Wohnzimmer", "has_light": True, "light_topics": ["wohnung/wohnbereich/licht1", "wohnung/wohnbereich/licht2"], "has_blind": True, "blind_topic": "wohnung/fenster/rollo"},
            {"name": "Küche", "has_light": True, "light_topics": ["wohnung/kueche/licht"], "has_blind": False},
            {"name": "Schlafzimmer", "has_light": True, "light_topics": ["wohnung/schlafzimmer/licht"], "has_blind": True, "blind_topic": "wohnung/fenster/rollo"},
            {"name": "Bad", "has_light": True, "light_topics": ["wohnung/bad/licht"], "has_blind": False},
            {"name": "Eingang", "has_light": True, "light_topics": ["wohnung/eingang/licht"], "has_blind": False},
            {"name": "Übergang", "has_light": True, "light_topics": ["wohnung/uebergang/licht"], "has_blind": False}
        ]
        self.current_room_idx = 0  # Startet im Wohnzimmer
        
        # Mapping von Finger-Anzahl auf den jeweiligen Raum-Index (Laut Tabelle)
        self.room_finger_mapping = {
            5: 0,   # 5 Finger -> Wohnzimmer
            6: 1,   # 6 Finger -> Küche
            7: 2,   # 7 Finger -> Schlafzimmer
            8: 3,   # 8 Finger -> Bad
            9: 4,   # 9 Finger -> Eingang
            10: 5   # 10 Finger -> Übergang
        }
        
        # Alle Licht-Topics für globale Befehle (Faust)
        self.all_light_cmd_topics = [
            "wohnung/kueche/licht/cmd",
            "wohnung/wohnbereich/licht1/cmd",
            "wohnung/wohnbereich/licht2/cmd",
            "wohnung/eingang/licht/cmd",
            "wohnung/uebergang/licht/cmd",
            "wohnung/schlafzimmer/licht/cmd",
            "wohnung/bad/licht/cmd"
        ]
        
        # --- Interner Gesten-Speicher (Wiederholschutz) ---
        self.last_executed_gesture = None  
        self.last_command_time = 0
        self.cooldown_seconds = 0.6  
        
        # --- Speicher für Faust-Wechsel (Globaler Licht-Toggle) ---
        self.global_lights_toggle = True  # True = Alles AN, False = Alles AUS
        
        # --- Speicher für Raumwechsel-Verzögerung ---
        self.last_room_change_time = 0
        self.room_change_cooldown = 1.2  # Verhindert hektisches Hin- und Herspringen

        # --- MediaPipe Initialisierung (Für 2 Hände optimiert) ---
        self.mp_hands = mp.solutions.hands
        self.mp_drawing = mp.solutions.drawing_utils
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,  
            min_detection_confidence=0.5,  # Etwas gesenkt, damit die 2. Hand stabiler erkannt wird
            min_tracking_confidence=0.5
        )

    def connect_mqtt(self):
        try:
            print("[MQTT] Verbinde zum Mosquitto Broker...")
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
            print("[MQTT] Erfolgreich verbunden.")
            return True
        except Exception as e:
            print(f"[MQTT FEHLER] Verbindung fehlgeschlagen: {e}")
            return False

    def execute_gesture_action(self, gesture_id, gesture_name, action_function):
        current_time = time.time()
        if (current_time - self.last_command_time > self.cooldown_seconds) and (self.last_executed_gesture != gesture_id):
            print(f"\n[GESTE ERKANNT] {gesture_name}")
            action_function()
            self.last_executed_gesture = gesture_id
            self.last_command_time = current_time

    def count_fingers(self, hand_landmarks):
        """Zählt ausgestreckte Finger für EINE übergebene Hand."""
        finger_pairs = [(8, 5), (12, 9), (16, 13), (20, 17)]
        standard_fingers_up = 0
        
        wrist = hand_landmarks.landmark[0]
        mcp_middle = hand_landmarks.landmark[9]
        hand_size = math.sqrt((wrist.x - mcp_middle.x)**2 + (wrist.y - mcp_middle.y)**2 + (wrist.z - mcp_middle.z)**2)
        
        # 1. Die vier Standardfinger prüfen
        for tip_idx, mcp_idx in finger_pairs:
            tip = hand_landmarks.landmark[tip_idx]
            mcp = hand_landmarks.landmark[mcp_idx]
            
            if tip.y < mcp.y:
                dist = math.sqrt((tip.x - mcp.x)**2 + (tip.y - mcp.y)**2)
                if dist > hand_size * 0.4:
                    standard_fingers_up += 1
                    
        # 2. Daumen prüfen
        thumb_tip = hand_landmarks.landmark[4]
        index_mcp = hand_landmarks.landmark[5]
        thumb_dist = math.sqrt((thumb_tip.x - index_mcp.x)**2 + (thumb_tip.y - index_mcp.y)**2)
        
        thumb_is_up = thumb_dist > hand_size * 0.45
        
        return standard_fingers_up + (1 if thumb_is_up else 0)

    def _toggle_all_lights(self):
        """Faust-Funktion: Schaltet alle Lichter in der Wohnung um."""
        if self.global_lights_toggle:
            print("-> Faust: Schalte ALLE LICHTER ein")
            for topic in self.all_light_cmd_topics:
                self.client.publish(topic, "1")
            self.global_lights_toggle = False
        else:
            print("-> Faust: Schalte ALLE LICHTER aus")
            for topic in self.all_light_cmd_topics:
                self.client.publish(topic, "0")
            self.global_lights_toggle = True

    def run(self):
        if not self.connect_mqtt():
            print("[System] Beende Steuerung, da keine MQTT-Verbindung aufgebaut werden konnte.")
            return

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("[FEHLER] Kamera konnte nicht geöffnet werden.")
            return

        print("[System] Neue Gestensteuerung nach Spezifikation aktiv.")
        print("[Regeln] Faust = ALLE LICHTER toggeln (An / Aus)")
        print("[Regeln] 1 Finger = Licht AN | 2 Finger = Licht AUS")
        print("[Regeln] 3 Finger = Rollo AUF | 4 Finger = Rollo ZU")
        print("[Regeln] 5 bis 10 Finger = Direkt-Raumwechsel (5=Wohnzimmer, 6=Küche, ..., 10=Übergang)\n")

        try:
            while cap.isOpened():
                success, frame = cap.read()
                if not success: 
                    continue

                frame = cv2.flip(frame, 1)
                h, w, _ = frame.shape
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                results = self.hands.process(rgb_frame)
                total_detected_fingers = -1 

                if results.multi_hand_landmarks:
                    total_detected_fingers = 0
                    for hand_landmarks in results.multi_hand_landmarks:
                        self.mp_drawing.draw_landmarks(frame, hand_landmarks, self.mp_hands.HAND_CONNECTIONS)
                        total_detected_fingers += self.count_fingers(hand_landmarks)
                else:
                    self.last_executed_gesture = None 

                room = self.rooms[self.current_room_idx]
                current_time = time.time()

                # --- NEUES GESTEN-REGELWERK (Laut Word-Spezifikation) ---
                
                # 1. FAUST -> ALLE LICHTER TOGGELN (An / Aus)
                if total_detected_fingers == 0:
                    self.execute_gesture_action(
                        "global_faust_toggle", 
                        "Faust -> ALLE LICHTER TOGGLE (AN/AUS)", 
                        self._toggle_all_lights
                    )

                # 2. 1 FINGER -> LICHT IM AKTUELLEN RAUM AN
                elif total_detected_fingers == 1:
                    if room["has_light"]:
                        self.execute_gesture_action(
                            f"licht_an_{room['name']}", 
                            f"1 Finger -> {room['name']} Licht AN", 
                            lambda: [self.client.publish(f"{t}/cmd", "1") for t in room["light_topics"]]
                        )
                        
                # 3. 2 FINGER -> LICHT IM AKTUELLEN RAUM AUS
                elif total_detected_fingers == 2:
                    if room["has_light"]:
                        self.execute_gesture_action(
                            f"licht_aus_{room['name']}", 
                            f"2 Finger -> {room['name']} Licht AUS", 
                            lambda: [self.client.publish(f"{t}/cmd", "0") for t in room["light_topics"]]
                        )
                        
                # 4. 3 FINGER -> ROLLO IM AKTUELLEN RAUM AUF
                elif total_detected_fingers == 3:
                    if room["has_blind"]:
                        self.execute_gesture_action(
                            f"rollo_auf_{room['name']}", 
                            f"3 Finger -> {room['name']} Rollo AUF", 
                            lambda: self.client.publish(f"{room['blind_topic']}/cmd", "auf")
                        )
                        
                # 5. 4 FINGER -> ROLLO IM AKTUELLEN RAUM ZU
                elif total_detected_fingers == 4:
                    if room["has_blind"]:
                        self.execute_gesture_action(
                            f"rollo_zu_{room['name']}", 
                            f"4 Finger -> {room['name']} Rollo ZU", 
                            lambda: self.client.publish(f"{room['blind_topic']}/cmd", "zu")
                        )

                # 6. 5 BIS 10 FINGER -> DIREKTER RAUMWECHSEL
                elif total_detected_fingers in self.room_finger_mapping:
                    target_room_idx = self.room_finger_mapping[total_detected_fingers]
                    target_room_name = self.rooms[target_room_idx]["name"]
                    
                    if (current_time - self.last_room_change_time > self.room_change_cooldown) and (self.current_room_idx != target_room_idx):
                        self.current_room_idx = target_room_idx
                        print(f"\n[RAUM-WECHSEL] {total_detected_fingers} Finger erkannt -> Gewechselt zu: {target_room_name}")
                        self.last_room_change_time = current_time
                        self.last_executed_gesture = f"wechsel_zu_{target_room_name}"
                        
                elif total_detected_fingers != -1:
                    self.last_executed_gesture = None

                # --- MONITOR / GRAFISCHES DISPLAY ---
                cv2.rectangle(frame, (0, 0), (w, 60), (35, 35, 35), -1)
                cv2.putText(frame, f"RAUM: {room['name']}", (20, 40), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
                
                # Dynamischer Hilfetext oben rechts basierend auf verfügbaren Funktionen im Raum
                help_text = "Licht vorhanden" + (" + Rollo" if room["has_blind"] else "")
                cv2.putText(frame, f"[{help_text}]", (w - 280, 38), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

                if total_detected_fingers != -1:
                    cv2.putText(frame, f"Geste: {total_detected_fingers} Finger", (20, h - 30), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                cv2.imshow('Smart-Home Gesture Control', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'): 
                    break

        finally:
            print("\n[System] Schließe Ressourcen und beende MQTT Loop...")
            cap.release()
            cv2.destroyAllWindows()
            self.client.loop_stop()
            self.client.disconnect()
            print("[System] Beendet.")

if __name__ == "__main__":
    controller = UltimateSmartHomeController()
    controller.run()