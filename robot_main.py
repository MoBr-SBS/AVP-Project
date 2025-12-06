import asyncio
import json
import board
import busio
from aiohttp import web
from adafruit_servokit import ServoKit

# --- KONFIGURATION ---
i2c = busio.I2C(board.SCL, board.SDA)
kit = ServoKit(channels=16, i2c=i2c)

# PCA9685 Channels
PAN_CHANNEL = 10
TILT_CHANNEL = 11

# --- SICHERHEIT Token für go2rtc ---
# Muss mit dem 'token' in go2rtc.yaml übereinstimmen!
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


# --- USER LADEN ---
def load_users():
    try:
        with open('users.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("WARNUNG: users.json nicht gefunden! Login wird fehlschlagen.")
        return {}


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

                    if user in users and users[user] == pw:
                        authenticated = True
                        client_connected = True
                        client_ip = current_user_ip
                        client_name = user

                        # --- WICHTIG: URL mit Token bauen ---
                        # Alte Version (blockiert): http://user:pass@IP...
                        # Neue Version (erlaubt): http://IP...?token=...
                        auth_stream_url = f"http://{host}:1984/stream.html?src=cam&mode=webrtc&token={CAM_TOKEN}"

                        print(f"Login erfolgreich: {user}")

                        await ws.send_json({
                            "type": "login_success",
                            "user": user,
                            "stream_url": auth_stream_url
                        })
                    else:
                        print(f"Login fehlgeschlagen für: {user}")
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

            except Exception as e:
                print(f"Fehler: {e}")

    print("Verbindung geschlossen")
    if authenticated:
        client_connected = False
        client_name = "Niemand"
        client_ip = "N/A"

    return ws


# --- STATUS API HANDLER ---
async def status_handler(request):
    data = {
        "pan": round(current_pan, 1),
        "tilt": round(current_tilt, 1),
        "connected": client_connected,
        "client_ip": client_ip,
        "client_name": client_name,
        "system": "online"
    }
    return web.json_response(data)


# --- APP SETUP ---
async def index(request):
    return web.FileResponse('./index.html')


app = web.Application()
app.router.add_get('/', index)
app.router.add_get('/ws', websocket_handler)
app.router.add_get('/api/status', status_handler)

if __name__ == '__main__':
    print("Starte Roboter-Server auf Port 8080...")
    web.run_app(app, host='0.0.0.0', port=8080)
