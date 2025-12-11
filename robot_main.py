import asyncio
import json
import board
import busio
import hashlib
import secrets
import os
from aiohttp import web
from adafruit_servokit import ServoKit


# --- KONFIGURATION ---
class Config:
    """
    Zentrale Konfiguration für Hardware-Pins, Pfade und Sicherheitstokens.
    Trennt Einstellungen von der Programmlogik.
    """
    # PCA9685 Servo-Kanäle
    PAN_CHANNEL = 10
    TILT_CHANNEL = 11

    # Inter-Process Communication (IPC) via RAM-Disk
    # /dev/shm ist ein temporäres Dateisystem im Arbeitsspeicher (extrem schnell, keine SD-Abnutzung)
    SHM_FILE = "/dev/shm/robot_status.json"

    # Sicherheitstoken für den WebRTC-Stream (muss mit go2rtc.yaml übereinstimmen)
    CAM_TOKEN = "aB7dE9fG2hJ5kL8mN1pQ"

    HOST = '0.0.0.0'
    PORT = 8080


# --- HARDWARE INITIALISIERUNG ---
try:
    i2c = busio.I2C(board.SCL, board.SDA)
    kit = ServoKit(channels=16, i2c=i2c)
    print("Hardware: Servo-Treiber erfolgreich initialisiert.")
except Exception as e:
    # Fehlerbehandlung: Erlaubt den Start des Webservers auch ohne angeschlossene Hardware (z.B. zum Testen)
    print(f"Hardware-Fehler: Servo-Treiber nicht gefunden ({e}). Simulationsmodus aktiv.")
    kit = None

# Globale Zustandsvariablen
current_pan = 90
current_tilt = 90
client_connected = False
client_ip = "N/A"
client_name = "Niemand"

# Startposition anfahren, falls Hardware verfügbar
if kit:
    kit.servo[Config.PAN_CHANNEL].angle = current_pan
    kit.servo[Config.TILT_CHANNEL].angle = current_tilt


# --- STATUS KOMMUNIKATION (IPC) ---

def write_status():
    """
    Schreibt den aktuellen Roboter-Status in den Shared Memory (/dev/shm).
    Nutzt 'Atomic Writes', um Datenkonsistenz zu gewährleisten.
    """
    global current_pan, current_tilt, client_connected, client_ip, client_name

    data = {
        "pan": round(current_pan, 1),
        "tilt": round(current_tilt, 1),
        "connected": client_connected,
        "client_ip": client_ip,
        "client_name": client_name
    }
    try:
        # 1. Schreiben in eine temporäre Datei
        tmp_file = Config.SHM_FILE + ".tmp"
        with open(tmp_file, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())  # Erzwingt das Schreiben in den RAM

        # 2. Atomares Umbenennen: Das Betriebssystem garantiert, dass dieser Schritt unteilbar ist.
        # Das Display-Skript liest dadurch niemals eine halb-geschriebene (korrupte) Datei.
        os.replace(tmp_file, Config.SHM_FILE)
    except Exception as e:
        print(f"IPC-Fehler: Konnte Status nicht schreiben: {e}")


# Initialen Status schreiben
write_status()


# --- AUTHENTIFIZIERUNG ---

