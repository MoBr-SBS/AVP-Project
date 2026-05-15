"""OLED-Anzeige (SH1106, 128x64) und Drehgeber-Eingabe als asyncio-Task.

Portiert aus oled-menu.py. Kernänderungen:
- Kein SystemMonitor-Thread: Daten kommen direkt aus app["state"]
- gpiozero-Callbacks → loop.call_soon_threadsafe (threadsicher ohne Queue)
- Rendering und System-Stats laufen in run_in_executor (blockiert Event-Loop nicht)
"""

import asyncio
import subprocess
import textwrap
from pathlib import Path

from aiohttp import web

_BASE = Path(__file__).parent.parent          # → code/
_ICON_DIR = _BASE / "menu-icons"
_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_FPS = 20

_oled_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

class _Resources:
    def __init__(self):
        from PIL import ImageFont
        self._cache: dict = {}
        try:
            self.font = ImageFont.truetype(_FONT_PATH, 12)
        except IOError:
            self.font = ImageFont.load_default()

    def icon(self, filename: str, size: tuple = (16, 16)):
        key = (filename, size)
        if key not in self._cache:
            from PIL import Image
            path = _ICON_DIR / filename
            try:
                img = Image.open(path).convert("1").resize(size) if path.exists() else Image.new("1", size)
            except Exception:
                img = Image.new("1", size)
            self._cache[key] = img
        return self._cache[key]


# ---------------------------------------------------------------------------
# Menu Controller
# ---------------------------------------------------------------------------

class _Controller:
    def __init__(self, device, res: _Resources, loop: asyncio.AbstractEventLoop):
        self._device = device
        self._res = res
        self._loop = loop
        self.view = "dashboard"
        self.dashboard_page = 0
        self.menu_index = 0
        self._menu_top = 0
        self.info_scroll = 0
        self._info_lines: list = []
        self.data: dict = {}   # Snapshot: app["state"] + system stats

        self._menu_items = [
            {"title": "Zurück",   "icon": "back.png",     "fn": self._go_dashboard},
            {"title": "Info",     "icon": "info.png",     "fn": self._show_info},
            {"title": "Reboot",   "icon": "reboot.png",   "cmd": "sudo reboot"},
            {"title": "Shutdown", "icon": "shutdown.png", "cmd": "sudo shutdown now"},
        ]

    # --- Eingabe-Handler (werden aus gpiozero-Thread via call_soon_threadsafe aufgerufen) ---

    def handle_rotate(self, direction: int):
        if self.view == "dashboard":
            self.dashboard_page = (self.dashboard_page + direction) % 3
        elif self.view == "info":
            max_s = max(0, len(self._info_lines) - 3)
            self.info_scroll = max(0, min(self.info_scroll + direction, max_s))
        elif self.view == "menu":
            new = self.menu_index + direction
            if 0 <= new < len(self._menu_items):
                self.menu_index = new
                if self.menu_index >= self._menu_top + 3:
                    self._menu_top += 1
                elif self.menu_index < self._menu_top:
                    self._menu_top -= 1

    def handle_click(self):
        if self.view != "menu":
            self.view = "menu"
            return
        item = self._menu_items[self.menu_index]
        if "fn" in item:
            item["fn"]()
        elif "cmd" in item:
            # System-Befehl asynchron ausführen (reboot/shutdown beendet den Pi sowieso)
            asyncio.run_coroutine_threadsafe(self._run_cmd(item["cmd"]), self._loop)

    async def _run_cmd(self, cmd: str):
        await asyncio.create_subprocess_shell(cmd)

    def _go_dashboard(self):
        self.view = "dashboard"

    def _show_info(self):
        try:
            txt = (_ICON_DIR / "menu-info.txt").read_text(encoding="utf-8")
        except Exception:
            txt = "Info-Datei fehlt."
        self._info_lines = textwrap.wrap(txt, width=18)
        self.info_scroll = 0
        self.view = "info"

    # --- Rendering (synchron, läuft in run_in_executor) ---

    def render(self):
        from luma.core.render import canvas
        with canvas(self._device) as draw:
            if self.view == "dashboard":
                self._draw_dashboard(draw)
            elif self.view == "menu":
                self._draw_menu(draw)
            elif self.view == "info":
                self._draw_info(draw)

    def _draw_dashboard(self, draw):
        f = self._res.font
        d = self.data
        if self.dashboard_page == 0:
            draw.text((10, 0), "VERBUNDEN" if d.get("connected") else "WARTEN...", font=f, fill="white")
            draw.line((0, 14, 128, 14), fill="white")
            draw.bitmap((2, 20), self._res.icon("user.png"), fill="white")
            draw.text((24, 20), str(d.get("user", "-")), font=f, fill="white")
            draw.bitmap((2, 40), self._res.icon("network.png"), fill="white")
            draw.text((24, 40), str(d.get("client_ip", "-")), font=f, fill="white")
        elif self.dashboard_page == 1:
            rows = [
                ("temp.png",    f"CPU: {d.get('cpu_temp', 'N/A')}"),
                ("online.png" if d.get("server_online") else "offline.png", "Server-Status"),
                ("network.png", d.get("ip", "N/A")),
            ]
            for row_idx, (icon, text) in enumerate(rows):
                y = row_idx * 20
                draw.bitmap((2, y), self._res.icon(icon), fill="white")
                draw.text((24, y), text, font=f, fill="white")
        elif self.dashboard_page == 2:
            draw.bitmap((0, 0),  self._res.icon("servo-tilt.png", (32, 32)), fill="white")
            draw.text((36, 10), f"Tilt: {float(d.get('tilt', 0)):.1f}°", font=f, fill="white")
            draw.bitmap((0, 32), self._res.icon("servo-pan.png", (32, 32)), fill="white")
            draw.text((36, 42), f"Pan:  {float(d.get('pan', 0)):.1f}°",  font=f, fill="white")

    def _draw_menu(self, draw):
        for i in range(self._menu_top, min(self._menu_top + 3, len(self._menu_items))):
            y = (i - self._menu_top) * 20
            sel = (i == self.menu_index)
            fg = "black" if sel else "white"
            if sel:
                draw.rectangle((0, y, 120, y + 20), fill="white")
            draw.bitmap((2, y + 2), self._res.icon(self._menu_items[i]["icon"]), fill=fg)
            draw.text((24, y + 2), self._menu_items[i]["title"], font=self._res.font, fill=fg)

    def _draw_info(self, draw):
        for i, line in enumerate(self._info_lines[self.info_scroll:self.info_scroll + 4]):
            draw.text((2, i * 16), line, font=self._res.font, fill="white")


