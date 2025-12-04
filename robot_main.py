import asyncio
import json
import board
import busio
from aiohttp import web
from adafruit_servokit import ServoKit

# --- KONFIGURATION ---
# I2C Setup für Raspberry Pi 5
i2c = busio.I2C(board.SCL, board.SDA)

# PCA9685 initialisieren (16 Kanäle)
kit = ServoKit(channels=16, i2c=i2c)

# Servo Kanäle (Anpassen an deine Verkabelung!)
PAN_CHANNEL = 10
TILT_CHANNEL = 11

# Startposition (90 Grad = Mitte)
kit.servo[PAN_CHANNEL].angle = 90
kit.servo[TILT_CHANNEL].angle = 90

print("Servos initialisiert.")


# --- WEBSOCKET HANDLER ---
async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    print("Client verbunden (Websocket)")

    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            try:
                # Wir erwarten JSON: {"pan": 0.5, "tilt": -0.2}
                # Wertebereich vom Client sollte ca -1.0 bis +1.0 sein (oder Grad)
                data = json.loads(msg.data)

                if 'pan' in data and 'tilt' in data:
                    # Empfangene Werte (Mapping anpassen!)
                    # Hier nehme ich an, der Client sendet direkt Winkel (0-180)
                    # Oder relative Werte, die wir umrechnen.
                    # Für diesen Test sendet die index.html WINKEL (0 bis 180).

                    pan = float(data['pan'])
                    tilt = float(data['tilt'])

                    # Sicherheits-Begrenzung (Clamping)
                    pan = max(0, min(180, pan))
                    tilt = max(0, min(180, tilt))

                    # Servos bewegen
                    kit.servo[PAN_CHANNEL].angle = pan
                    kit.servo[TILT_CHANNEL].angle = tilt

            except ValueError:
                pass
            except Exception as e:
                print(f"Fehler: {e}")

        elif msg.type == web.WSMsgType.ERROR:
            print('Verbindung geschlossen mit Fehler %s', ws.exception())

    print("Client getrennt")
    return ws


# --- HTML SERVING ---
async def index(request):
    # Liefert die index.html aus
    return web.FileResponse('./index.html')


# --- MAIN APP SETUP ---
app = web.Application()
app.router.add_get('/', index)  # Startseite
app.router.add_get('/ws', websocket_handler)  # Websocket Endpunkt

if __name__ == '__main__':
    print("Starte Roboter-Server auf Port 8080...")
    web.run_app(app, host='0.0.0.0', port=8080)