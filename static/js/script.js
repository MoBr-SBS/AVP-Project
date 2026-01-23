// --- GLOBALE VARIABLEN ---
const host = window.location.hostname;
const port = window.location.port;
let currentPan = 90;
let currentTilt = 90;
let isLoggedIn = false;
let userRole = 'user';
let lastSend = 0;

const ws = new WebSocket(`ws://${host}:${port}/ws`);

// --- WEBSOCKET LOGIK ---
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.type === 'login_success') {
        isLoggedIn = true;
        userRole = data.role;
        document.getElementById('loginOverlay').style.display = 'none';
        document.getElementById('displayUser').innerText = `${data.user} (${userRole})`;
        document.getElementById('connectionStatus').innerText = "Verbunden";
        document.getElementById('connectionStatus').style.color = "#00ff00";
        document.getElementById('camStream').src = data.stream_url;

        if (userRole === 'admin') {
            document.getElementById('btn-system').style.display = 'inline-block';
        } else {
            document.getElementById('btn-system').style.display = 'none';
        }
    }
    else if (data.type === 'status') {
        // WICHTIG: parseFloat erzwingt, dass es eine Zahl ist!
        currentPan = parseFloat(data.pan);
        currentTilt = parseFloat(data.tilt);
    }
    else if (data.type === 'config_data') {
        fillAdminFields(data.config);
    }
    else if (data.type === 'config_update_success') {
        alert("Konfiguration gespeichert!");
    }
};

// --- STEUERUNGS FUNKTIONEN ---
function sendAngles(p, t) {
    const now = Date.now();
    if (now - lastSend < 50) return; // Rate Limiting
    lastSend = now;

    if (ws.readyState === WebSocket.OPEN && isLoggedIn) {
        ws.send(JSON.stringify({ type: 'move', pan: Math.round(p), tilt: Math.round(t) }));
    }
}

// Maus-Steuerung
const mouseZone = document.getElementById('mouseZone');
if (mouseZone) {
    mouseZone.addEventListener('mousemove', (e) => {
        if (e.buttons !== 1) return;
        const rect = mouseZone.getBoundingClientRect();
        const p = 180 - ((e.clientX - rect.left) / rect.width * 180);
        const t = 180 - ((e.clientY - rect.top) / rect.height * 180);
        sendAngles(p, t);
    });
}

// Tastatur-Steuerung Zustand
const keyState = {};
window.addEventListener('keydown', (e) => {
    if(document.activeElement.tagName === 'INPUT') return;
    keyState[e.key] = true;
});
window.addEventListener('keyup', (e) => keyState[e.key] = false);

// Der Steuerungs-Loop (alle 50ms)
setInterval(() => {
    if (!isLoggedIn) return;

    let moveStep = 5;
    let changed = false;

    // Wir arbeiten mit Kopien der aktuellen Werte
    let targetPan = currentPan;
    let targetTilt = currentTilt;

    if (keyState['ArrowLeft'])  { targetPan += moveStep; changed = true; }
    if (keyState['ArrowRight']) { targetPan -= moveStep; changed = true; }
    if (keyState['ArrowUp'])    { targetTilt += moveStep; changed = true; }
    if (keyState['ArrowDown'])  { targetTilt -= moveStep; changed = true; }

    if (changed) {
        sendAngles(targetPan, targetTilt);
    }
}, 50);

// --- ADMIN & SETTINGS FUNKTIONEN ---
function openUserSettings() {
    if(!isLoggedIn) return;
    document.getElementById('settingsOverlay').style.display = 'flex';
    document.getElementById('userSettingsArea').style.display = 'block';
    document.getElementById('adminArea').style.display = 'none';
}

function openSystemSettings() {
    if(!isLoggedIn || userRole !== 'admin') return;

    document.getElementById('settingsOverlay').style.display = 'flex';

    // User Bereich AUS, Admin Bereich AN
    document.getElementById('userSettingsArea').style.display = 'none';
    document.getElementById('adminArea').style.display = 'block';

    // Config vom Server laden
    ws.send(JSON.stringify({ type: 'get_config' }));
}

function closeSettings() {
    document.getElementById('settingsOverlay').style.display = 'none';
}

function fillAdminFields(config) {
    // Hardware & Reverse Checkboxen
    document.getElementById('cfg-pan-ch').value = config.hardware.pan.channel;
    document.getElementById('cfg-pan-rev').checked = config.hardware.pan.reverse;
    document.getElementById('cfg-pan-min').value = config.hardware.pan.min_angle;
    document.getElementById('cfg-pan-max').value = config.hardware.pan.max_angle;

    document.getElementById('cfg-tilt-ch').value = config.hardware.tilt.channel;
    document.getElementById('cfg-tilt-rev').checked = config.hardware.tilt.reverse;
    document.getElementById('cfg-tilt-min').value = config.hardware.tilt.min_angle;
    document.getElementById('cfg-tilt-max').value = config.hardware.tilt.max_angle;

    // OLED & Netz
    document.getElementById('cfg-oled-addr').value = config.oled.address;
    document.getElementById('cfg-oled-clk').value = config.oled.pin_clk;
    document.getElementById('cfg-oled-dt').value = config.oled.pin_dt;
    document.getElementById('cfg-oled-sw').value = config.oled.pin_sw;

    document.getElementById('cfg-net-port').value = config.network.port;
    document.getElementById('cfg-sec-token').value = config.security.cam_token;
}

function saveAdminConfig() {
    const updatedConfig = {
        hardware: {
            pan: {
                channel: parseInt(document.getElementById('cfg-pan-ch').value),
                reverse: document.getElementById('cfg-pan-rev').checked,
                min_angle: parseInt(document.getElementById('cfg-pan-min').value),
                max_angle: parseInt(document.getElementById('cfg-pan-max').value)
            },
            tilt: {
                channel: parseInt(document.getElementById('cfg-tilt-ch').value),
                reverse: document.getElementById('cfg-tilt-rev').checked,
                min_angle: parseInt(document.getElementById('cfg-tilt-min').value),
                max_angle: parseInt(document.getElementById('cfg-tilt-max').value)
            }
        },
        oled: {
            address: document.getElementById('cfg-oled-addr').value,
            pin_clk: parseInt(document.getElementById('cfg-oled-clk').value),
            // KORREKTUR: Werte aus Inputs lesen, nicht hardcoden!
            pin_dt: parseInt(document.getElementById('cfg-oled-dt').value),
            pin_sw: parseInt(document.getElementById('cfg-oled-sw').value),
            bounce_time: 0.3
        },
        network: { host: "0.0.0.0", port: parseInt(document.getElementById('cfg-net-port').value) },
        security: { cam_token: document.getElementById('cfg-sec-token').value },
        paths: { user_db: "users.json", shm_file: "/dev/shm/robot_status.json" }
    };

    ws.send(JSON.stringify({ type: 'update_config', config: updatedConfig }));
}

function performLogin() {
    const u = document.getElementById('userInput').value;
    const p = document.getElementById('passInput').value;
    ws.send(JSON.stringify({ type: 'login', user: u, pass: p }));
}