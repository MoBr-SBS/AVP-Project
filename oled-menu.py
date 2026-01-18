import time
import subprocess
import threading
from pathlib import Path
from PIL import Image, ImageFont
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106
from gpiozero import RotaryEncoder, Button
import sys
import textwrap
import json
import os

# --- KONFIGURATION (Dynamisch aus JSON) ---
class Config:
    # Standardwerte (werden durch load_from_json überschrieben)
    PIN_CLK = 17
    PIN_DT = 18
    PIN_SW = 27
    I2C_ADDR = 0x3C
    BOUNCE_TIME = 0.3
    WIDTH = 128
    HEIGHT = 64
    FPS = 30
    POLL_INTERVAL = 0.5
    SHM_FILE = "/dev/shm/robot_status.json"

    # Pfade
    BASE_DIR = Path(__file__).parent
    ICON_DIR = BASE_DIR / "menu-icons"
    FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    @classmethod
    def load_from_json(cls):
        config_path = cls.BASE_DIR / 'config.json'
        try:
            if config_path.exists():
                with open(config_path, 'r') as f:
                    c = json.load(f)
                    # OLED Hardware
                    cls.I2C_ADDR = int(c['oled'].get('address', '0x3C'), 16)
                    cls.PIN_CLK = c['oled'].get('pin_clk', 17)
                    cls.PIN_DT = c['oled'].get('pin_dt', 18)
                    cls.PIN_SW = c['oled'].get('pin_sw', 27)
                    cls.BOUNCE_TIME = c['oled'].get('bounce_time', 0.3)
                    # Pfade
                    cls.SHM_FILE = c['paths'].get('shm_file', cls.SHM_FILE)
                    print(f"[CONFIG] Geladen: I2C={hex(cls.I2C_ADDR)}, SHM={cls.SHM_FILE}")
            else:
                print("[CONFIG] config.json nicht gefunden, nutze Defaults.")
        except Exception as e:
            print(f"[CONFIG] Fehler beim Laden der JSON: {e}")

# Initiales Laden der Config
Config.load_from_json()

# --- RESOURCE MANAGER ---
class ResourceManager:
    def __init__(self):
        self.icons = {}
        self.font = self._load_font()

    def _load_font(self):
        try:
            return ImageFont.truetype(Config.FONT_PATH, 12)
        except IOError:
            return ImageFont.load_default()

    def get_icon(self, filename, size=(16, 16)):
        key = (filename, size)
        if key not in self.icons:
            try:
                path = Config.ICON_DIR / filename
                if not path.exists():
                    img = Image.new('1', size, color=0)
                else:
                    img = Image.open(path).convert("1").resize(size)
                self.icons[key] = img
            except Exception as e:
                self.icons[key] = Image.new('1', size, color=0)
        return self.icons[key]

