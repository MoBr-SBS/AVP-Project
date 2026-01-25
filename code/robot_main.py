import asyncio
import sys
import ssl
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
client_role = "none"  # --- NEU: Rolle global speichern
client_ip = "N/A"


# --- 3. HELFER-FUNKTIONEN (Sicherheit & IP) ---

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password.strip()).encode()).hexdigest()
    return f"{salt}${hashed}"


def verify_password(stored_password, provided_password):
    try:
        if not stored_password or '$' not in stored_password:
            return False
        salt, hashed = stored_password.split('$')
        new_hash = hash_password(provided_password, salt).split('$')[1]
        return new_hash == hashed
    except Exception as e:
        print(f"[DEBUG] Fehler in verify_password: {e}")
        return False


def load_users():
    try:
        with open(cfg['paths']['user_db'], 'r') as f:
            users = json.load(f)

        # --- AUTO-FIX LOGIK ---
        changed = False
        for username, data in users.items():
            # Falls der Eintrag noch ein einfacher String (altes Format) ist:
            if isinstance(data, str):
                print(f"[SYS] Konvertiere User '{username}' in neues Format...")
                users[username] = {
                    "password": data,
                    "role": "admin" if username == "admin" else "user"
                }
                changed = True

        if changed:
            save_users(users)
        return users
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


# --- 4. SERVO LOGIK ---

def set_servo_angle(axis, angle):
    s_cfg = cfg['hardware'][axis]
    angle = max(s_cfg['min_angle'], min(s_cfg['max_angle'], angle))
    actual_angle = (180 - angle) if s_cfg['reverse'] else angle

    if kit:
        try:
            kit.servo[s_cfg['channel']].angle = actual_angle
        except Exception as e:
            print(f"[HW] Servo Fehler {axis}: {e}")
    return angle


# --- 4. STATUS UPDATES ---
async def write_status(ws=None):
    # Status-Paket schnüren
    status = {
        "type": "status",  # Wichtig, damit JS es erkennt!
        "pan": current_pan,
        "tilt": current_tilt,
        "user": client_name,
        "role": client_role,
        "connected": client_connected
    }

    # 1. In SHM Datei schreiben (für OLED Service)
    try:
        with open(cfg['paths']['shm_file'], 'w') as f:
            json.dump(status, f)
    except Exception:
        pass

    # 2. An User via Websocket senden (nur wenn ws übergeben wurde)
    if ws is not None and not ws.closed:
        try:
            await ws.send_json(status)
        except Exception as e:
            print(f"[NET] Fehler beim Senden des Status: {e}")


# --- 5. WEBSOCKET HANDLER ---