# ---------------------------------------------------------------------------
# System-Stats (blockierend → run_in_executor)
# ---------------------------------------------------------------------------

def _fetch_system_stats() -> dict:
    stats: dict = {}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            stats["cpu_temp"] = f"{float(f.read()) / 1000:.1f}°C"
    except Exception:
        stats["cpu_temp"] = "N/A"
    try:
        ip = subprocess.check_output(
            "hostname -I | cut -d' ' -f1", shell=True, timeout=2
        ).decode().strip()
        stats["ip"] = ip or "N/A"
    except Exception:
        stats["ip"] = "N/A"
    return stats


# ---------------------------------------------------------------------------
# Haupt-Task
# ---------------------------------------------------------------------------

async def _oled_loop(app: web.Application):
    cfg = app["config"]["oled"]
    loop = asyncio.get_event_loop()

    try:
        from gpiozero import Button, RotaryEncoder
        from luma.core.interface.serial import i2c as luma_i2c
        from luma.oled.device import sh1106

        serial = luma_i2c(port=1, address=int(cfg["address"], 16))
        device = sh1106(serial, width=128, height=64)
        encoder = RotaryEncoder(cfg["pin_clk"], cfg["pin_dt"], max_steps=1)
        button = Button(cfg["pin_sw"], pull_up=True, bounce_time=cfg["bounce_time"])
        print(f"[OLED] Hardware initialisiert (I2C {cfg['address']}).")
    except Exception as e:
        print(f"[OLED] FEHLER: Hardware nicht gefunden ({e}). OLED-Task beendet.")
        return

    res = _Resources()
    ctrl = _Controller(device, res, loop)

    # gpiozero läuft in eigenem Thread → call_soon_threadsafe überbrückt die Grenze
    encoder.when_rotated_clockwise = lambda: loop.call_soon_threadsafe(ctrl.handle_rotate, 1)
    encoder.when_rotated_counter_clockwise = lambda: loop.call_soon_threadsafe(ctrl.handle_rotate, -1)
    button.when_pressed = lambda: loop.call_soon_threadsafe(ctrl.handle_click)

    # System-Stats sofort einmal holen, dann alle 5 s (= 100 Frames bei 20 FPS)
    stats = await loop.run_in_executor(None, _fetch_system_stats)
    frame = 0

    print("[OLED] Render-Loop gestartet.")
    try:
        while True:
            if frame == 0:
                stats = await loop.run_in_executor(None, _fetch_system_stats)
            frame = (frame + 1) % 100

            # Snapshot zusammenstellen (atomare Dict-Zuweisung → GIL schützt render())
            ctrl.data = {**app["state"], **stats, "server_online": True}

            await loop.run_in_executor(None, ctrl.render)
            await asyncio.sleep(1.0 / _FPS)

    except asyncio.CancelledError:
        pass
    finally:
        try:
            device.cleanup()
        except Exception:
            pass
        print("[OLED] Render-Loop beendet.")


async def start_oled(app: web.Application):
    global _oled_task
    _oled_task = asyncio.create_task(_oled_loop(app))
    print("[OLED] Task gestartet.")


async def stop_oled(app: web.Application):
    global _oled_task
    if _oled_task and not _oled_task.done():
        _oled_task.cancel()
        try:
            await _oled_task
        except asyncio.CancelledError:
            pass
    print("[OLED] Task gestoppt.")
