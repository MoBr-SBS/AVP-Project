"""WebSocket-Handler: Servo-Steuerung, User-Management, System-Kontrolle.

Verbindungsaufbau: wss://<host>/ws?token=<session_token>
Rollen: viewer (nur lesen), user (Servo-Steuerung), admin (alles)
"""

import asyncio
import json
import os
import sys

from aiohttp import web

from server.auth import (
    get_session,
    hash_password,
    load_users,
    save_users,
    verify_password,
)

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Servo-Kit – lazy, damit der Server auch ohne Hardware startet
_kit = None
_kit_ready = False
_heartbeat_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------

def _init_kit():
    global _kit, _kit_ready
    if _kit_ready:
        return _kit
    _kit_ready = True
    try:
        import board
        import busio
        from adafruit_servokit import ServoKit
        _kit = ServoKit(channels=16, i2c=busio.I2C(board.SCL, board.SDA))
        print("[HW] Servo-Treiber erfolgreich initialisiert.")
    except Exception as e:
        print(f"[HW] FEHLER: Servo-Treiber nicht gefunden ({e}). Simulationsmodus aktiv.")
    return _kit


def _move_servo(cfg: dict, axis: str, angle: float) -> float:
    hw = cfg["hardware"][axis]
    angle = max(hw["min_angle"], min(hw["max_angle"], float(angle)))
    kit = _init_kit()
    if kit:
        actual = (180 - angle) if hw.get("reverse") else angle
        try:
            kit.servo[hw["channel"]].angle = actual
        except Exception as e:
            print(f"[HW] Servo-Fehler {axis}: {e}")
    return angle


# ---------------------------------------------------------------------------
# SHM-Status (wird auch vom OLED gelesen)
# ---------------------------------------------------------------------------

def _write_shm_blocking(path: str, data: dict):
    with open(path, "w") as f:
        json.dump(data, f)


async def write_shm(app: web.Application) -> dict:
    """Schreibt app['state'] in die Shared-Memory-Datei und gibt das Dict zurück."""
    s = app["state"]
    payload = {
        "type": "status",
        "pan": s["pan"],
        "tilt": s["tilt"],
        "user": s["user"],
        "role": s["role"],
        "connected": s["connected"],
        "client_ip": s["client_ip"],
    }
    shm = app["config"]["paths"]["shm_file"]
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write_shm_blocking, shm, payload)
    except Exception:
        pass
    return payload


# ---------------------------------------------------------------------------
# Heartbeat (hält das OLED-"Server online"-Flag am Leben)
# ---------------------------------------------------------------------------

async def _heartbeat_loop(app: web.Application):
    while True:
        await write_shm(app)
        await asyncio.sleep(2)


async def start_heartbeat(app: web.Application):
    global _heartbeat_task
    _heartbeat_task = asyncio.create_task(_heartbeat_loop(app))
    print("[WS] Heartbeat-Task gestartet.")


async def stop_heartbeat(app: web.Application):
    global _heartbeat_task
    if _heartbeat_task and not _heartbeat_task.done():
        _heartbeat_task.cancel()
        try:
            await _heartbeat_task
        except asyncio.CancelledError:
            pass
    print("[WS] Heartbeat-Task gestoppt.")


# ---------------------------------------------------------------------------
# Nachrichten-Handler (je ein async def pro Typ, klein und testbar)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Control-Management
# ---------------------------------------------------------------------------

async def _broadcast_control(app: web.Application):
    """Sendet den aktuellen Control-State an alle verbundenen Clients."""
    ctrl = app["controller"]
    for client in list(app.get("ws_clients", [])):
        try:
            await client["ws"].send_json({
                "type": "control_state",
                "controller": ctrl["user"],
                "you_have_control": ctrl["token"] == client["token"],
            })
        except Exception:
            pass


async def _on_claim_control(app: web.Application, user: str, token: str):
    ctrl = app["controller"]
    if ctrl["token"] is not None:
        return  # jemand hat bereits die Kontrolle, ignorieren
    ctrl["user"] = user
    ctrl["token"] = token
    print(f"[CTRL] '{user}' hat die Steuerung übernommen.")
    await _broadcast_control(app)


