from controller import Robot
import threading
import numpy as np
import cv2
from flask import Flask, Response, request, redirect
from ultralytics import YOLO
import time
from twilio.rest import Client
import os
from dotenv import load_dotenv  # <-- pour charger automatiquement le fichier .env

# Charger les variables du fichier .env (s'il existe)
load_dotenv()


def clamp(value, vmin, vmax):
    return min(max(value, vmin), vmax)


def send_alert(message):
    # ⚠️ Récupération sécurisée des identifiants depuis .env
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM_NUMBER", "whatsapp:+14155238886")  # valeur par défaut
    to_number = os.getenv("TWILIO_TO_NUMBER")

    if not account_sid or not auth_token or not to_number:
        print("❌ Impossible d'envoyer l'alerte : variables d'environnement Twilio manquantes.")
        return

    client = Client(account_sid, auth_token)
    msg = client.messages.create(
        body=message,
        from_=from_number,
        to=to_number
    )
    print(f"📲 Alerte envoyée : {msg.sid}")


class AutonomousMavic(Robot):
    K_VERTICAL_THRUST = 68.5
    K_VERTICAL_OFFSET = 0.6
    K_VERTICAL_P = 3.0
    K_ROLL_P = 50.0
    K_PITCH_P = 30.0

    def __init__(self):
        super().__init__()
        self.time_step = int(self.getBasicTimeStep())

        self.imu = self.getDevice("inertial unit")
        self.imu.enable(self.time_step)
        self.gps = self.getDevice("gps")
        self.gps.enable(self.time_step)
        self.gyro = self.getDevice("gyro")
        self.gyro.enable(self.time_step)

        self.camera = self.getDevice("camera")
        self.camera.enable(self.time_step)
        self.cam_width = self.camera.getWidth()
        self.cam_height = self.camera.getHeight()

        self.motors = {
            'front_left': self.getDevice("front left propeller"),
            'front_right': self.getDevice("front right propeller"),
            'rear_left': self.getDevice("rear left propeller"),
            'rear_right': self.getDevice("rear right propeller"),
        }
        for motor in self.motors.values():
            motor.setPosition(float('inf'))
            motor.setVelocity(1.0)

        self.flying = False
        self.target_altitude = 0.0
        self.command_queue = []
        self.searching = False
        self.search_label = ""
        self.current_search_label = ""
        self.current_detections = []
        self.flask_started = False
        self.yaw_override = 0.0

        import torch
        device = torch.device("cpu")
        self.yolo = YOLO("yolov8s.pt").to(device)

    def get_camera_image(self):
        raw = self.camera.getImage()
        if raw is None:
            return None
        img = np.zeros((self.cam_height, self.cam_width, 3), dtype=np.uint8)
        for y in range(self.cam_height):
            for x in range(self.cam_width):
                r = self.camera.imageGetRed(raw, self.cam_width, x, y)
                g = self.camera.imageGetGreen(raw, self.cam_width, x, y)
                b = self.camera.imageGetBlue(raw, self.cam_width, x, y)
                img[y, x] = [r, g, b]
        return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    def start_stream_server(self):
        app = Flask(__name__)
        command_ref = self.command_queue

        def generate():
            while True:
                img = self.get_camera_image()
                if img is None:
                    continue

                if self.current_search_label:
                    cv2.putText(
                        img,
                        self.current_search_label,
                        (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1,
                        (0, 0, 255),
                        2,
                        cv2.LINE_AA
                    )

                for (x1, y1, x2, y2, name) in self.current_detections:
                    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(
                        img,
                        name,
                        (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (0, 255, 0),
                        2,
                        cv2.LINE_AA
                    )

                _, buffer = cv2.imencode('.jpg', img)
                frame = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

        @app.route('/')
        def index():
            return '''
            <html>
            <head><title>Drone Control</title></head>
            <body style="text-align:center; font-family:sans-serif;">
                <h1>🎮 Drone Live Feed + Console</h1>
                <img src="/video" width="640"><br><br>
                <form method="post" action="/command">
                    <input type="text" name="cmd" placeholder="Enter command (e.g. d or search bottle)" size="40">
                    <input type="submit" value="Send">
                </form>
            </body>
            </html>
            '''

        @app.route('/video')
        def video_feed():
            return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

        @app.route('/command', methods=['POST'])
        def receive_command():
            cmd = request.form.get('cmd', '').strip().lower()
            if cmd:
                print(f"🌐 Commande web reçue : {cmd}")
                command_ref.append(cmd)
            return redirect('/')

        print("🌐 Interface web en ligne sur http://localhost:5010/")
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.DEBUG)
        app.run(host='0.0.0.0', port=5010, debug=False, use_reloader=False)

    def search_loop(self):
        print(f"🔎 Thread YOLO lancé pour : {self.search_label}")
        already_alerted = False

        while self.searching:
            frame = self.get_camera_image()
            if frame is None:
                continue

            results = self.yolo(frame)[0]
            new_detections = []

            for det in results.boxes.data.tolist():
                x1, y1, x2, y2, score, cls_id = det
                name = results.names[int(cls_id)]
                if name.lower() == self.search_label.lower():
                    new_detections.append((int(x1), int(y1), int(x2), int(y2), name))
                    print(f"✅ {name} détecté")
                    if not already_alerted:
                        send_alert(f"📡 Drone : Objet détecté -> {self.search_label}")
                        already_alerted = True

            self.current_detections = new_detections
            self.current_search_label = f"Found: {self.search_label}" if new_detections else f"Searching: {self.search_label}"

            if new_detections:
                self.yaw_override = 0.0

            time.sleep(0.1)

        print("🛑 Fin du thread YOLO")
        self.current_search_label = ""
        self.current_detections = []

    def run(self):
        print("Drone prêt. L'interface web s'initialise...")

        if not self.flask_started:
            threading.Thread(target=self.start_stream_server, daemon=True).start()
            self.flask_started = True

        while self.step(self.time_step) != -1:
            if self.command_queue:
                cmd = self.command_queue.pop(0)
                if cmd == "d":
                    self.flying = True
                    self.target_altitude = 1.0
                    print("🛫 Décollage déclenché.")
                elif cmd.startswith("search "):
                    target = cmd[7:].strip()
                    self.search_label = target
                    self.searching = True
                    self.yaw_override = 0.3
                    threading.Thread(target=self.search_loop, daemon=True).start()

            if self.flying:
                roll, pitch, yaw = self.imu.getRollPitchYaw()
                x, y, z = self.gps.getValues()
                roll_rate, pitch_rate, _ = self.gyro.getValues()

                roll_input = self.K_ROLL_P * clamp(roll, -1, 1) + roll_rate
                pitch_input = self.K_PITCH_P * clamp(pitch, -1, 1) + pitch_rate
                altitude_error = clamp(self.target_altitude - z + self.K_VERTICAL_OFFSET, -1, 1)
                vertical_input = self.K_VERTICAL_P * pow(altitude_error, 3)

                yaw_input = self.yaw_override

                self.motors['front_left'].setVelocity(self.K_VERTICAL_THRUST + vertical_input - roll_input + pitch_input - yaw_input)
                self.motors['front_right'].setVelocity(-(self.K_VERTICAL_THRUST + vertical_input + roll_input + pitch_input + yaw_input))
                self.motors['rear_left'].setVelocity(-(self.K_VERTICAL_THRUST + vertical_input - roll_input - pitch_input + yaw_input))
                self.motors['rear_right'].setVelocity(self.K_VERTICAL_THRUST + vertical_input + roll_input - pitch_input - yaw_input)
            else:
                for motor in self.motors.values():
                    motor.setVelocity(1.0)


# --- Bloc principal (à la toute fin) ---
if __name__ == "__main__":
    AutonomousMavic().run()
