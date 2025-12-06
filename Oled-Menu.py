import time
import subprocess
import requests
import socket
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106
from gpiozero import RotaryEncoder, Button
from PIL import Image, ImageFont
import sys
import textwrap

# --- 1. Hardware-Konfiguration & Konstanten ---
PIN_CLK = 17
PIN_DT = 18
PIN_SW = 27
I2C_ADDR = 0x3C
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 64
SPLASH_DURATION = 1.0

# Text-Konstanten für die Info-Seite
LINE_HEIGHT = 16
MAX_CONTENT_LINES = (DISPLAY_HEIGHT // LINE_HEIGHT) - 1  # 3 Zeilen Inhalt + 1 Zeile Titel
MAX_CHARS_PER_LINE = 18

# Menü-Konstanten
MENU_LINE_HEIGHT = 20
MAX_VISIBLE_MENU_ITEMS = 3
SCROLLBAR_WIDTH = 4  # Breite der Scrollbar

# --- 2. Globale Zustandsvariablen & Konfiguration ---

# types: numeric, choice, action
menu_items = [
    {
        'title': 'Back',
        'type': 'action',
        'icon': 'back.png'
    },
    {
        'title': 'Camera',
        'type': 'choice',
        'options': ['cam1', 'cam2', 'cam3', 'cam4', 'cam5'],
        'selected_index': 0,
        'icon': 'camera.png'
    },
    {
        'title': 'Speaker',
        'type': 'choice',
        'options': ['Speaker1', 'Speaker2', 'Speaker3'],
        'selected_index': 0,
        'icon': 'speaker.png'
    },
    {
        'title': 'Microphone',
        'type': 'choice',
        'options': ['Mic1', 'Mic2', 'Mic3'],
        'selected_index': 0,
        'icon': 'microphone.png'
    },
    {
        'title': 'Reboot',
        'type': 'action',
        'icon': 'reboot.png',
        'action_command': 'sudo reboot'
    },
    {
        'title': 'Shutdown',
        'type': 'action',
        'icon': 'shutdown.png',
        'action_command': 'sudo shutdown now'
    },
    {
        'title': 'Info',
        'type': 'action',
        'icon': 'info.png'
    }
]


# --- HILFSFUNKTIONEN FÜR DASHBOARD-DATEN (TESTWERTE) ---



def get_mic_status(): return True


def get_speaker_status(): return False


def get_camera_status(): return True


def get_servo1_angle(): return 45


def get_servo2_angle(): return 135


# --- HILFSFUNKTIONEN FÜR DASHBOARD ---

# Cache Variablen, damit wir nicht bei jedem Frame den Server fragen
last_api_check = 0
cached_api_data = {
    "pan": 90,
    "tilt": 90,
    "connected": False,
    "client_ip": "Warten...",
    "client_name": "Keiner"
}


def update_api_data():
    """Holt Daten vom Roboter-Server, aber maximal alle 0.5 Sekunden"""
    global last_api_check, cached_api_data

    if time.time() - last_api_check < 0.5:
        return cached_api_data

    try:
        # Timeout ist wichtig, damit das Menü nicht hängt!
        r = requests.get("http://localhost:8080/api/status", timeout=0.2)
        if r.status_code == 200:
            cached_api_data = r.json()
    except:
        # Wenn Server aus ist
        cached_api_data = {
            "pan": 90,
            "tilt": 90,
            "connected": False,
            "client_ip": "Warten...",
            "client_name": "Keiner"
        }

    last_api_check = time.time()
    return cached_api_data


# --- Getter Funktionen anpassen ---
def get_camera_status():
    # Zeigt an, ob ein User per Websocket verbunden ist
    data = update_api_data()
    return data.get("connected", False)


def get_servo1_angle():  # Tilt
    data = update_api_data()
    return int(data.get("tilt", 0))


def get_servo2_angle():  # Pan
    data = update_api_data()
    return int(data.get("pan", 0))


def get_system_status():
    # Prüfen ob der Server antwortet
    try:
        requests.get("http://localhost:8080", timeout=0.2)
        return "Online"
    except:
        return "Offline"

def get_cpu_temp():
    temp_path = "/sys/class/thermal/thermal_zone0/temp"
    try:
        with open(temp_path, "r") as f:
            temp_c = float(f.read()) / 1000.0
        return f"{temp_c:.1f} °C"
    except Exception:
        return "N/A"


def get_ip_address():
    try:
        cmd = "hostname -I | cut -d' ' -f1"
        ip = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
        return ip if ip else "No IP found"
    except Exception:
        return "N/A"


def get_display_ip():
    ip_addr = get_ip_address()
    if ip_addr not in ["N/A", "No IP found", "127.0.0.1"]:
        octets = ip_addr.split('.')
        return "..." + ".".join(octets[-2:])
    else:
        return ip_addr


# Konfiguration der Dashboard-Seiten
dashboard_webrtc_items = [
    {'icon_on': 'mic-on.png', 'icon_off': 'mic-off.png', 'getter': get_mic_status},
    {'icon_on': 'speaker-on.png', 'icon_off': 'speaker-off.png', 'getter': get_speaker_status},
    {'icon_on': 'camera-on.png', 'icon_off': 'camera-off.png', 'getter': get_camera_status}
]
dashboard_servo_items = [
    {'label': 'Tilt', 'icon': 'servo-tilt.png', 'getter': get_servo1_angle},
    {'label': 'Pan', 'icon': 'servo-pan.png', 'getter': get_servo2_angle}
]
dashboard_system_items = [
    {'label': 'CPU', 'icon': 'temp.png', 'getter': get_cpu_temp},
    {'label': 'IP', 'icon': 'network.png', 'getter': get_display_ip},
    {'label': 'Robot', 'icon': 'ok.png', 'getter': get_system_status} # Umbenannt
]

# ZUSTANDSVARIABLEN
NUM_DASHBOARD_PAGES = 3
current_dashboard_page = 0
current_menu_index = 0
edit_mode = False
current_view = 'dashboard'  # Kann 'dashboard', 'menu' oder 'info' sein
needs_redraw = True
top_index = 0
info_scroll_offset = 0
wrapped_info_lines = []


# --- 3. Hardware und Hilfsfunktionen initialisieren ---

def load_icon(filename, size=(16, 16)):
    """Lädt ein Bild, skaliert es und konvertiert es zu Monochrom (1-Bit)."""
    try:
        path = f"menu-icons/{filename}"
        icon = Image.open(path).convert("1")
        icon = icon.resize(size)
        return icon
    except FileNotFoundError:
        # Erzeugt ein leeres 1-Bit Bild, falls das Icon fehlt.
        return Image.new('1', size, color=0)


try:
    serial = i2c(port=1, address=I2C_ADDR)
    device = sh1106(serial, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
    except IOError:
        font = ImageFont.load_default()

    encoder = RotaryEncoder(a=PIN_CLK, b=PIN_DT, max_steps=1)
    button = Button(PIN_SW, pull_up=True, bounce_time=0.1)

except Exception as e:
    print(f"Fehler beim Initialisieren der Hardware: {e}")
    sys.exit(1)


# --- 4. ZEICHENFUNKTIONEN FÜR INFO & DASHBOARD ---

def read_and_wrap_info(filename="info.txt"):
    """Liest Info-Text und bricht ihn für das Display um."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read().strip()
    except FileNotFoundError:
        return ["Info.txt", "nicht gefunden. Bitte erstellen Sie die Datei."]
    lines = textwrap.wrap(content, width=MAX_CHARS_PER_LINE)
    return lines


# Hilfsfunktion zum Zeichnen der Scrollbar
def draw_scrollbar(draw, max_items, visible_items, current_offset, y_start, height):
    """Zeichnet eine Scrollbar am rechten Rand."""

    SCROLLBAR_X = DISPLAY_WIDTH - SCROLLBAR_WIDTH - 1

    # Nur zeichnen, wenn Scrollen notwendig ist
    if max_items <= visible_items:
        return

    # Scrollbalken-Block (Thumb)
    scrollable_range = max_items - visible_items

    # Höhe des Thumb (mindestens 2 Pixel)
    thumb_height = max(2, int(height * (visible_items / max_items)))

    # Maximale Scroll-Distanz für den Thumb
    max_thumb_travel = height - thumb_height

    # Aktuelle Position des Thumbs
    scroll_ratio = current_offset / scrollable_range
    thumb_y_offset = int(max_thumb_travel * scroll_ratio)

    # Zeichne den Thumb relativ zum y_start der Scrollbar
    draw.rectangle((SCROLLBAR_X, y_start + thumb_y_offset,
                    SCROLLBAR_X + SCROLLBAR_WIDTH, y_start + thumb_y_offset + thumb_height),
                   outline="white", fill="white")


def draw_info_page():
    """Zeichnet die Info-Seite mit umgebrochenem Text aus der Datei, inklusive Scrollen."""
    global info_scroll_offset, wrapped_info_lines

    display_lines = wrapped_info_lines[info_scroll_offset: info_scroll_offset + MAX_CONTENT_LINES]
    total_lines = len(wrapped_info_lines)

    with canvas(device) as draw:
        draw.rectangle(device.bounding_box, outline="black", fill="black")

        # 1. Titel
        draw.text((2, 0), "Projekt Info", font=font, fill="white")
        draw.line((0, LINE_HEIGHT - 2, DISPLAY_WIDTH, LINE_HEIGHT - 2), fill="white")

        # 2. Inhalt
        for i, line in enumerate(display_lines):
            draw.text((2, LINE_HEIGHT + i * LINE_HEIGHT), line, font=font, fill="white")

        # 3. Scrollbar (Nur der Bereich UNTER dem Titel)
        SCROLLBAR_Y = LINE_HEIGHT
        SCROLLBAR_HEIGHT = DISPLAY_HEIGHT - LINE_HEIGHT

        draw_scrollbar(draw, total_lines, MAX_CONTENT_LINES, info_scroll_offset, SCROLLBAR_Y, SCROLLBAR_HEIGHT)


def draw_client_info():
    # Daten von der API holen
    data = update_api_data()
    is_connected = data.get("connected", False)
    name = data.get("client_name", "Niemand")
    ip = data.get("client_ip", "-")

    ICON_SIZE = (16, 16)

    # Icons laden (Dateinamen an deine Icons anpassen!)

    icon_user = load_icon("user.png", ICON_SIZE)
    icon_net = load_icon("network.png", ICON_SIZE)

    with canvas(device) as draw:
        draw.rectangle(device.bounding_box, outline="black", fill="black")

        # 1. Überschrift (Zentriert)
        header = "VERBUNDEN" if is_connected else "WARTE AUF LOGIN..."
        w = draw.textlength(header, font=font)
        draw.text(((DISPLAY_WIDTH - w) // 2, 0), header, font=font, fill="white")
        draw.line((0, 14, DISPLAY_WIDTH, 14), fill="white")

        # 2. Zeile: User
        # Icon bei X=2, Text daneben
        draw.bitmap((2, 20), icon_user, fill="white")
        draw.text((24, 20), f"{name}", font=font, fill="white")

        # 3. Zeile: IP
        # Icon bei X=2, Text daneben (tiefer gesetzt)
        draw.bitmap((2, 40), icon_net, fill="white")
        draw.text((24, 40), f"{ip}", font=font, fill="white")


def draw_system_info():
    """Seite 1: System Info (CPU Temp, IP, Status) mit 16x16 Icons."""
    ICON_SIZE = (16, 16)
    ICON_SPACE = 20
    LINE_HEIGHT = 20
    with canvas(device) as draw:
        draw.rectangle(device.bounding_box, outline="black", fill="black")
        for i, item in enumerate(dashboard_system_items):
            y = 0 + i * LINE_HEIGHT
            live_value = item['getter']()
            icon_img = load_icon(item['icon'], ICON_SIZE)
            icon_pos_y = y
            draw.bitmap((2, icon_pos_y), icon_img, fill="white")
            draw.text((ICON_SPACE, y), f"{item['label']}:", font=font, fill="white")
            draw.text((75, y), live_value, font=font, fill="white")


def draw_servo_angles():
    """Seite 2: Zwei 32x32 Servo-Icons nebeneinander mit zentrierter Beschriftung darunter."""
    ICON_SIZE = (32, 32)
    NUM_ICONS = 2
    GAP = (DISPLAY_WIDTH - (NUM_ICONS * ICON_SIZE[0])) // (NUM_ICONS + 1)
    ICON_Y = 4
    TEXT_Y_START = 40
    with canvas(device) as draw:
        draw.rectangle(device.bounding_box, outline="black", fill="black")
        for i, item in enumerate(dashboard_servo_items):
            x_pos_icon = GAP + (i * ICON_SIZE[0]) + (i * GAP)
            icon_img = load_icon(item['icon'], ICON_SIZE)
            draw.bitmap((x_pos_icon, ICON_Y), icon_img, fill="white")
            angle = item['getter']()
            display_text = f"{item['label']}: {angle} °"
            text_width = draw.textlength(display_text, font=font)
            text_x_pos = x_pos_icon + (ICON_SIZE[0] // 2) - (text_width // 2)
            draw.text((text_x_pos, TEXT_Y_START), display_text, font=font, fill="white")


# --- 5. HAUPT-ZEICHENFUNKTIONEN ---

def show_splash_screen():
    """Zeigt ein statisches PNG für 3 Sekunden beim Programmstart an."""
    SPLASH_FILE = "menu-icons/splash_screen.png"
    try:
        splash_img = Image.open(SPLASH_FILE).resize((DISPLAY_WIDTH, DISPLAY_HEIGHT)).convert("1")
        device.display(splash_img)
    except Exception as e:
        print(f"WARNUNG: Splash-Screen-Fehler: {e}")
    time.sleep(SPLASH_DURATION)
    device.clear()


def draw_menu():
    """Zeichnet das Menü, nun mit korrigierter Icon-Farbe und Scrollbar."""
    global needs_redraw
    needs_redraw = False

    ICON_SIZE = (16, 16)
    ICON_X = 2
    TEXT_X = ICON_SIZE[0] + ICON_X + 2

    total_items = len(menu_items)

    with canvas(device) as draw:
        draw.rectangle(device.bounding_box, outline="black", fill="black")

        for i in range(top_index, min(top_index + MAX_VISIBLE_MENU_ITEMS, total_items)):
            item = menu_items[i]
            visible_line = i - top_index
            y = visible_line * MENU_LINE_HEIGHT

            # Wähle Farben basierend auf Auswahl-Status
            is_selected = (i == current_menu_index)
            text_color = "black" if is_selected else "white"
            bg_color = "white" if is_selected else "black"
            icon_color = "black" if is_selected else "white"  # Iconfarbe muss invertiert sein, wenn Hintergrund weiß ist

            # 1. Zeichne das Markierungsrechteck (Hervorhebung)
            if is_selected:
                # Zeichne das Rechteck nur bis zum Beginn der Scrollbar, falls vorhanden
                rect_width = DISPLAY_WIDTH
                if total_items > MAX_VISIBLE_MENU_ITEMS:
                    rect_width -= (SCROLLBAR_WIDTH + 1)

                draw.rectangle((0, y, rect_width, y + MENU_LINE_HEIGHT), outline="white", fill=bg_color)

            # 2. Icon zeichnen
            icon_img = load_icon(item['icon'], ICON_SIZE)
            icon_pos_y = y + 2
            draw.bitmap((ICON_X, icon_pos_y), icon_img, fill=icon_color)

            # 3. Text zeichnen
            title = item['title']
            prefix = "> " if is_selected and not edit_mode else "  "  # ">" nur wenn ausgewählt und nicht im Edit-Modus

            if is_selected and edit_mode:
                if item['type'] == 'numeric':
                    display_text = f"[{title}: {item['value']}]"
                elif item['type'] == 'choice':
                    option_text = item['options'][item['selected_index']]
                    display_text = f"[{title}: {option_text}]"
                else:
                    display_text = f"{title}"
            else:
                display_text = f"{prefix}{title}"

            draw.text((TEXT_X, y + 2), display_text, font=font, fill=text_color)

        # NEU: Scrollbar zeichnen (verwendet die gesamte Höhe)
        draw_scrollbar(draw, total_items, MAX_VISIBLE_MENU_ITEMS, top_index, 0, DISPLAY_HEIGHT)


def draw_dashboard():
    global needs_redraw
    needs_redraw = False

    if current_dashboard_page == 0:
        # HIER die neue Funktion aufrufen statt draw_webrtc_status
        draw_client_info()

    elif current_dashboard_page == 1:
        draw_system_info()
    elif current_dashboard_page == 2:
        draw_servo_angles()


# --- 6. EVENT-HANDLER (Callbacks) ---

def get_current_value(item):
    if item['type'] == 'numeric':
        return item['value']
    if item['type'] == 'choice':
        return item['options'][item['selected_index']]
    return "N/A"


def on_rotate_clockwise():
    global current_menu_index, edit_mode, needs_redraw, top_index, current_dashboard_page, info_scroll_offset

    needs_redraw = True

    if current_view == 'dashboard':
        current_dashboard_page = (current_dashboard_page + 1) % NUM_DASHBOARD_PAGES
        return

    if current_view == 'info':
        total_lines = len(wrapped_info_lines)
        max_offset = total_lines - MAX_CONTENT_LINES
        if max_offset > 0:
            info_scroll_offset = min(info_scroll_offset + 1, max_offset)
        return

    if current_view == 'menu':
        if not edit_mode:
            total_items = len(menu_items)
            current_menu_index = (current_menu_index + 1) % total_items

            if current_menu_index >= top_index + MAX_VISIBLE_MENU_ITEMS:
                top_index += 1
            elif current_menu_index == 0:
                top_index = 0

        else:
            item = menu_items[current_menu_index]
            if item.get('type') == 'numeric' and 'max' in item and 'step' in item:
                item['value'] = min(item['max'], item['value'] + item['step'])
            elif item['type'] == 'choice':
                item['selected_index'] = (item['selected_index'] + 1) % len(item['options'])


def on_rotate_counter_clockwise():
    global current_menu_index, edit_mode, needs_redraw, top_index, current_dashboard_page, info_scroll_offset

    needs_redraw = True

    if current_view == 'dashboard':
        current_dashboard_page = (current_dashboard_page - 1) % NUM_DASHBOARD_PAGES
        return

    if current_view == 'info':
        info_scroll_offset = max(0, info_scroll_offset - 1)
        return

    if current_view == 'menu':
        if not edit_mode:
            total_items = len(menu_items)
            current_menu_index = (current_menu_index - 1) % total_items

            if current_menu_index < top_index:
                top_index -= 1
            elif current_menu_index == total_items - 1 and total_items > MAX_VISIBLE_MENU_ITEMS:
                top_index = total_items - MAX_VISIBLE_MENU_ITEMS

        else:
            item = menu_items[current_menu_index]
            if item.get('type') == 'numeric' and 'min' in item and 'step' in item:
                item['value'] = max(item['min'], item['value'] - item['step'])
            elif item['type'] == 'choice':
                item['selected_index'] = (item['selected_index'] - 1) % len(item['options'])


def on_button_press():
    global edit_mode, current_view, needs_redraw, current_menu_index, top_index, info_scroll_offset, wrapped_info_lines

    needs_redraw = True

    if current_view == 'info':
        current_view = 'menu'
        return

    if current_view == 'dashboard':
        current_view = 'menu'
        current_menu_index = 0
        top_index = 0
        return

    # --- MENÜ-LOGIK ---
    item = menu_items[current_menu_index]

    if edit_mode:
        edit_mode = False
        print(f"Wert gespeichert: {item['title']} ist jetzt {get_current_value(item)}")
    else:
        # Check auf 'Back'
        if item['title'] == 'Back':
            current_view = 'dashboard'
            current_menu_index = 0
            top_index = 0
        elif item['type'] == 'numeric' or item['type'] == 'choice':
            edit_mode = True
        elif item['type'] == 'action':

            if item['title'] == 'Info':
                wrapped_info_lines = read_and_wrap_info()
                info_scroll_offset = 0
                current_view = 'info'
                return

            # Überprüfen, ob ein Shell-Befehl hinterlegt ist (Reboot/Shutdown)
            if 'action_command' in item:
                command = item['action_command']
                with canvas(device) as draw:
                    draw.rectangle(device.bounding_box, outline="black", fill="black")
                    draw.text((10, 10), f"Starte Aktion:", font=font, fill="white")
                    draw.text((10, 30), f"'{item['title']}'", font=font, fill="white")
                time.sleep(1.0)
                print(f"AKTION AUSGEFÜHRT: {item['title']} - Führe Befehl aus: {command}")
                try:
                    subprocess.run(command, shell=True, check=True)
                    sys.exit(0)
                except Exception as e:
                    print(f"FEHLER beim Ausführen von {command}: {e}")
                    with canvas(device) as draw:
                        draw.rectangle(device.bounding_box, outline="black", fill="black")
                        draw.text((10, 10), "FEHLER!", font=font, fill="white")
                        draw.text((10, 30), "Befehl fehlgeschlagen", font=font, fill="white")
                    time.sleep(2.0)
            else:
                print(f"AKTION AUSGEFÜHRT: {item['title']}")
                with canvas(device) as draw:
                    draw.rectangle(device.bounding_box, outline="black", fill="black")
                    draw.text((10, 20), f"Aktion:\n {item['title']}", font=font, fill="white")
                time.sleep(1.5)

    needs_redraw = True


# --- 7. Haupt-Schleife ---
encoder.when_rotated_clockwise = on_rotate_clockwise
encoder.when_rotated_counter_clockwise = on_rotate_counter_clockwise
button.when_pressed = on_button_press

print("Menü-System gestartet.")

# Splash-Screen beim Start anzeigen
show_splash_screen()

try:
    while True:
        if needs_redraw or current_view == 'dashboard':
            if current_view == 'menu':
                draw_menu()
                needs_redraw = False
            elif current_view == 'info':
                draw_info_page()
                needs_redraw = False
            else:  # current_view == 'dashboard'
                draw_dashboard()
                needs_redraw = True

        time.sleep(0.033)

except KeyboardInterrupt:
    print("Skript beendet.")
    device.cleanup()
