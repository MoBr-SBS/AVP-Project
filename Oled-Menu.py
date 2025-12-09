import time
import subprocess
import requests
import threading
from pathlib import Path
from PIL import Image, ImageFont
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106
from gpiozero import RotaryEncoder, Button
import sys
import textwrap


# --- KONFIGURATION ---
class Config:
    # Hardware
    PIN_CLK = 17
    PIN_DT = 18
    PIN_SW = 27
    I2C_ADDR = 0x3C
    BOUNCE_TIME = 0.05

    # Display
    WIDTH = 128
    HEIGHT = 64
    FPS = 30

    # Pfade
    BASE_DIR = Path(__file__).parent
    ICON_DIR = BASE_DIR / "menu-icons"
    FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    # API
    API_URL = "http://localhost:8080/api/status"
    API_POLL_INTERVAL = 1.0  # Sekunden


# --- RESOURCE MANAGER (Caching) ---
class ResourceManager:
    """Lädt Ressourcen nur einmal beim Start."""

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
                    # Fallback: Leeres Bild
                    img = Image.new('1', size, color=0)
                else:
                    img = Image.open(path).convert("1").resize(size)
                self.icons[key] = img
            except Exception as e:
                print(f"Error loading icon {filename}: {e}")
                self.icons[key] = Image.new('1', size, color=0)
        return self.icons[key]


# --- DATA PROVIDER (Hintergrund-Thread) ---
class SystemMonitor(threading.Thread):
    """Holt Daten im Hintergrund, damit das UI nicht blockiert."""

    def __init__(self):
        super().__init__()
        self.daemon = True  # Beendet sich, wenn Hauptprogramm endet
        self.running = True
        self.data = {
            "pan": 90, "tilt": 90, "connected": False,
            "client_ip": "-", "client_name": "Keiner",
            "server_online": False,
            "cpu_temp": "N/A",
            "ip": "N/A"
        }

    def run(self):
        while self.running:
            self._fetch_api()
            self._fetch_system_stats()
            time.sleep(Config.API_POLL_INTERVAL)

    def _fetch_api(self):
        try:
            r = requests.get(Config.API_URL, timeout=0.5)
            if r.status_code == 200:
                json_data = r.json()
                self.data.update(json_data)
                self.data["server_online"] = True
            else:
                self.data["server_online"] = False
        except:
            self.data["connected"] = False
            self.data["server_online"] = False

    def _fetch_system_stats(self):
        # CPU Temp
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                self.data["cpu_temp"] = f"{float(f.read()) / 1000.0:.1f}°C"
        except:
            pass

        # IP Address
        try:
            cmd = "hostname -I | cut -d' ' -f1"
            ip = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
            self.data["ip"] = ip if ip else "No IP"
        except:
            pass

    def get(self, key, default=None):
        return self.data.get(key, default)