# --- DATA PROVIDER (Shared Memory) ---
class SystemMonitor(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.running = True
        self.data = {
            "pan": 90, "tilt": 90, "client_connected": False,
            "client_ip": "-", "client_name": "Keiner",
            "server_online": False,
            "cpu_temp": "N/A",
            "ip": "N/A"
        }

    def run(self):
        while self.running:
            self._read_shared_memory()
            self._fetch_system_stats()
            time.sleep(Config.POLL_INTERVAL)

    def _read_shared_memory(self):
        if not os.path.exists(Config.SHM_FILE):
            self.data["server_online"] = False
            return
        try:
            with open(Config.SHM_FILE, "r") as f:
                json_data = json.load(f)
            self.data.update(json_data)
            self.data["server_online"] = True
        except:
            pass

    def _fetch_system_stats(self):
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                self.data["cpu_temp"] = f"{float(f.read()) / 1000.0:.1f}°C"
        except: pass
        try:
            cmd = "hostname -I | cut -d' ' -f1"
            ip = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
            self.data["ip"] = ip if ip else "No IP"
        except: pass

    def get(self, key, default=None):
        return self.data.get(key, default)

# --- UI LOGIC ---
class MenuController:
    def __init__(self, device, resources, monitor):
        self.device = device
        self.res = resources
        self.monitor = monitor
        self.current_view = 'dashboard'
        self.dashboard_page = 0
        self.menu_index = 0
        self.menu_top_index = 0
        self.edit_mode = False
        self.info_scroll = 0
        self.info_lines = []

        self.menu_items = [
            {'title': 'Zurück', 'type': 'action', 'icon': 'back.png', 'fn': self.go_dashboard},
            {'title': 'Info', 'type': 'action', 'icon': 'info.png', 'fn': self.show_info},
            {'title': 'Reboot', 'type': 'action', 'icon': 'reboot.png', 'cmd': 'sudo reboot'},
            {'title': 'Shutdown', 'type': 'action', 'icon': 'shutdown.png', 'cmd': 'sudo shutdown now'},
        ]

    def go_dashboard(self): self.current_view = 'dashboard'

    def show_info(self):
        try:
            txt = Path("menu-icons/menu-info.txt").read_text(encoding="utf-8")
        except: txt = "Info Datei fehlt."
        self.info_lines = textwrap.wrap(txt, width=18)
        self.current_view = 'info'
        self.info_scroll = 0

    def handle_rotate(self, direction):
        if self.current_view == 'dashboard':
            self.dashboard_page = (self.dashboard_page + direction) % 3
        elif self.current_view == 'info':
            max_scroll = max(0, len(self.info_lines) - 3)
            self.info_scroll = max(0, min(self.info_scroll + direction, max_scroll))
        elif self.current_view == 'menu':
            new_idx = self.menu_index + direction
            if 0 <= new_idx < len(self.menu_items):
                self.menu_index = new_idx
                if self.menu_index >= self.menu_top_index + 3: self.menu_top_index += 1
                elif self.menu_index < self.menu_top_index: self.menu_top_index -= 1

    def handle_click(self):
        if self.current_view != 'menu':
            self.current_view = 'menu'
            return
        item = self.menu_items[self.menu_index]
        if item['type'] == 'action':
            if 'fn' in item: item['fn']()
            elif 'cmd' in item: subprocess.run(item['cmd'], shell=True)

    def update_display(self):
        with canvas(self.device) as draw:
            if self.current_view == 'dashboard': self._draw_dashboard(draw)
            elif self.current_view == 'menu': self._draw_menu(draw)
            elif self.current_view == 'info': self._draw_info(draw)

    def _draw_dashboard(self, draw):
        font = self.res.font
        if self.dashboard_page == 0:
            status = "VERBUNDEN" if self.monitor.get("client_connected") else "WARTEN..."
            draw.text((10, 0), status, font=font, fill="white")
            draw.line((0, 14, 128, 14), fill="white")
            draw.bitmap((2, 20), self.res.get_icon("user.png"), fill="white")
            draw.text((24, 20), str(self.monitor.get("client_name")), font=font, fill="white")
            draw.bitmap((2, 40), self.res.get_icon("network.png"), fill="white")
            draw.text((24, 40), str(self.monitor.get("client_ip")), font=font, fill="white")
        elif self.dashboard_page == 1:
            y = 0
            items = [("temp.png", f"CPU: {self.monitor.get('cpu_temp')}"),
                     ("ok.png" if self.monitor.get("server_online") else "shutdown.png", "Server"),
                     ("network.png", self.monitor.get("ip"))]
            for icon, text in items:
                draw.bitmap((2, y), self.res.get_icon(icon), fill="white")
                draw.text((24, y), text, font=font, fill="white")
                y += 20
        elif self.dashboard_page == 2:
            draw.bitmap((0, 0), self.res.get_icon("servo-tilt.png", (32, 32)), fill="white")
            draw.text((36, 10), f"Tilt: {float(self.monitor.get('tilt', 0)):.1f}°", font=font, fill="white")
            draw.bitmap((0, 32), self.res.get_icon("servo-pan.png", (32, 32)), fill="white")
            draw.text((36, 42), f"Pan: {float(self.monitor.get('pan', 0)):.1f}°", font=font, fill="white")

    def _draw_menu(self, draw):
        for i in range(self.menu_top_index, min(self.menu_top_index + 3, len(self.menu_items))):
            y = (i - self.menu_top_index) * 20
            sel = (i == self.menu_index)
            if sel: draw.rectangle((0, y, 120, y + 20), fill="white")
            draw.bitmap((2, y + 2), self.res.get_icon(self.menu_items[i]['icon']), fill="black" if sel else "white")
            draw.text((24, y + 2), self.menu_items[i]['title'], font=self.res.font, fill="black" if sel else "white")

    def _draw_info(self, draw):
        # Einfache Info-Ansicht
        for i, line in enumerate(self.info_lines[self.info_scroll:self.info_scroll+4]):
            draw.text((2, i*16), line, font=self.res.font, fill="white")

def main():
    try:
        serial = i2c(port=1, address=Config.I2C_ADDR)
        device = sh1106(serial, width=Config.WIDTH, height=Config.HEIGHT)
        encoder = RotaryEncoder(Config.PIN_CLK, Config.PIN_DT, max_steps=1)
        button = Button(Config.PIN_SW, pull_up=True, bounce_time=Config.BOUNCE_TIME)
    except Exception as e:
        print(f"Hardware Fehler: {e}"); return

    res_mgr = ResourceManager()
    monitor = SystemMonitor()
    controller = MenuController(device, res_mgr, monitor)
    monitor.start()

    encoder.when_rotated_clockwise = lambda: controller.handle_rotate(1)
    encoder.when_rotated_counter_clockwise = lambda: controller.handle_rotate(-1)
    button.when_pressed = controller.handle_click

    while True:
        controller.update_display()
        time.sleep(1.0 / Config.FPS)

if __name__ == "__main__":
    main()