def load_users():
    """Lädt die Benutzerdatenbank aus der JSON-Datei."""
    try:
        with open('users.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("Kritischer Fehler: 'users.json' nicht gefunden.")
        return {}


def verify_password(stored_password, provided_password):
    """
    Überprüft das Passwort kryptografisch sicher.
    Verwendet PBKDF2-Hashing mit Salt und zeit-konstanten Vergleich,
    um Timing-Side-Channel-Attacken zu verhindern.
    """
    try:
        salt, stored_hash = stored_password.split('$')

        # Erneutes Hashen des Eingabe-Passworts mit demselben Salt
        new_hash = hashlib.pbkdf2_hmac(
            'sha256',
            provided_password.encode('utf-8'),
            bytes.fromhex(salt),
            100000
        )

        # `secrets.compare_digest` vergleicht Strings in konstanter Zeit,
        # unabhängig davon, wie viele Zeichen übereinstimmen.
        return secrets.compare_digest(new_hash.hex(), stored_hash)
    except Exception as e:
        print(f"Auth-Fehler: {e}")
        return False


# --- WEBSOCKET LOGIK ---
async def websocket_handler(request):
    """Verwaltet die Echtzeit-Verbindung für Login und Steuerung."""
    global client_connected, current_pan, current_tilt, client_ip, client_name

    ws = web.WebSocketResponse(heartbeat=10.0)
    await ws.prepare(request)

    authenticated = False
    current_user_ip = request.remote
    host = request.host.split(':')[0]

    # Optional: Loggen, dass sich technisch jemand verbunden hat (noch ohne Login)
    # print(f"[NET] Neue WebSocket-Verbindung von {current_user_ip}")

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)

                    # --- Sektion 1: Login ---
                    if 'type' in data and data['type'] == 'login':

                        # 1. Daten extrahieren (noch nichts prüfen)
                        attempt_user = data.get('user', 'Unbekannt')

                        # LOG: Zeige JEDEN Versuch an
                        print(f"[AUTH] Login-Versuch | User: '{attempt_user}' | IP: {current_user_ip}")

                        # 2. Prüfen: Ist schon besetzt?
                        if client_connected:
                            print(f"[AUTH] Abgelehnt: System ist bereits belegt durch '{client_name}'")
                            await ws.send_json({
                                "type": "login_fail",
                                "message": "System ist belegt!"
                            })
                            continue  # Abbruch

                        # 3. Prüfen: Passwort
                        users = load_users()
                        pw = data.get('pass')

                        if attempt_user in users and verify_password(users[attempt_user], pw):
                            # ERFOLG
                            authenticated = True
                            client_connected = True
                            client_ip = current_user_ip
                            client_name = attempt_user

                            write_status()  # Display Update

                            auth_stream_url = f"http://{host}:1984/stream.html?src=cam&mode=webrtc&token={Config.CAM_TOKEN}"

                            print(f"[AUTH] Login erfolgreich! | User: '{client_name}'")

                            await ws.send_json({
                                "type": "login_success",
                                "user": attempt_user,
                                "stream_url": auth_stream_url
                            })
                        else:
                            # FEHLSCHLAG (Falsche Daten)
                            print(f"[AUTH] Login fehlgeschlagen: Falsches Passwort oder User für '{attempt_user}'")
                            await asyncio.sleep(1)  # Brute-Force Bremse
                            await ws.send_json({"type": "login_fail"})

                    # --- Sektion 2: Steuerung ---
                    elif authenticated:
                        if 'pan' in data and 'tilt' in data:
                            pan = float(data['pan'])
                            tilt = float(data['tilt'])

                            pan = max(0, min(180, pan))
                            tilt = max(0, min(180, tilt))

                            current_pan = pan
                            current_tilt = tilt

                            if kit:
                                kit.servo[Config.PAN_CHANNEL].angle = pan
                                kit.servo[Config.TILT_CHANNEL].angle = tilt

                            write_status()

                except Exception as e:
                    print(f"[ERR] Fehler bei Nachrichtenverarbeitung: {e}")

    finally:
        # --- Aufräumen ---
        if authenticated:
            print(f"[SYS] Verbindung getrennt. User '{client_name}' ausgeloggt. System frei.")
            client_connected = False
            client_name = "Niemand"
            client_ip = "N/A"
            write_status()
        else:
            # Wenn jemand ohne Login das Fenster schließt
            # print(f"[NET] WebSocket getrennt (ohne Login) von {current_user_ip}")
            pass

    return ws


# --- MAIN SETUP ---
async def index(request):
    return web.FileResponse('./index.html')


app = web.Application()
app.router.add_get('/', index)
app.router.add_get('/ws', websocket_handler)

if __name__ == '__main__':
    print(f"Starte Roboter-Server auf Port {Config.PORT}...")
    try:
        web.run_app(app, host=Config.HOST, port=Config.PORT)
    finally:
        # Graceful Shutdown: Bringt den Roboter beim Beenden in eine sichere Parkposition
        if kit:
            print("Server gestoppt. Fahre Servos in Parkposition (90/90)...")
            kit.servo[Config.PAN_CHANNEL].angle = 90
            kit.servo[Config.TILT_CHANNEL].angle = 90