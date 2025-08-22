# console.py
import socket

HOST = '127.0.0.1'
PORT = 65432  # Port arbitraire, doit être le même côté Webots

print("📡 Console connectée. Tapez 'd' pour décoller ou 'exit' pour quitter.")
while True:
    msg = input(">> ").strip()
    if msg == "exit":
        break
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.connect((HOST, PORT))
            s.sendall(msg.encode('utf-8'))
        except ConnectionRefusedError:
            print("🚫 Le contrôleur Webots n'écoute pas encore.")
