from controller import Robot
import threading
import numpy as np
import cv2
from flask import Flask, Response, request, redirect
from ultralytics import YOLO
import time
from twilio.rest import Client
import os
from dotenv import load_dotenv  # <-- load environment variables automatically

# Load variables from .env file (if it exists)
load_dotenv()


def clamp(value, vmin, vmax):
    return min(max(value, vmin), vmax)


def send_alert(message):
    # ⚠️ Securely load Twilio credentials from environment variables
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM_NUMBER", "whatsapp:+14155238886")  # default value if not set
    to_number = os.getenv("TWILIO_TO_NUMBER")

    if not account_sid or not auth_token or not to_number:
        print("❌ Cannot send alert: missing Twilio environment variables.")
        return

    client = Client(account_sid, auth_token)
    msg = client.messages.create(
        body=message,
        from_=from_number,
        to=to_number
    )
    print(f"📲 Alert sent: {msg.sid}")


class AutonomousMavic(Robot):
    K_VERTICAL_THRUST = 68.5
    K_VERTICAL_OFFSET = 0.6
    K_VERTICAL_P = 3.0
    K_ROLL_P = 50.0
    K_PITCH_P = 30.0

    def __init__(self):
        super().__init__()
        self.time_step = int(self.getBasicTimeStep())

        # Sensors
        self.imu = self.getDevice("inertial unit")
        self.imu.enable(self.time_step)
        self.gps = self.getDevice("gps")
        self.gps.enable(self.time_step)
        self.gyro = self.getDevice("gyro")
        self.gyro.enable(self.time_step)

        # Camera
        self.camera = self.getDevice("camera")
        self.camera.enable(self.time_step)
        self.cam_width = self.camera.getWidth()
        self.cam_height = self.camera.getHeight()

        # Motors
        self.motors = {
            'front_left': self.getDevice("front left propeller"),
            'front_right': self.getDevice("front right propeller"),
            'rear_left': self.getDevice("rear left propeller"),
            'rear_right': self.getDevice("rear right propeller"),
        }
        for motor in self.motors.values():
            motor.setPosition(float('inf'))
            motor.setVelocity(1.0)

        # Drone state
        self.flying = False
        self.target_altitude = 0.0
        self.command_queue = []
        self.searching = False
        self.search_label = ""
        self.current_search_label = ""
        self.current_detections = []
