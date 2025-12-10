import asyncio
import json
import board
import busio
import hashlib
import secrets
import os  # NEU: Für Datei-Operationen
from aiohttp import web
from adafruit_servokit import ServoKit

# --- KONFIGURATION ---
i2c = busio.I2C(board.SCL, board.SDA)
kit = ServoKit(channels=16, i2c=i2c)

# PCA9685 Channels
PAN_CHANNEL = 10
TILT_CHANNEL = 11

# IPC: SHARED MEMORY PFAD
SHM_FILE = "/dev/shm/robot_status.json"

# --- SICHERHEIT Token für go2rtc ---
CAM_TOKEN = "aB7dE9fG2hJ5kL8mN1pQ"

# Globale Status Variablen
current_pan = 90
current_tilt = 90
client_connected = False
client_ip = "N/A"
client_name = "Niemand"

# Startposition
kit.servo[PAN_CHANNEL].angle = current_pan
kit.servo[TILT_CHANNEL].angle = current_tilt

print("Servos initialisiert.")


# --- IPC: SHARED MEMORY WRITE ---
def write_status():
    """Schreibt den aktuellen globalen Status ATOMAR in den RAM."""
    global current_pan, current_tilt, client_connected, client_ip, client_name

    data = {
        # Werte runden, damit JSON sauber bleibt
        "pan": round(current_pan, 1),
        "tilt": round(current_tilt, 1),
        "connected": client_connected,
        "client_ip": client_ip,
        "client_name": client_name
    }
    try:
        tmp_file = SHM_FILE + ".tmp"
        with open(tmp_file, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        # Atomares Verschieben verhindert, dass der Leser eine kaputte Datei erwischt
        os.replace(tmp_file, SHM_FILE)
    except Exception as e:
        print(f"Fehler beim Schreiben des Status: {e}")


# Initialer Status-Schreibvorgang
write_status()


# --- USER LADEN ---
def load_users():
    try:
        with open('users.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("WARNUNG: users.json nicht gefunden! Login wird fehlschlagen.")
        return {}


def verify_password(stored_password, provided_password):
    try:
        salt, stored_hash = stored_password.split('$')
        new_hash = hashlib.pbkdf2_hmac(
            'sha256',
            provided_password.encode('utf-8'),
            bytes.fromhex(salt),
            100000
        )
        return new_hash.hex() == stored_hash
    except Exception as e:
        print(f"Fehler bei Passwortprüfung: {e}")
        return False


# --- WEBSOCKET HANDLER ---
async def websocket_handler(request):
    global client_connected, current_pan, current_tilt, client_ip, client_name

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    authenticated = False
    current_user_ip = request.remote
    host = request.host.split(':')[0]

    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)

                # --- 1. LOGIN VERSUCH ---
                if 'type' in data and data['type'] == 'login':
                    users = load_users()
                    user = data.get('user')
                    pw = data.get('pass')

                    if user in users and verify_password(users[user], pw):
                        authenticated = True
                        client_connected = True
                        client_ip = current_user_ip
                        client_name = user

                        # STATUS UPDATE 1: Login erfolgreich
                        write_status()

                        # --- URL mit Token ---
                        auth_stream_url = f"http://{host}:1984/stream.html?src=cam&mode=webrtc&token={CAM_TOKEN}"

                        print(f"Login erfolgreich: {user}")

                        await ws.send_json({
                            "type": "login_success",
                            "user": user,
                            "stream_url": auth_stream_url
                        })
                    else:
                        print(f"Login fehlgeschlagen für: {user}")
                        await asyncio.sleep(1)
                        await ws.send_json({"type": "login_fail"})

                # --- 2. STEUERUNG ---
                elif authenticated:
                    if 'pan' in data and 'tilt' in data:
                        pan = float(data['pan'])
                        tilt = float(data['tilt'])

                        pan = max(0, min(180, pan))
                        tilt = max(0, min(180, tilt))
                        current_pan = pan
                        current_tilt = tilt

                        kit.servo[PAN_CHANNEL].angle = pan
                        kit.servo[TILT_CHANNEL].angle = tilt

                        # STATUS UPDATE 2: Bewegung
                        write_status()

            except Exception as e:
                print(f"Fehler: {e}")

    print("Verbindung geschlossen")
    if authenticated:
        client_connected = False
        client_name = "Niemand"
        client_ip = "N/A"

        # STATUS UPDATE 3: Disconnect
        write_status()

    return ws


# --- STATUS API HANDLER ---
# DIESER BLOCK WURDE ENTFERNT, da er nicht mehr benötigt wird.


# --- APP SETUP ---
async def index(request):
    return web.FileResponse('./index.html')


app = web.Application()
app.router.add_get('/', index)
app.router.add_get('/ws', websocket_handler)
# Entferne: app.router.add_get('/api/status', status_handler)

if __name__ == '__main__':
    print("Starte Roboter-Server auf Port 8080...")
    # Starte den Server weiterhin auf 0.0.0.0, damit das Websocket vom Client
    # noch erreicht werden kann. Nur der Status-Handler ist weg.
    web.run_app(app, host='0.0.0.0', port=8080)