import asyncio
import websockets


async def send_angle():
    uri = "ws://localhost:8765"
    try:

        async with websockets.connect(uri) as websocket:
            print("Verbunden. Geben Sie Winkel ein (z.B. 100,20):")


            while True:
                angle = "10,20"
                #angle = input('> ')
                if angle.lower() == 'exit':
                    break

                #await websocket.send(angle)
                print(f"Gesendet: {angle}")

                await asyncio.sleep(1000)

    except ConnectionRefusedError:
        print("FEHLER: Verbindung zum Server abgelehnt.")



if __name__ == "__main__":
    asyncio.run(send_angle())