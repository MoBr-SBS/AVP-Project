"""Login-Logik: POST /login, POST /logout, Session-Token-Verwaltung.

Hilfsfunktionen (hash_password, load_users, save_users) werden auch von
server/websocket.py importiert.
"""

import hashlib
import json
import os
import secrets
import time

from aiohttp import web

# Absoluter Pfad zu code/ (eine Ebene über diesem Modul)
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Nutzer-Datenbank
# ---------------------------------------------------------------------------

def hash_password(password: str, salt: str = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password.strip()).encode()).hexdigest()
    return f"{salt}${hashed}"


def load_users(cfg: dict) -> dict:
    path = os.path.join(_BASE, cfg["paths"]["user_db"])
    try:
        with open(path, "r") as f:
            users = json.load(f)
        # Kompatibilität mit altem Format (password als plain string)
        changed = False
        for name, data in users.items():
            if isinstance(data, str):
                print(f"[AUTH] Konvertiere Nutzer '{name}' ins neue Format …")
                users[name] = {
                    "password": data,
                    "role": "admin" if name == "admin" else "user",
                }
                changed = True
        if changed:
            save_users(users, cfg)
        return users
    except Exception as e:
        print(f"[AUTH] FEHLER beim Laden der Nutzerdatenbank: {e}")
        return {}


def save_users(users: dict, cfg: dict) -> bool:
    path = os.path.join(_BASE, cfg["paths"]["user_db"])
    try:
        with open(path, "w") as f:
            json.dump(users, f, indent=4)
        return True
    except Exception as e:
        print(f"[AUTH] FEHLER beim Speichern der Nutzerdatenbank: {e}")
        return False


def verify_password(stored: str, provided: str) -> bool:
    try:
        if not stored or "$" not in stored:
            return False
        salt, hashed = stored.split("$", 1)
        return hashlib.sha256((salt + provided.strip()).encode()).hexdigest() == hashed
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Session-Verwaltung
# ---------------------------------------------------------------------------

def create_session(app: web.Application, user: str, role: str) -> str:
    """Legt eine neue Session an und gibt den Token zurück."""
    token = secrets.token_urlsafe(32)
    app["sessions"][token] = {"user": user, "role": role, "created_at": time.time()}
    return token


def get_session(app: web.Application, token: str) -> dict | None:
    """Gibt die Session-Daten zurück oder None wenn der Token ungültig ist."""
    return app["sessions"].get(token)


def remove_session(app: web.Application, token: str) -> dict | None:
    """Entfernt eine Session und gibt ihre Daten zurück (oder None)."""
    return app["sessions"].pop(token, None)


# ---------------------------------------------------------------------------
# HTTP-Handler
# ---------------------------------------------------------------------------

async def login_handler(request: web.Request) -> web.Response:
    """POST /login  { "user": "...", "pass": "..." }  →  { "token": "...", "user": "...", "role": "..." }"""
    cfg = request.app["config"]
    auth_required = cfg.get("auth", {}).get("required", True)

    try:
        data = await request.json()
    except Exception:
        data = {}

    username = str(data.get("user", "")).strip()
    password = str(data.get("pass", "")).strip()

    # Guest bypass: only when auth is disabled AND no credentials provided
    if not auth_required and not username:
        token = create_session(request.app, "Guest", "user")
        print(f"[AUTH] Guest login (auth disabled) from {request.remote}")
        return web.json_response({"token": token, "user": "Guest", "role": "user"})

    if not username or not password:
        return web.json_response({"error": "Username and password required"}, status=400)

    users = load_users(cfg)

    if username not in users or not verify_password(users[username].get("password", ""), password):
        print(f"[AUTH] Login failed for '{username}' from {request.remote}")
        return web.json_response({"error": "Invalid username or password"}, status=401)

    role = users[username].get("role", "user")
    token = create_session(request.app, username, role)
    print(f"[AUTH] Login successful: '{username}' [{role}] from {request.remote}")
    return web.json_response({"token": token, "user": username, "role": role})


async def logout_handler(request: web.Request) -> web.Response:
    """POST /logout  { "token": "..." }"""
    try:
        data = await request.json()
        token = data.get("token", "")
    except Exception:
        return web.json_response({"error": "Ungültiges JSON"}, status=400)

    session = remove_session(request.app, token)
    if session:
        print(f"[AUTH] Logout: '{session['user']}' von {request.remote}")
    return web.json_response({"ok": True})
