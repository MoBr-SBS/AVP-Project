"""Telepräsenz-Roboter – Haupteinstiegspunkt."""

import json
import os
import socket
import ssl

from aiohttp import web

from hardware.oled import start_oled, stop_oled
from server.auth import login_handler, logout_handler
from server.stream import start_capture, stop_capture, stream_handler
from server.websocket import start_heartbeat, stop_heartbeat, websocket_handler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config() -> dict:
    path = os.path.join(BASE_DIR, "config.json")
    try:
        with open(path, "r") as f:
            cfg = json.load(f)
        print("[KONFIG] config.json geladen.")
        return cfg
    except FileNotFoundError:
        print("[FEHLER] config.json nicht gefunden!")
        raise SystemExit(1)
    except json.JSONDecodeError as e:
        print(f"[FEHLER] config.json ungültig: {e}")
        raise SystemExit(1)


def get_local_ips() -> list:
    ips = []
    try:
        for interface in socket.getaddrinfo(socket.gethostname(), None):
            ip = interface[4][0]
            if "." in ip and not ip.startswith("127."):
                if ip not in ips:
                    ips.append(ip)
    except Exception:
        pass
    return ips


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(os.path.join(BASE_DIR, "templates", "index.html"))


def build_app(cfg: dict) -> web.Application:
    app = web.Application()
    app["config"] = cfg
    app["sessions"] = {}  # token → {"user", "role", "created_at"}  (befüllt von auth.py)
    app["state"] = {      # Servo-Position + aktiver Nutzer (geteilt mit OLED via SHM)
        "pan": 90, "tilt": 90,
        "connected": False, "user": "Niemand", "role": "none", "client_ip": "N/A",
    }
    app["controller"] = {"user": None, "token": None}  # wer gerade steuert
    app["ws_clients"] = []                              # alle offenen WS-Verbindungen

    static_path = os.path.join(BASE_DIR, "static")
    app.router.add_get("/", index)
    app.router.add_get("/stream", stream_handler)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_post("/login", login_handler)
    app.router.add_post("/logout", logout_handler)
    app.router.add_static("/static/", path=static_path, name="static")

    app.on_startup.append(start_capture)
    app.on_startup.append(start_heartbeat)
    app.on_startup.append(start_oled)
    app.on_cleanup.append(stop_capture)
    app.on_cleanup.append(stop_heartbeat)
    app.on_cleanup.append(stop_oled)

    return app


def load_ssl() -> ssl.SSLContext | None:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    cert = os.path.join(BASE_DIR, "certs", "cert.pem")
    key = os.path.join(BASE_DIR, "certs", "key.pem")
    try:
        ctx.load_cert_chain(cert, key)
        print(f"[SEC] SSL-Zertifikate geladen ({cert}).")
        return ctx
    except FileNotFoundError:
        print("[SEC] WARNUNG: Zertifikate nicht gefunden – starte ohne HTTPS.")
        return None


if __name__ == "__main__":
    cfg = load_config()

    host = cfg["network"]["host"]
    port = cfg["network"]["port"]
    auth_required = cfg.get("auth", {}).get("required", True)

    app = build_app(cfg)
    ssl_ctx = load_ssl()

    protocol = "https" if ssl_ctx else "http"
    local_ips = get_local_ips()

    print("-" * 50)
    print(f"[SYS] Roboter-Server gestartet ({protocol.upper()}) – Port {port}")
    for ip in local_ips:
        print(f"  -> {protocol}://{ip}:{port}")
    print(f"[AUTH] Authentifizierung: {'erforderlich' if auth_required else 'deaktiviert (Gast-Modus)'}")
    print("-" * 50)

    web.run_app(app, host=host, port=port, ssl_context=ssl_ctx)
