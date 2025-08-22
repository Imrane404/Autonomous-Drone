# 🚁 Autonomous Drone (Webots + Python)

A simulation project of an **autonomous drone** in [Webots](https://cyberbotics.com/) with:
- Object detection using **YOLOv8**
- Flight control (altitude, stabilization, yaw)
- Web interface for sending commands
- **WhatsApp alerts via Twilio** when an object is detected

---

## 📂 Project Structure


▶️ Running the Simulation

Open the autonomous_drone.wbt world in Webots

Webots will automatically run the Python controller drone_controller.py

Open the web interface (live feed + console):

http://localhost:5010



🎮 Available Commands

d → Take off

search bottle → Drone searches for a bottle

search person → Drone searches for a person

When an object is detected:

It will be highlighted in green in the video feed

A WhatsApp message will be sent via Twilio ✅



📌 Future Improvements

 Add more commands (landing, waypoint navigation, etc.)

 Optimize YOLO model for faster inference

 Save detection logs

 Docker deployment for easy setup

 Ability to control the drone via the local console

 Expand the number of objects that can be detected