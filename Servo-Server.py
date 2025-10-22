import asyncio
import websockets


async def set_angle(websocket):
    # Abrufen der Client-Adresse
    peer = websocket.remote_address
    print(f"Neue Verbindung von {peer} angenommen.")

    while True:
        try:
            angle_string = await websocket.recv()
            angle_list = angle_string.split(',')

            pan_angle = int(angle_list[0])
            tilt_angle = int(angle_list[1])

        except websockets.exceptions.ConnectionClosed as e:
            print(f"Verbindung beendet von {peer}. Status: {e.code}")
            break

        # Fängt Fehler beim Parsen (int() oder Index [0]/[1]) ab
        except (ValueError, IndexError):
            try:
                print(f"ERROR von {peer}: Ungültiges Format empfangen: {angle_string!r}.")
            except NameError:
                # Wird ausgelöst, wenn angle_string nicht definiert werden konnte
                print(f"ERROR von {peer}: Ungültiges Datenformat (lesefehler).")
            continue  # Springt zur nächsten Nachricht

        # 3. Servo-Logik (Ausgabe zur Bestätigung)
        print(f'Pan: {pan_angle}, Tilt: {tilt_angle}')


async def start_server():
    # websockets.serve ruft set_angle(websocket) auf
    async with websockets.serve(
            set_angle,
            '0.0.0.0',
            8765,
            ping_interval=10,
            ping_timeout=5
    ):
        print("Server gestartet auf ws://localhost:8765. Warten...")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(start_server())