# --- UI LOGIC ---
class MenuController:
    def __init__(self, device, resources, monitor):
        self.device = device
        self.res = resources
        self.monitor = monitor

        # State
        self.current_view = 'dashboard'  # dashboard, menu, info
        self.dashboard_page = 0
        self.menu_index = 0
        self.menu_top_index = 0
        self.edit_mode = False
        self.info_scroll = 0
        self.info_lines = []

        # Menu Definition
        self.menu_items = [
            {'title': 'Back', 'type': 'action', 'icon': 'back.png', 'fn': self.go_dashboard},
            {'title': 'Camera', 'type': 'choice', 'options': ['cam1', 'cam2'], 'sel': 0, 'icon': 'camera.png'},
            {'title': 'Speaker', 'type': 'choice', 'options': ['SP1', 'SP2'], 'sel': 0, 'icon': 'speaker.png'},
            {'title': 'Reboot', 'type': 'action', 'icon': 'reboot.png', 'cmd': 'sudo reboot'},
            {'title': 'Shutdown', 'type': 'action', 'icon': 'shutdown.png', 'cmd': 'sudo shutdown now'},
            {'title': 'Info', 'type': 'action', 'icon': 'info.png', 'fn': self.show_info},
        ]

    # --- Actions ---
    def go_dashboard(self):
        self.current_view = 'dashboard'

    def show_info(self):
        self.load_info_text()
        self.current_view = 'info'
        self.info_scroll = 0

    def load_info_text(self):
        try:
            txt = Path("info.txt").read_text(encoding="utf-8")
        except FileNotFoundError:
            txt = "Info.txt fehlt."
        self.info_lines = textwrap.wrap(txt, width=18)

    # --- Inputs ---
    def handle_rotate(self, direction):
        """1 = Clockwise, -1 = Counter-Clockwise"""

        if self.current_view == 'dashboard':
            pages = 3
            self.dashboard_page = (self.dashboard_page + direction) % pages

        elif self.current_view == 'info':
            max_scroll = max(0, len(self.info_lines) - 3)
            self.info_scroll = max(0, min(self.info_scroll + direction, max_scroll))

        elif self.current_view == 'menu':
            if not self.edit_mode:
                # Normal Navigation
                new_idx = self.menu_index + direction
                if 0 <= new_idx < len(self.menu_items):
                    self.menu_index = new_idx
                    # Scroll Logik
                    vis_items = 3
                    if self.menu_index >= self.menu_top_index + vis_items:
                        self.menu_top_index += 1
                    elif self.menu_index < self.menu_top_index:
                        self.menu_top_index -= 1
            else:
                # Werte ändern
                item = self.menu_items[self.menu_index]
                if item['type'] == 'choice':
                    item['sel'] = (item['sel'] + direction) % len(item['options'])

    def handle_click(self):
        if self.current_view == 'dashboard' or self.current_view == 'info':
            self.current_view = 'menu'
            self.menu_index = 0
            self.menu_top_index = 0
            return

        # Menu Logic
        item = self.menu_items[self.menu_index]

        if self.edit_mode:
            self.edit_mode = False  # Save
            return

        if item['type'] == 'action':
            if 'fn' in item:
                item['fn']()
            elif 'cmd' in item:
                self.draw_message("Exec:", item['title'])
                subprocess.run(item['cmd'], shell=True)
        elif item['type'] in ['choice', 'numeric']:
            self.edit_mode = True

    # --- Drawing ---
    def draw_message(self, line1, line2):
        with canvas(self.device) as draw:
            draw.text((10, 20), line1, font=self.res.font, fill="white")
            draw.text((10, 40), line2, font=self.res.font, fill="white")
        time.sleep(1)

    def update_display(self):
        with canvas(self.device) as draw:
            draw.rectangle(self.device.bounding_box, outline="black", fill="black")

            if self.current_view == 'dashboard':
                self._draw_dashboard(draw)
            elif self.current_view == 'menu':
                self._draw_menu(draw)
            elif self.current_view == 'info':
                self._draw_info(draw)

    def _draw_dashboard(self, draw):
        # Schriftart holen
        font = self.res.font

        if self.dashboard_page == 0:  # Client Info
            status = "VERBUNDEN" if self.monitor.get("connected") else "WARTEN..."
            draw.text((10, 0), status, font=font, fill="white")
            draw.line((0, 14, 128, 14), fill="white")

            draw.bitmap((2, 20), self.res.get_icon("user.png"), fill="white")
            draw.text((24, 20), str(self.monitor.get("client_name")), font=font, fill="white")

            draw.bitmap((2, 40), self.res.get_icon("network.png"), fill="white")
            draw.text((24, 40), str(self.monitor.get("client_ip")), font=font, fill="white")

        elif self.dashboard_page == 1:  # System Stats
            y = 0
            items = [
                ("temp.png", f"CPU: {self.monitor.get('cpu_temp')}"),
                ("ok.png" if self.monitor.get("server_online") else "shutdown.png", "Server"),
                ("network.png", self.monitor.get("ip"))
            ]
            for icon_name, text in items:
                # Hier nutzen wir Standardgröße (16x16)
                draw.bitmap((2, y), self.res.get_icon(icon_name), fill="white")
                draw.text((24, y), text, font=font, fill="white")
                y += 20

        elif self.dashboard_page == 2:  # Servos (Angepasst nach deinem Wunsch)
            # Wir brauchen hier große Icons (32x32)
            icon_size = (32, 32)

            # --- OBERE HÄLFTE: TILT ---
            # Icon bei X=0, Y=0
            icon_tilt = self.res.get_icon("servo-tilt.png", size=icon_size)
            draw.bitmap((0, 0), icon_tilt, fill="white")

            # Text daneben (X=36), vertikal mittig im 32er Block (Y=10 ca.)
            tilt_val = self.monitor.get('tilt', 0)
            draw.text((36, 10), f"Tilt: {tilt_val}°", font=font, fill="white")

            # --- UNTERE HÄLFTE: PAN ---
            # Icon bei X=0, Y=32
            icon_pan = self.res.get_icon("servo-pan.png", size=icon_size)
            draw.bitmap((0, 32), icon_pan, fill="white")

            # Text daneben (X=36), vertikal mittig im unteren Block (Y=42 ca.)
            pan_val = self.monitor.get('pan', 0)
            draw.text((36, 42), f"Pan: {pan_val}°", font=font, fill="white")

    def _draw_menu(self, draw):
        font = self.res.font
        visible_cnt = 3

        for i in range(self.menu_top_index, min(self.menu_top_index + visible_cnt, len(self.menu_items))):
            item = self.menu_items[i]
            y = (i - self.menu_top_index) * 20
            selected = (i == self.menu_index)

            bg = "white" if selected else "black"
            fg = "black" if selected else "white"

            if selected:
                draw.rectangle((0, y, 120, y + 20), fill="white")

            # Icon
            icon = self.res.get_icon(item['icon'])
            draw.bitmap((2, y + 2), icon, fill=fg)

            # Text
            text = item['title']
            if selected and self.edit_mode and item['type'] == 'choice':
                text = f"<{item['options'][item['sel']]}>"
            elif item['type'] == 'choice':
                text = f"{text}: {item['options'][item['sel']]}"

            draw.text((24, y + 2), text, font=font, fill=fg)

        # Einfache Scrollbar
        sb_h = Config.HEIGHT * (visible_cnt / len(self.menu_items))
        sb_y = (self.menu_top_index / len(self.menu_items)) * Config.HEIGHT
        draw.rectangle((124, sb_y, 127, sb_y + sb_h), fill="white")

    def _draw_info(self, draw):
        font = self.res.font
        line_height = 16

        # 1. Layout und Text-Startindex bestimmen
        if self.info_scroll == 0:
            # --- ZUSTAND: GANZ OBEN ---
            # Header anzeigen
            draw.text((0, 0), "INFO", font=font, fill="white")
            draw.line((0, 14, 128, 14), fill="white")

            start_y = 16
            visible_lines = 3

            # Text beginnt normal bei 0
            text_start_index = 0

        else:
            # --- ZUSTAND: GESCROLLT ---
            # Kein Header, volle Höhe nutzen
            start_y = 0
            visible_lines = 4

            text_start_index = self.info_scroll - 1

        # 2. Text zeichnen
        slice_end = text_start_index + visible_lines
        current_slice = self.info_lines[text_start_index: slice_end]

        for i, line in enumerate(current_slice):
            draw.text((2, start_y + i * line_height), line, font=font, fill="white")

        # 3. Scrollbar zeichnen
        total_lines = len(self.info_lines)

        if total_lines > visible_lines:
            ratio = visible_lines / total_lines
            sb_h = max(5, int(Config.HEIGHT * ratio))

            # Position berechnen
            max_scroll = total_lines - visible_lines

            # Wir nutzen hier self.info_scroll für die Position,
            # damit der Balken sich sofort bewegt, wenn man dreht.
            if max_scroll > 0:
                progress = self.info_scroll / max_scroll
            else:
                progress = 0

            # Begrenzen auf 1.0 (da wir durch den Trick evtl. etwas weiter drehen können)
            progress = min(progress, 1.0)

            available_height = Config.HEIGHT - sb_h
            sb_y = int(progress * available_height)

            draw.rectangle((124, sb_y, 127, sb_y + sb_h), fill="white")