async def websocket_handler(request):
    global current_pan, current_tilt, client_connected, client_name, client_ip, client_role

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

                    if u in users:
                        user_entry = users[u]
                        # Passwort-Check gegen das 'password' Feld im Objekt
                        if verify_password(user_entry.get('password', ''), p):
                            authenticated = True
                            this_session_user = u

                            # Rolle auslesen (Default: user)
                            role = user_entry.get('role', 'user')

                            client_connected = True
                            client_name = u
                            client_role = role

                            print(f"[AUTH] LOGIN ERFOLGREICH: User '{u}' [{role}] | {client_ip}")

                            server_ip = request.host.split(':')[0]
                            stream_name = "cam"
                            target_url = f"https://{server_ip}:1985/stream.html?src={stream_name}"

                            await ws.send_json({
                                "type": "login_success",
                                "user": u,
                                "role": role,  # --- NEU: Rolle an Client senden
                                "stream_url": target_url
                            })
                            await write_status()
                        else:
                            await ws.send_json({"type": "login_fail", "message": "Passwort falsch"})
                    else:
                        await ws.send_json({"type": "login_fail", "message": "Nutzer unbekannt"})

                #STEUERUNG
                elif authenticated and msg_type == 'move':
                    new_pan = data.get('pan', current_pan)
                    new_tilt = data.get('tilt', current_tilt)

                    current_pan = max(cfg['hardware']['pan']['min_angle'],
                                      min(cfg['hardware']['pan']['max_angle'], new_pan))

                    current_tilt = max(cfg['hardware']['tilt']['min_angle'],
                                       min(cfg['hardware']['tilt']['max_angle'], new_tilt))

                    # 3. Hardware-Ansteuerung (nur wenn Hardware vorhanden ist)
                    if kit:
                        # PAN: Reverse-Logik anwenden
                        pan_target = current_pan
                        if cfg['hardware']['pan'].get('reverse'):
                            pan_target = 180 - pan_target

                        # TILT: Reverse-Logik anwenden
                        tilt_target = current_tilt
                        if cfg['hardware']['tilt'].get('reverse'):
                            tilt_target = 180 - tilt_target

                        # Befehle an die in der Config hinterlegten Kanäle senden
                        try:
                            kit.servo[cfg['hardware']['pan']['channel']].angle = pan_target
                            kit.servo[cfg['hardware']['tilt']['channel']].angle = tilt_target
                        except Exception as e:
                            print(f"[HW] Fehler bei Servo-Ansteuerung: {e}")

                    # 4. Status aktualisieren (für OLED und Websocket-Feedback)
                    await write_status(ws)

                # PASSWORT ÄNDERN
                elif authenticated and msg_type == 'change_password':
                    old_p = data.get('old')
                    new_p = data.get('new')

                    users_db = load_users()
                    user_data = users_db.get(client_name)

                    # Prüfen ob altes PW stimmt
                    if user_data and verify_password(user_data['password'], old_p):
                        users_db[client_name]['password'] = hash_password(new_p)
                        if save_users(users_db):
                            await ws.send_json(
                                {"type": "admin_action_success", "message": "Dein Passwort wurde geändert!"})
                    else:
                        await ws.send_json({"type": "error", "message": "Altes Passwort ist falsch!"})

                elif authenticated and msg_type == 'get_users':
                    if client_role == 'admin':
                        users_db = load_users()
                        user_list = []
                        # Wir senden nur Namen und Rollen, KEINE Passwörter!
                        for u_name, u_data in users_db.items():
                            user_list.append({
                                "name": u_name,
                                "role": u_data.get("role", "user")
                            })
                        await ws.send_json({"type": "user_list", "users": user_list})

                # ADMIN: USER UPDATEN (PASSWORT RESET & ROLLE)
                elif authenticated and msg_type == 'admin_update_user':
                    if client_role == 'admin':
                        target_user = data.get('target_user')
                        new_pass = data.get('new_pass')
                        is_admin = data.get('is_admin')

                        users_db = load_users()  # Aktuellen Stand laden

                        if target_user in users_db:
                            # Rolle setzen
                            users_db[target_user]['role'] = 'admin' if is_admin else 'user'

                            # Passwort nur ändern, wenn ein neues eingegeben wurde
                            if new_pass and len(str(new_pass).strip()) > 0:
                                users_db[target_user]['password'] = hash_password(str(new_pass).strip())
                                print(f"[ADMIN] PW-Reset für {target_user}")

                            # In Datei schreiben
                            if save_users(users_db):
                                await ws.send_json({
                                    "type": "admin_action_success",
                                    "message": f"Änderungen für {target_user} gespeichert!"
                                })
                                # WICHTIG: Sende die aktualisierte Liste sofort zurück an den Admin
                                new_list = [{"name": n, "role": d.get("role", "user")} for n, d in users_db.items()]
                                await ws.send_json({"type": "user_list", "users": new_list})
                        else:
                            await ws.send_json({"type": "error", "message": "User nicht gefunden"})

                # ADMIN: SYSTEM STEUERUNG (Restart, Reboot, Shutdown)
                elif authenticated and msg_type == 'system_control':
                    if client_role == 'admin':
                        command = data.get('command')
                        print(f"[ADMIN] Führt System-Befehl aus: {command}")

                        if command == 'restart_code':
                            await ws.send_json({"type": "admin_action_success", "message": "Server startet neu..."})
                            # Startet das aktuelle Python-Skript neu
                            os.execv(sys.executable, ['python3'] + sys.argv)

                        elif command == 'reboot':
                            await ws.send_json(
                                {"type": "admin_action_success", "message": "Raspberry Pi startet neu..."})
                            os.system('sudo reboot')

                        elif command == 'shutdown':
                            await ws.send_json(
                                {"type": "admin_action_success", "message": "Raspberry Pi fährt herunter..."})
                            os.system('sudo shutdown -h now')

                #CREATE NEW USER
                elif authenticated and msg_type == 'admin_create_user':
                    if client_role == 'admin':
                        new_u = str(data.get('username', '')).strip()
                        new_p = str(data.get('password', '')).strip()
                        is_admin = data.get('is_admin')

                        users_db = load_users()

                        if not new_u or not new_p:
                            await ws.send_json({"type": "error", "message": "Bitte Name und Passwort angeben!"})
                        elif new_u in users_db:
                            await ws.send_json({"type": "error", "message": f"User '{new_u}' existiert bereits!"})
                        else:
                            # User anlegen
                            users_db[new_u] = {
                                "password": hash_password(new_p),
                                "role": "admin" if is_admin else "user"
                            }

                            if save_users(users_db):
                                await ws.send_json({"type": "admin_action_success",
                                                    "message": f"User '{new_u}' erfolgreich angelegt."})
                                # Liste für den Admin sofort aktualisieren
                                new_list = [{"name": n, "role": d.get("role", "user")} for n, d in users_db.items()]
                                await ws.send_json({"type": "user_list", "users": new_list})

                #DELETE USER
                elif authenticated and msg_type == 'admin_delete_user':
                    if client_role == 'admin':
                        target = data.get('target_user')

                        # Einzige Sperre: Man kann sich nicht selbst löschen
                        if target == client_name:
                            await ws.send_json({"type": "error",
                                                "message": "Selbstmord-Kommando abgelehnt: Du kannst dich nicht selbst löschen!"})
                        else:
                            users_db = load_users()
                            if target in users_db:
                                del users_db[target]
                                if save_users(users_db):
                                    await ws.send_json(
                                        {"type": "admin_action_success", "message": f"User '{target}' wurde gelöscht."})
                                    print(f"[ADMIN] User '{target}' erfolgreich gelöscht!")
                                    # Liste aktualisieren
                                    new_list = [{"name": n, "role": d.get("role", "user")} for n, d in users_db.items()]
                                    await ws.send_json({"type": "user_list", "users": new_list})
                            else:
                                await ws.send_json({"type": "error", "message": "User nicht gefunden."})


                # KONFIGURATION ÜBERGEBEN/AUSLESEN (NUR ADMIN)
                elif authenticated and msg_type == 'get_config':
                    if client_role == 'admin':
                        await ws.send_json({
                            "type": "config_data",
                            "config": cfg
                        })

                    # KONFIGURATION SPEICHERN (NUR ADMIN)
                elif authenticated and msg_type == 'update_config':
                    if client_role == 'admin':
                        new_cfg_data = data.get('config')
                        if new_cfg_data:
                            # Wir aktualisieren das globale cfg-Objekt
                            cfg.update(new_cfg_data)
                            # In Datei speichern
                            with open('config.json', 'w') as f:
                                json.dump(cfg, f, indent=4)

                            print(f"[ADMIN] Konfiguration durch {client_name} aktualisiert.")
                            await ws.send_json({"type": "config_update_success"})
                    else:
                        await ws.send_json({"type": "error", "message": "Nicht autorisiert"})

    finally:
        if authenticated:
            print(f"[SYS] Logout: User '{client_name}' ({client_ip}) hat getrennt.")
            client_connected = False
            client_name = "Niemand"
            client_role = "none"
            client_ip = "N/A"

            await write_status()

    return ws


# --- 6. SERVER START ---

async def index(request):
    return web.FileResponse('./templates/index.html')


app = web.Application()
app.router.add_static('/static/', path='static', name='static')
app.router.add_get('/', index)
app.router.add_get('/ws', websocket_handler)

if __name__ == '__main__':
    host = cfg['network']['host']
    port = cfg['network']['port']
    local_ips = get_local_ips()

    print("-" * 50)
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

    cert_file = './certs/cert.pem'
    key_file = './certs/key.pem'

    try:
        ssl_context.load_cert_chain(cert_file, key_file)
        print(f"[SEC] SSL Zertifikate geladen ({cert_file}).")
        print(f"ROBOTER-SERVER GESTARTET (HTTPS) auf Port {port}")
    except FileNotFoundError:
        print("[SEC] FEHLER: Zertifikate nicht gefunden! Starte ohne HTTPS.")
        ssl_context = None
        print(f"ROBOTER-SERVER GESTARTET (HTTP - UNSICHER) auf Port {port}")

    for ip in local_ips:
        protocol = "https" if ssl_context else "http"
        print(f" -> {protocol}://{ip}:{port}")
    print("-" * 50)

    web.run_app(app, host=host, port=port, ssl_context=ssl_context)