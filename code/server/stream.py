"""MJPEG-Stream aus /dev/video0 als multipart/x-mixed-replace über HTTPS."""

import asyncio
import select as _select

from aiohttp import web

# Modul-globale Liste aller aktiven Stream-Subscriber (asyncio.Queue je Client)
_subscribers: list = []
_capture_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# Token-Validierung
# ---------------------------------------------------------------------------

async def _validate_token(request: web.Request) -> bool:
    """Prüft ?token=... gegen app['sessions']. Bei auth.required=false immer True."""
    cfg = request.app["config"]
    if not cfg.get("auth", {}).get("required", True):
        return True

    token = request.rel_url.query.get("token", "")
    if not token:
        return False
    return token in request.app.get("sessions", {})


# ---------------------------------------------------------------------------
# Blocking-I/O-Helfer (laufen im Thread-Pool via run_in_executor)
# ---------------------------------------------------------------------------

def _open_device_blocking(device: str, width: int, height: int):
    """Öffnet das V4L2-Gerät und fordert MJPEG-Format an. Gibt (kind, cap) zurück."""
    try:
        import v4l2capture
        video = v4l2capture.Video_device(device)
        video.set_format(width, height, "MJPEG")
        video.create_buffers(2)
        video.start()
        print(f"[STREAM] v4l2capture: {device} bereit ({width}x{height}, MJPEG, kein Re-Encoding)")
        return "v4l2", video
    except ImportError:
        print("[STREAM] v4l2capture nicht installiert, versuche cv2 …")

    try:
        import cv2
        cap = cv2.VideoCapture(device)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not cap.isOpened():
            raise RuntimeError(f"cv2 konnte {device} nicht öffnen")
        print(f"[STREAM] cv2: {device} bereit ({width}x{height}) [Re-Encoding aktiv]")
        return "cv2", cap
    except ImportError:
        pass

    raise RuntimeError("[STREAM] FEHLER: Weder v4l2capture noch cv2 verfügbar!")


def _read_frame_blocking(kind: str, cap) -> bytes:
    """Liest einen JPEG-Frame (blockierend). v4l2capture liefert rohe Bytes."""
    if kind == "v4l2":
        _select.select((cap,), (), ())
        return cap.read_and_queue()

    # cv2-Fallback: BGR-Frame → JPEG (Re-Encoding unvermeidlich)
    import cv2
    ret, frame = cap.read()
    if not ret:
        raise RuntimeError("cv2: Frame-Lesen fehlgeschlagen")
    _, jpeg = cv2.imencode(".jpg", frame)
    return jpeg.tobytes()


def _close_device_blocking(kind: str, cap) -> None:
    if kind == "v4l2":
        cap.close()
    else:
        cap.release()


# ---------------------------------------------------------------------------
# Capture-Loop (asyncio.Task)
# ---------------------------------------------------------------------------

async def _capture_loop(app: web.Application) -> None:
    """Liest dauerhaft Frames und verteilt sie an alle eingetragenen Subscriber."""
    stream_cfg = app["config"].get("stream", {})
    device = stream_cfg.get("device", "/dev/video0")
    width = stream_cfg.get("width", 640)
    height = stream_cfg.get("height", 480)

    loop = asyncio.get_event_loop()

    print(f"[STREAM] Öffne {device} …")
    try:
        kind, cap = await loop.run_in_executor(
            None, _open_device_blocking, device, width, height
        )
    except Exception as e:
        print(f"[STREAM] FEHLER beim Öffnen: {e}")
        return

    print("[STREAM] Capture-Loop aktiv.")
    try:
        while True:
            if not _subscribers:
                await asyncio.sleep(0.05)
                continue

            try:
                jpeg = await loop.run_in_executor(None, _read_frame_blocking, kind, cap)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[STREAM] Frame-Fehler: {e}")
                await asyncio.sleep(0.5)
                continue

            for q in list(_subscribers):
                try:
                    q.put_nowait(jpeg)
                except asyncio.QueueFull:
                    pass  # Langsamer Client: Frame verwerfen, Verbindung behalten
    finally:
        await loop.run_in_executor(None, _close_device_blocking, kind, cap)
        print("[STREAM] Capture-Loop beendet.")


async def start_capture(app: web.Application) -> None:
    global _capture_task
    _capture_task = asyncio.create_task(_capture_loop(app))
    print("[STREAM] Capture-Task gestartet.")


async def stop_capture(app: web.Application) -> None:
    global _capture_task
    if _capture_task and not _capture_task.done():
        _capture_task.cancel()
        try:
            await _capture_task
        except asyncio.CancelledError:
            pass
    print("[STREAM] Capture-Task gestoppt.")


# ---------------------------------------------------------------------------
# HTTP-Handler
# ---------------------------------------------------------------------------

async def stream_handler(request: web.Request) -> web.StreamResponse:
    """GET /stream?token=<session_token> → MJPEG-Multipart-Stream."""
    if not await _validate_token(request):
        raise web.HTTPUnauthorized(reason="Ungültiger oder fehlender Stream-Token")

    response = web.StreamResponse(
        headers={
            "Content-Type": "multipart/x-mixed-replace; boundary=frame",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
    await response.prepare(request)

    queue: asyncio.Queue = asyncio.Queue(maxsize=2)
    _subscribers.append(queue)
    print(f"[STREAM] Neuer Client: {request.remote} (gesamt: {len(_subscribers)})")

    try:
        while True:
            jpeg = await asyncio.wait_for(queue.get(), timeout=10.0)
            header = (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n"
                b"\r\n"
            )
            await response.write(header + jpeg + b"\r\n")
    except asyncio.TimeoutError:
        print(f"[STREAM] Client {request.remote}: Timeout (kein Frame), trenne.")
    except ConnectionResetError:
        print(f"[STREAM] Client {request.remote}: Verbindung unterbrochen.")
    except asyncio.CancelledError:
        pass
    finally:
        if queue in _subscribers:
            _subscribers.remove(queue)
        print(f"[STREAM] Client {request.remote} getrennt (verbleibend: {len(_subscribers)})")

    return response
