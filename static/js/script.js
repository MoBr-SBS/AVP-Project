// --- GLOBALE VARIABLEN & INITIALISIERUNG ---
const host = window.location.hostname;
const port = window.location.port;
let currentPan = 90;
let currentTilt = 90;
let isLoggedIn = false;
let lastSend = 0;

// WebSocket Verbindung aufbauen
const ws = new WebSocket(`ws://${host}:${port}/ws`);
const statusEl = document.getElementById('connectionStatus');

// --- UI FUNKTIONEN (Header & Overlays) ---
function openSettings() {
    if(!isLoggedIn) return;
    document.getElementById('settingsOverlay').style.display = 'flex';
    // Felder zurücksetzen
    document.getElementById('oldPass').value = '';
    document.getElementById('newPass').value = '';
    const errBox = document.getElementById('settingsError');
    if(errBox) errBox.style.display = 'none';
}

function closeSettings() {
    document.getElementById('settingsOverlay').style.display = 'none';
}

// --- AUTHENTIFIZIERUNG ---
function performLogin() {
    const u = document.getElementById('userInput').value;
    const p = document.getElementById('passInput').value;
    if(ws.readyState === WebSocket.OPEN) {
        // Login-Daten als JSON senden
        ws.send(JSON.stringify({ type: 'login', user: u, pass: p }));
    }
}

function changePassword() {
    const oldP = document.getElementById('oldPass').value;
    const newP = document.getElementById('newPass').value;
    const repP = document.getElementById('newPassRepeat')?.value || newP;

    if (!oldP || !newP || newP !== repP || newP.length < 4) {
        alert("Eingabe ungültig (Min. 4 Zeichen)");
        return;
    }
    // Passwort-Änderung an Server senden
    ws.send(JSON.stringify({ type: 'change_password', old_pass: oldP, new_pass: newP }));
}

// --- WEBSOCKET EVENT HANDLING ---
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.type === 'login_success') {
        document.getElementById('loginOverlay').style.display = 'none';
        if (data.stream_url) document.getElementById('camStream').src = data.stream_url;
        document.getElementById('displayUser').innerText = data.user;
        isLoggedIn = true;
        statusEl.innerText = "Verbunden";
        statusEl.style.color = "#0f0";
    } else if (data.type === 'login_fail') {
        alert(data.message || "Login fehlgeschlagen");
    } else if (data.type === 'pw_change_success') {
        alert("Passwort erfolgreich geändert!");
        closeSettings();
    }
};

ws.onclose = () => {
    statusEl.innerText = "Getrennt";
    statusEl.style.color = "#f00";
    document.getElementById('loginOverlay').style.display = 'flex';
    isLoggedIn = false;
};

// --- STEUERUNGS-LOGIK ---

function sendAngles(pan, tilt) {
    if (!isLoggedIn) return;

    // Werte auf 0-180 Grad begrenzen
    pan = Math.max(0, Math.min(180, pan));
    tilt = Math.max(0, Math.min(180, tilt));

    currentPan = pan;
    currentTilt = tilt;

    const now = Date.now();
    if (now - lastSend < 40) return; // Rate Limiting (~25 FPS)
    lastSend = now;

    if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ pan, tilt }));
    }
}

// Maus-Steuerung im Video-Bereich
const mouseZone = document.getElementById('mouseZone');
if(mouseZone) {
    mouseZone.addEventListener('mousemove', (e) => {
        if (e.buttons !== 1) return;
        const rect = mouseZone.getBoundingClientRect();
        const p = 180 - ((e.clientX - rect.left) / rect.width * 180);
        const t = 180 - ((e.clientY - rect.top) / rect.height * 180);
        sendAngles(p, t);
    });
}

// Tastatur & Joystick Loop
const knob = document.getElementById('joystick-knob');
const joystickWrapper = document.getElementById('joystick-wrapper');
let joyX = 0, joyY = 0;
const keyState = {};

setInterval(() => {
    if (!isLoggedIn) return;
    if (Object.values(keyState).some(x => x) || joyX !== 0 || joyY !== 0) {
        // Bewegung berechnen (4 Grad Schritte)
        sendAngles(currentPan + (joyX * 4 * -1), currentTilt + (joyY * 4 * -1));
    }
}, 50);

// Tastatur Events
window.addEventListener('keydown', (e) => {
    if(document.activeElement.tagName === 'INPUT') return;
    if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)) {
        keyState[e.key] = true;
        updateFromKeys();
    }
});

window.addEventListener('keyup', (e) => {
    if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)) {
        keyState[e.key] = false;
        updateFromKeys();
    }
});

function updateFromKeys() {
    joyX = (keyState.ArrowRight ? 1 : 0) - (keyState.ArrowLeft ? 1 : 0);
    joyY = (keyState.ArrowDown ? 1 : 0) - (keyState.ArrowUp ? 1 : 0);
    if(knob) knob.style.transform = `translate(calc(-50% + ${joyX*35}px), calc(-50% + ${joyY*35}px))`;
}