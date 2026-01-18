import asyncio
import json
import board
import busio
import hashlib
import secrets
import os
import socket
from aiohttp import web
from adafruit_servokit import ServoKit


# --- 1. KONFIGURATION LADEN ---
def load_config():
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("FEHLER: config.json nicht gefunden! Bitte erstelle die Datei.")
        exit(1)


cfg = load_config()

# --- 2. HARDWARE INITIALISIERUNG ---
try:
    i2c = busio.I2C(board.SCL, board.SDA)
    kit = ServoKit(channels=16, i2c=i2c)
    print("[HW] Servo-Treiber erfolgreich initialisiert.")
except Exception as e:
    print(f"[HW] FEHLER: Servo-Treiber nicht gefunden ({e}). Simulationsmodus aktiv.")
    kit = None

# Globale Zustände
current_pan = 90
current_tilt = 90
client_connected = False
client_name = "Niemand"
client_ip = "N/A"  # --- ÄNDERUNG: Globale Variable für IP hinzugefügt


# --- 3. HELFER-FUNKTIONEN (Sicherheit & IP) ---

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    # .strip() entfernt unsichtbare Leerzeichen oder Zeilenumbrüche
    hashed = hashlib.sha256((salt + password.strip()).encode()).hexdigest()
    return f"{salt}${hashed}"


def verify_password(stored_password, provided_password):
    try:
        if not stored_password or '$' not in stored_password:
            return False
        salt, hashed = stored_password.split('$')
        # Wir berechnen den Hash des eingegebenen Passworts mit dem alten Salt
        new_hash = hash_password(provided_password, salt).split('$')[1]
        return new_hash == hashed
    except Exception as e:
        print(f"[DEBUG] Fehler in verify_password: {e}")
        return False


def load_users():
    try:
        with open(cfg['paths']['user_db'], 'r') as f:
            data = json.load(f)
            return data
    except Exception as e:
        print(f"[FEHLER] Konnte {cfg['paths']['user_db']} nicht laden: {e}")
        return {}


def save_users(users):
    try:
        with open(cfg['paths']['user_db'], 'w') as f:
            json.dump(users, f, indent=4)
        return True
    except:
        return False


def get_local_ips():
    ips = []
    try:
        for interface in socket.getaddrinfo(socket.gethostname(), None):
            ip = interface[4][0]
            if "." in ip and not ip.startswith("127."):
                if ip not in ips: ips.append(ip)
    except:
        pass
    return ips


# --- 4. SERVO LOGIK MIT REVERSE & LIMITS ---

def set_servo_angle(axis, angle):
    s_cfg = cfg['hardware'][axis]

    # Limits einhalten
    angle = max(s_cfg['min_angle'], min(s_cfg['max_angle'], angle))

    # Reverse Logik
    actual_angle = (180 - angle) if s_cfg['reverse'] else angle

    if kit:
        try:
            kit.servo[s_cfg['channel']].angle = actual_angle
        except Exception as e:
            print(f"[HW] Servo Fehler {axis}: {e}")

    return angle


def write_status():
    # Wir formatieren die Zahlen hier explizit als Strings mit einer Nachkommastelle,
    # damit in der JSON-Datei keine Fließkomma-Fehler entstehen.
    status = {
        "pan": f"{float(current_pan):.1f}",
        "tilt": f"{float(current_tilt):.1f}",
        "client_connected": client_connected,
        "client_name": client_name,
        "client_ip": client_ip
    }
    try:
        with open(cfg['paths']['shm_file'], 'w') as f:
            json.dump(status, f)
    except Exception as e:
        print(f"[SYS] Fehler beim Schreiben der Status-Datei: {e}")


# --- 5. WEBSOCKET HANDLER ---

async def websocket_handler(request):
    # --- ÄNDERUNG: client_ip als global markieren
    global current_pan, current_tilt, client_connected, client_name, client_ip

    client_ip = request.remote
    print(f"[SYS] Neue WebSocket-Verbindung: {client_ip}")

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    authenticated = False
    this_session_user = "Unbekannt"

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                msg_type = data.get('type')

                # LOGIN
                if msg_type == 'login':
                    users = load_users()
                    u = str(data.get('user', '')).strip()
                    p = str(data.get('pass', '')).strip()

                    print(f"[AUTH] Login-Versuch für User: '{u}' | {client_ip}")

                    if u in users:
                        print(f"[AUTH] User '{u}' gefunden. Prüfe Passwort...")
                        if verify_password(users[u], p):
                            authenticated = True
                            this_session_user = u

                            client_connected = True
                            client_name = u

                            print(f"[AUTH] LOGIN ERFOLGREICH: User '{u}' | {client_ip}")

                            server_ip = request.host.split(':')[0]
                            stream_name = "cam"  # Dein Stream-Name aus der go2rtc.yaml
                            target_url = f"http://{server_ip}:1984/stream.html?src={stream_name}"

                            await ws.send_json({
                                "type": "login_success",
                                "user": u,
                                "stream_url": target_url
                            })

                            write_status()
                        else:
                            print(f"[AUTH] PASSWORT FALSCH für '{u}'")
                            await ws.send_json({"type": "login_fail", "message": "Passwort falsch"})
                    else:
                        print(f"[AUTH] USER NICHT GEFUNDEN: '{u}'")
                        print(f"[DEBUG] Vorhandene User in Datei: {list(users.keys())}")
                        await ws.send_json({"type": "login_fail", "message": "Nutzer unbekannt"})

                # STEUERUNG
                elif authenticated and 'pan' in data and 'tilt' in data:
                    current_pan = set_servo_angle('pan', data['pan'])
                    current_tilt = set_servo_angle('tilt', data['tilt'])
                    write_status()

                # PASSWORT ÄNDERN
                elif authenticated and msg_type == 'change_password':
                    users = load_users()
                    if verify_password(users[this_session_user], data.get('old_pass')):
                        users[this_session_user] = hash_password(data.get('new_pass'))
                        if save_users(users):
                            await ws.send_json({"type": "pw_change_success"})
                    else:
                        await ws.send_json({"type": "pw_change_fail", "message": "Falsches Passwort"})

    finally:
        if authenticated:
            # --- ÄNDERUNG: IP beim Logout anzeigen und zurücksetzen
            print(f"[SYS] Logout: User '{client_name}' ({client_ip}) hat getrennt.")
            client_connected = False
            client_name = "Niemand"
            client_ip = "N/A"
            write_status()
    return ws


# --- 6. SERVER START ---

async def index(request):
    return web.FileResponse('./templates/index.html')


app = web.Application()
app.router.add_static('/static/', path='./static', name='static')
app.router.add_get('/', index)
app.router.add_get('/ws', websocket_handler)

if __name__ == '__main__':
    host = cfg['network']['host']
    port = cfg['network']['port']
    local_ips = get_local_ips()

    print("-" * 50)
    print(f"ROBOTER-SERVER GESTARTET auf Port {port}")
    for ip in local_ips:
        print(f"  > http://{ip}:{port}")
    print("-" * 50)

    # Servos in Startposition
    current_pan = set_servo_angle('pan', 90)
    current_tilt = set_servo_angle('tilt', 90)

    web.run_app(app, host=host, port=port)