async def _on_release_control(app: web.Application, token: str):
    ctrl = app["controller"]
    if ctrl["token"] != token:
        return  # nicht der aktuelle Controller
    print(f"[CTRL] '{ctrl['user']}' hat die Steuerung freigegeben.")
    ctrl["user"] = None
    ctrl["token"] = None
    await _broadcast_control(app)


async def _on_force_control(app: web.Application, user: str, token: str):
    ctrl = app["controller"]
    prev = ctrl["user"]
    ctrl["user"] = user
    ctrl["token"] = token
    print(f"[CTRL] Admin '{user}' hat die Steuerung von '{prev}' übernommen.")
    await _broadcast_control(app)


async def _on_move(ws: web.WebSocketResponse, app: web.Application, data: dict, token: str):
    if app["controller"]["token"] != token:
        return  # nur der aktuelle Controller darf steuern
    cfg = app["config"]
    s = app["state"]
    s["pan"] = _move_servo(cfg, "pan", data.get("pan", s["pan"]))
    s["tilt"] = _move_servo(cfg, "tilt", data.get("tilt", s["tilt"]))
    await ws.send_json(await write_shm(app))


async def _on_change_password(ws: web.WebSocketResponse, app: web.Application,
                               data: dict, user: str):
    users = load_users(app["config"])
    stored = users.get(user, {}).get("password", "")
    if not verify_password(stored, data.get("old", "")):
        await ws.send_json({"type": "error", "message": "Altes Passwort ist falsch!"})
        return
    users[user]["password"] = hash_password(data.get("new", ""))
    if save_users(users, app["config"]):
        await ws.send_json({"type": "admin_action_success", "message": "Passwort geändert."})


async def _on_get_users(ws: web.WebSocketResponse, app: web.Application):
    users = load_users(app["config"])
    await ws.send_json({
        "type": "user_list",
        "users": [{"name": n, "role": d.get("role", "user")} for n, d in users.items()],
    })


async def _on_create_user(ws: web.WebSocketResponse, app: web.Application, data: dict):
    name = str(data.get("username", "")).strip()
    pw = str(data.get("password", "")).strip()
    if not name or not pw:
        await ws.send_json({"type": "error", "message": "Name und Passwort erforderlich."})
        return
    users = load_users(app["config"])
    if name in users:
        await ws.send_json({"type": "error", "message": f"Nutzer '{name}' existiert bereits."})
        return
    users[name] = {"password": hash_password(pw), "role": "admin" if data.get("is_admin") else "user"}
    if save_users(users, app["config"]):
        await ws.send_json({"type": "admin_action_success", "message": f"Nutzer '{name}' angelegt."})
        await _on_get_users(ws, app)


async def _on_update_user(ws: web.WebSocketResponse, app: web.Application, data: dict):
    target = data.get("target_user")
    users = load_users(app["config"])
    if target not in users:
        await ws.send_json({"type": "error", "message": "Nutzer nicht gefunden."})
        return
    users[target]["role"] = "admin" if data.get("is_admin") else "user"
    new_pw = str(data.get("new_pass", "")).strip()
    if new_pw:
        users[target]["password"] = hash_password(new_pw)
        print(f"[ADMIN] Passwort-Reset für '{target}'")
    if save_users(users, app["config"]):
        await ws.send_json({"type": "admin_action_success", "message": f"Änderungen für '{target}' gespeichert."})
        await _on_get_users(ws, app)


async def _on_delete_user(ws: web.WebSocketResponse, app: web.Application,
                           data: dict, current_user: str):
    target = data.get("target_user")
    if target == current_user:
        await ws.send_json({"type": "error", "message": "Du kannst dich nicht selbst löschen."})
        return
    users = load_users(app["config"])
    if target not in users:
        await ws.send_json({"type": "error", "message": "Nutzer nicht gefunden."})
        return
    del users[target]
    if save_users(users, app["config"]):
        print(f"[ADMIN] Nutzer '{target}' gelöscht.")
        await ws.send_json({"type": "admin_action_success", "message": f"Nutzer '{target}' gelöscht."})
        await _on_get_users(ws, app)


