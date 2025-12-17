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


# --- KONFIGURATION ---
class Config:
    PAN_CHANNEL = 10
    TILT_CHANNEL = 11
    SHM_FILE = "/dev/shm/robot_status.json"
    CAM_TOKEN = "aB7dE9fG2hJ5kL8mN1pQ"
    HOST = '0.0.0.0'
    PORT = 8080


# --- HARDWARE INITIALISIERUNG ---
try:
    i2c = busio.I2C(board.SCL, board.SDA)
    kit = ServoKit(channels=16, i2c=i2c)
    print("Hardware: Servo-Treiber erfolgreich initialisiert.")
except Exception as e:
    print(f"Hardware-Fehler: Servo-Treiber nicht gefunden ({e}). Simulationsmodus aktiv.")
    kit = None

current_pan = 90
current_tilt = 90
client_connected = False
client_ip = "N/A"
client_name = "Niemand"

if kit:
    kit.servo[Config.PAN_CHANNEL].angle = current_pan
    kit.servo[Config.TILT_CHANNEL].angle = current_tilt


# --- STATUS SCHREIBEN ---
def write_status():
    global current_pan, current_tilt, client_connected, client_ip, client_name
    data = {
        "pan": round(current_pan, 1),
        "tilt": round(current_tilt, 1),
        "connected": client_connected,
        "client_ip": client_ip,
        "client_name": client_name
    }
    try:
        tmp_file = Config.SHM_FILE + ".tmp"
        with open(tmp_file, "w") as f:
            json.dump(data, f)
        os.replace(tmp_file, Config.SHM_FILE)
    except Exception as e:
        print(f"IPC-Fehler: {e}")


write_status()


# --- USER MANAGEMENT ---
def load_users():
    try:
        with open('users.json', 'r') as f:
            return json.load(f)
    except:
        return {}


def save_users(users_data):
    try:
        with open('users.json', 'w') as f:
            json.dump(users_data, f, indent=4)
        return True
    except:
        return False


def hash_password(password):
    salt = secrets.token_hex(16)
    new_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), 100000)
    return f"{salt}${new_hash.hex()}"


def verify_password(stored_password, provided_password):
    try:
        salt, stored_hash = stored_password.split('$')
        new_hash = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), bytes.fromhex(salt), 100000)
        return secrets.compare_digest(new_hash.hex(), stored_hash)
    except:
        return False


# --- NETZWERK-IP ERMITTLUNG ---
def get_local_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            s.connect(('10.254.254.254', 1))
            ips.append(s.getsockname()[0])
        except:
            pass
        finally:
            s.close()
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127.") and ip not in ips: ips.append(ip)
    except:
        pass
    return ips


# --- WEBSOCKET HANDLER ---
async def websocket_handler(request):
    global client_connected, current_pan, current_tilt, client_ip, client_name

    ws = web.WebSocketResponse(heartbeat=10.0)
    await ws.prepare(request)

    remote_addr = request.remote
    print(f"[SYS] Neue Verbindung von IP: {remote_addr}")

    authenticated = False
    this_session_user = None

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)

                if data.get('type') == 'login':
                    attempt_user = data.get('user', 'Unbekannt')

                    # FEHLER: System belegt
                    if client_connected:
                        print(
                            f"[AUTH] Login-Versuch abgelehnt: System belegt durch '{client_name}' (IP: {remote_addr})")
                        await ws.send_json({"type": "login_fail", "message": "System belegt!"})
                        continue

                    users = load_users()
                    if attempt_user in users and verify_password(users[attempt_user], data.get('pass')):
                        # ERFOLG: Login korrekt
                        authenticated = True
                        client_connected = True
                        client_ip = remote_addr
                        client_name = attempt_user
                        this_session_user = attempt_user
                        write_status()

                        host_header = request.host.split(':')[0]
                        auth_url = f"http://{host_header}:1984/stream.html?src=cam&mode=webrtc&token={Config.CAM_TOKEN}"
                        print(f"[AUTH] User '{client_name}' angemeldet (IP: {remote_addr})")
                        await ws.send_json({"type": "login_success", "user": attempt_user, "stream_url": auth_url})
                    else:
                        # FEHLER: Falsche Daten
                        print(f"[AUTH] FEHLER: Falsches Passwort/User für '{attempt_user}' (IP: {remote_addr})")
                        await asyncio.sleep(1)  # Schutz gegen Brute-Force
                        await ws.send_json({"type": "login_fail", "message": "Login-Daten ungültig"})

                elif authenticated:
                    if 'pan' in data and 'tilt' in data:
                        current_pan = max(0, min(180, float(data['pan'])))
                        current_tilt = max(0, min(180, float(data['tilt'])))
                        if kit:
                            kit.servo[Config.PAN_CHANNEL].angle = current_pan
                            kit.servo[Config.TILT_CHANNEL].angle = current_tilt
                        write_status()

                    elif data.get('type') == 'change_password':
                        users = load_users()
                        if verify_password(users[this_session_user], data.get('old_pass')):
                            users[this_session_user] = hash_password(data.get('new_pass'))
                            if save_users(users):
                                print(f"[SYS] Passwort geändert für User '{this_session_user}'")
                                await ws.send_json({"type": "pw_change_success"})
                        else:
                            await ws.send_json({"type": "pw_change_fail", "message": "Altes Passwort falsch!"})
    finally:
        if authenticated and client_name == this_session_user:
            print(f"[SYS] Logout: User '{client_name}' hat die Verbindung getrennt.")
            client_connected = False
            client_name = "Niemand"
            client_ip = "N/A"
            write_status()
    return ws


async def index(request):
    return web.FileResponse('./index.html')


app = web.Application()
app.router.add_get('/', index)
app.router.add_get('/ws', websocket_handler)

if __name__ == '__main__':
    local_ips = get_local_ips()
    print("-" * 50)
    print(f"ROBOTER-SERVER GESTARTET (Port {Config.PORT})")
    if local_ips:
        print("Erreichbar unter:")
        for ip in local_ips: print(f"  > http://{ip}:{Config.PORT}")
    else:
        print(f"  > http://localhost:{Config.PORT}")
    print("-" * 50)

    try:
        web.run_app(app, host=Config.HOST, port=Config.PORT, print=None)
    finally:
        if kit:
            kit.servo[Config.PAN_CHANNEL].angle = 90
            kit.servo[Config.TILT_CHANNEL].angle = 90