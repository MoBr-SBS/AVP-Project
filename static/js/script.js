// --- GLOBALE VARIABLEN ---
const host = window.location.hostname;
const port = window.location.port;
let currentPan = 90;
let currentTilt = 90;
let isLoggedIn = false;
let userRole = 'user'; // NEU: Rolle speichern

const ws = new WebSocket(`ws://${host}:${port}/ws`);

// --- UI STEUERUNG ---
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.type === 'login_success') {
        isLoggedIn = true;
        userRole = data.role; // Rolle vom Server speichern

        document.getElementById('loginOverlay').style.display = 'none';
        document.getElementById('displayUser').innerText = `${data.user} (${userRole})`;
        document.getElementById('connectionStatus').innerText = "Verbunden";
        document.getElementById('connectionStatus').style.color = "#00ff00";

        // Kamera-Stream laden
        document.getElementById('camStream').src = data.stream_url;

        // UI basierend auf Rolle anpassen
        if (userRole === 'admin') {
            document.body.classList.add('is-admin');
            console.log("Admin-Rechte gewährt");
        }
    }

    if (data.type === 'login_fail') {
        alert("Login fehlgeschlagen: " + data.message);
    }

    if (data.type === 'pw_change_success') {
        alert("Passwort erfolgreich geändert!");
        closeSettings();
    }
};

// --- FUNKTIONEN ---
function performLogin() {
    const u = document.getElementById('userInput').value.trim();
    const p = document.getElementById('passInput').value.trim();
    if(ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'login', user: u, pass: p }));
    }
}

function changePassword() {
    const oldP = document.getElementById('oldPass').value;
    const newP = document.getElementById('newPass').value;
    if(newP.length < 4) {
        alert("Neues Passwort zu kurz!");
        return;
    }
    ws.send(JSON.stringify({
        type: 'change_password',
        old_pass: oldP,
        new_pass: newP
    }));
}

// Restliche Steuerungs-Logik (MouseZone, Joystick etc.) bleibt gleich...