# --- MAIN ---
def main():
    # Setup Hardware
    try:
        serial = i2c(port=1, address=Config.I2C_ADDR)
        device = sh1106(serial, width=Config.WIDTH, height=Config.HEIGHT)
        encoder = RotaryEncoder(Config.PIN_CLK, Config.PIN_DT, max_steps=1)
        button = Button(Config.PIN_SW, pull_up=True, bounce_time=Config.BOUNCE_TIME)
    except Exception as e:
        print(f"Hardware Error: {e}")
        return

    # Init Subsystems
    res_mgr = ResourceManager()
    monitor = SystemMonitor()
    controller = MenuController(device, res_mgr, monitor)

    monitor.start()  # Startet den Hintergrund-Thread für API calls

    # Input Callbacks
    def on_cw():
        controller.handle_rotate(1)

    def on_ccw():
        controller.handle_rotate(-1)

    def on_btn():
        controller.handle_click()

    encoder.when_rotated_clockwise = on_cw
    encoder.when_rotated_counter_clockwise = on_ccw
    button.when_pressed = on_btn

    print("System started.")

    # Splash
    try:
        splash = Image.open(Config.ICON_DIR / "splash_screen.png").convert("1").resize((128, 64))
        device.display(splash)
        time.sleep(2)
    except:
        pass

    # Main Loop
    try:
        while True:
            controller.update_display()
            time.sleep(1.0 / Config.FPS)
    except KeyboardInterrupt:
        monitor.running = False
        monitor.join()
        print("Bye.")


if __name__ == "__main__":
    main()