async def _on_system_control(ws: web.WebSocketResponse, data: dict):
    cmd = data.get("command")
    print(f"[ADMIN] System-Befehl: {cmd}")
    if cmd == "restart_code":
        await ws.send_json({"type": "admin_action_success", "message": "Server startet neu …"})
        os.execv(sys.executable, ["python3"] + sys.argv)
    elif cmd == "reboot":
        await ws.send_json({"type": "admin_action_success", "message": "Raspberry Pi startet neu …"})
        os.system("sudo reboot")
    elif cmd == "shutdown":
        await ws.send_json({"type": "admin_action_success", "message": "Raspberry Pi fährt herunter …"})
        os.system("sudo shutdown -h now")


async def _on_get_config(ws: web.WebSocketResponse, app: web.Application):
    await ws.send_json({"type": "config_data", "config": app["config"]})


async def _on_update_config(ws: web.WebSocketResponse, app: web.Application, data: dict):
    new_cfg = data.get("config")
    if not new_cfg:
        return
    app["config"].update(new_cfg)
    cfg_path = os.path.join(_BASE, "config.json")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _write_shm_blocking, cfg_path, app["config"])
    print("[ADMIN] Konfiguration aktualisiert.")
    await ws.send_json({"type": "config_update_success"})


# ---------------------------------------------------------------------------
# Haupt-Handler
# ---------------------------------------------------------------------------

async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    """GET /ws?token=<session_token>"""
    cfg = request.app["config"]
    token = request.rel_url.query.get("token", "")
    session = get_session(request.app, token)

    if cfg.get("auth", {}).get("required", True) and not session:
        raise web.HTTPUnauthorized(reason="Ungültiger oder fehlender Token")

    if not session:
        session = {"user": "Gast", "role": "viewer"}

    user = session["user"]
    role = session["role"]
    client_ip = request.remote

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    app = request.app
    app["state"].update({"connected": True, "user": user, "role": role, "client_ip": client_ip})

    client_entry = {"ws": ws, "user": user, "token": token}
    app["ws_clients"].append(client_entry)

    print(f"[WS] Verbunden: '{user}' [{role}] von {client_ip}")
    await ws.send_json(await write_shm(app))

    # Initialen Control-State senden
    ctrl = app["controller"]
    await ws.send_json({
        "type": "control_state",
        "controller": ctrl["user"],
        "you_have_control": ctrl["token"] == token,
    })

    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                break
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue

            t = data.get("type")

            if t == "move" and role in ("user", "admin"):
                await _on_move(ws, app, data, token)
            elif t == "claim_control" and role in ("user", "admin"):
                await _on_claim_control(app, user, token)
            elif t == "release_control":
                await _on_release_control(app, token)
            elif t == "force_take_control" and role == "admin":
                await _on_force_control(app, user, token)
            elif t == "change_password":
                await _on_change_password(ws, app, data, user)
            elif t == "get_users" and role == "admin":
                await _on_get_users(ws, app)
            elif t == "admin_create_user" and role == "admin":
                await _on_create_user(ws, app, data)
            elif t == "admin_update_user" and role == "admin":
                await _on_update_user(ws, app, data)
            elif t == "admin_delete_user" and role == "admin":
                await _on_delete_user(ws, app, data, user)
            elif t == "system_control" and role == "admin":
                await _on_system_control(ws, data)
            elif t == "get_config" and role == "admin":
                await _on_get_config(ws, app)
            elif t == "update_config" and role == "admin":
                await _on_update_config(ws, app, data)

    finally:
        app["ws_clients"].remove(client_entry)

        # Steuerung freigeben wenn dieser Client der Controller war
        if app["controller"]["token"] == token:
            app["controller"]["user"] = None
            app["controller"]["token"] = None
            print(f"[CTRL] Steuerung freigegeben ('{user}' getrennt).")
            await _broadcast_control(app)

        app["state"].update({"connected": False, "user": "Niemand", "role": "none", "client_ip": "N/A"})
        await write_shm(app)
        print(f"[WS] Getrennt: '{user}' ({client_ip})")

    return ws
