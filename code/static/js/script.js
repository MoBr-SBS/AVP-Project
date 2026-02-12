// --- GLOBALE VARIABLEN ---
const host = window.location.hostname;
const port = window.location.port;
let currentPan = 90;
let currentTilt = 90;
let isLoggedIn = false;
let currentLoggedInUser = "";
let userRole = 'user';
let lastSend = 0;
// --- AVP VARIABLEN ---
let xrSession = null;
let initialYaw = null;
let initialPitch = null;
let gl = null;
let videoTexture = null;
let webrtcPeer = null;


const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
const ws = new WebSocket(`${protocol}://${host}:${port}/ws`);

// --- WEBSOCKET LOGIK ---
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.user) {
        currentLoggedInUser = data.user;
    }

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
    else if (data.type === 'user_list') {
        renderUserList(data.users);
    }
    else if (data.type === 'admin_action_success') {
        alert(data.message);
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

    // NEU: Wenn Admin, zeige Verwaltungs-Bereich und lade User
    if (userRole === 'admin') {
        document.getElementById('adminUserMgmt').style.display = 'block';
        ws.send(JSON.stringify({ type: 'get_users' }));
    } else {
        document.getElementById('adminUserMgmt').style.display = 'none';
    }
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

function renderUserList(users) {
    const container = document.getElementById('userListContainer');
    container.innerHTML = ''; // Liste leeren

    // 1. Bestehende User auflisten
    users.forEach(u => {
        const row = document.createElement('div');
        row.style = "display: flex; align-items: center; gap: 10px; background: #2a2a2a; padding: 10px; margin-bottom: 5px; border-radius: 5px;";

        // Name
        const nameLabel = document.createElement('span');
        nameLabel.innerText = u.name;
        nameLabel.style = "flex: 1; font-weight: bold;";

        // PW Reset
        const pwInput = document.createElement('input');
        pwInput.type = "password";
        pwInput.placeholder = "Reset PW";
        pwInput.id = `pw-reset-${u.name}`;
        pwInput.style = "width: 100px; padding: 5px; margin: 0;";

        // Admin Checkbox
        const roleLabel = document.createElement('label');
        roleLabel.style = "display: flex; align-items: center; gap: 5px; font-size: 0.8rem; cursor: pointer;";
        const roleCheck = document.createElement('input');
        roleCheck.type = "checkbox";
        roleCheck.id = `role-check-${u.name}`;
        if (u.role === 'admin') roleCheck.checked = true;
        roleLabel.appendChild(roleCheck);
        roleLabel.appendChild(document.createTextNode("Admin"));

        // Save Button
        const saveBtn = document.createElement('button');
        saveBtn.innerText = "💾";
        saveBtn.title = "Änderungen speichern";
        saveBtn.style = "width: auto; padding: 5px 10px; background: #007bff; margin: 0;";
        saveBtn.onclick = () => submitUserUpdate(u.name);

        row.appendChild(nameLabel);
        row.appendChild(pwInput);
        row.appendChild(roleLabel);
        row.appendChild(saveBtn);
        container.appendChild(row);

        const delBtn = document.createElement('button');
        delBtn.innerText = "🗑️";
        delBtn.title = "Löschen";

        // Delete Button
        if (u.name === currentLoggedInUser) {
            // Button ausgrauen und deaktivieren
            delBtn.style = "width: auto; padding: 5px 10px; background: #555; margin: 0; margin-left: 5px; cursor: not-allowed; opacity: 0.5;";
            delBtn.disabled = true;
            delBtn.title = "Du kannst dich nicht selbst löschen";
        } else {
            // Normaler roter Button
            delBtn.style = "width: auto; padding: 5px 10px; background: #dc3545; margin: 0; margin-left: 5px;";
            delBtn.onclick = () => deleteUser(u.name);
        }

        row.appendChild(delBtn);
    });

    // 2. Box für NEUEN User (ganz unten)
    const newRow = document.createElement('div');
    // Etwas anderes Styling (Dashed Border), damit es sich abhebt
    newRow.style = "display: flex; align-items: center; gap: 10px; background: #222; padding: 10px; margin-top: 20px; border: 1px dashed #666; border-radius: 5px;";

    const newNameInput = document.createElement('input');
    newNameInput.type = "text";
    newNameInput.placeholder = "Neuer Username";
    newNameInput.id = "new-user-name";
    newNameInput.style = "flex: 1; padding: 5px; margin: 0; background: #333; color: #fff; border: 1px solid #555;";

    const newPassInput = document.createElement('input');
    newPassInput.type = "password";
    newPassInput.placeholder = "Passwort";
    newPassInput.id = "new-user-pass";
    newPassInput.style = "width: 100px; padding: 5px; margin: 0; background: #333; color: #fff; border: 1px solid #555;";

    const newRoleLabel = document.createElement('label');
    newRoleLabel.style = "display: flex; align-items: center; gap: 5px; font-size: 0.8rem; cursor: pointer;";
    const newRoleCheck = document.createElement('input');
    newRoleCheck.type = "checkbox";
    newRoleCheck.id = "new-user-admin";
    newRoleLabel.appendChild(newRoleCheck);
    newRoleLabel.appendChild(document.createTextNode("Admin"));

    const addBtn = document.createElement('button');
    addBtn.innerText = "➕";
    addBtn.title = "User anlegen";
    addBtn.style = "width: auto; padding: 5px 10px; background: #28a745; margin: 0;"; // Grün
    addBtn.onclick = createNewUser;

    newRow.appendChild(newNameInput);
    newRow.appendChild(newPassInput);
    newRow.appendChild(newRoleLabel);
    newRow.appendChild(addBtn);

    container.appendChild(newRow);
}

function createNewUser() {
    const name = document.getElementById('new-user-name').value;
    const pass = document.getElementById('new-user-pass').value;
    const isAdmin = document.getElementById('new-user-admin').checked;

    if (!name || !pass) {
        alert("Bitte Username und Passwort für den neuen Nutzer eingeben!");
        return;
    }

    ws.send(JSON.stringify({
        type: 'admin_create_user',
        username: name,
        password: pass,
        is_admin: isAdmin
    }));
}

function changePassword() {
    const oldPass = document.getElementById('oldPass').value;
    const newPass = document.getElementById('newPass').value;

    if(!oldPass || !newPass) {
        alert("Bitte fülle beide Felder aus!");
        return;
    }

    ws.send(JSON.stringify({
        type: 'change_password',
        old: oldPass,
        new: newPass
    }));
}

// 2. Admin: User aktualisieren (wird vom Speicher-Button in der Liste aufgerufen)
function submitUserUpdate(username) {
    const newPassInput = document.getElementById(`pw-reset-${username}`);
    const roleCheck = document.getElementById(`role-check-${username}`);

    if(!newPassInput || !roleCheck) return;

    const newPass = newPassInput.value;
    const isAdmin = roleCheck.checked;

    ws.send(JSON.stringify({
        type: 'admin_update_user',
        target_user: username,
        new_pass: newPass, // Wenn leer, wird PW vom Server ignoriert
        is_admin: isAdmin
    }));
}

function deleteUser(username) {
    // Sicherheitsabfrage im Browser
    if (confirm(`Möchtest du den Benutzer '${username}' wirklich endgültig löschen?`)) {
        ws.send(JSON.stringify({
            type: 'admin_delete_user',
            target_user: username
        }));
    }
}

function triggerSystem(action) {
    let text = "";
    if (action === 'restart_code') text = "Soll der Robot-Server neu gestartet werden?";
    if (action === 'reboot') text = "Soll der ganze Raspberry Pi neu gestartet werden?";
    if (action === 'shutdown') text = "Soll der Raspberry Pi wirklich herunterfahren?";

    if (confirm(text)) {
        ws.send(JSON.stringify({
            type: 'system_control',
            command: action
        }));

        // Settings schließen, da die Verbindung gleich weg ist
        if (action !== 'restart_code') {
            closeSettings();
            alert("Befehl gesendet. Verbindung wird getrennt.");
        }
    }
}

async function connectWebRTC(videoElement) {
    // 1. PeerConnection erstellen
    const pc = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
    });

    // 2. Transceiver hinzufügen (wir wollen nur Video empfangen)
    pc.addTransceiver('video', { direction: 'recvonly' });

    // 3. Wenn ein Track (Stream) ankommt, an das Video-Element binden
    pc.ontrack = (event) => {
        if (event.streams && event.streams[0]) {
            videoElement.srcObject = event.streams[0];
            // Sicherstellen, dass das Video abspielt (wichtig für WebGL Textur!)
            videoElement.play().catch(e => console.error("Autoplay Fehler:", e));
        }
    };

    // 4. Offer erstellen
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    // 5. Offer an go2rtc senden und Answer erhalten
    // WICHTIG: Port 1985 ist in deiner go2rtc.yaml für HTTPS konfiguriert
    const go2rtcUrl = `https://${window.location.hostname}:1985/api/webrtc?src=cam`;

    try {
        const response = await fetch(go2rtcUrl, {
            method: 'POST',
            body: offer.sdp // go2rtc erwartet puren SDP String im Body
        });

        if (!response.ok) throw new Error("Go2RTC Antwort nicht OK");

        const answerSdp = await response.text();

        // 6. Remote Description (Answer) setzen
        await pc.setRemoteDescription({
            type: 'answer',
            sdp: answerSdp
        });

        console.log("WebRTC Verbindung erfolgreich ausgehandelt.");

        // Return pc, falls wir die Verbindung später schließen wollen (z.B. bei closeAVP)
        return pc;

    } catch (e) {
        console.error("WebRTC Fehler:", e);
        alert("Konnte WebRTC Stream nicht starten: " + e.message);
    }
    return null;
}

function openAVPSettings() {
    if(!isLoggedIn) return;
    document.getElementById('avpOverlay').style.display = 'flex';
}

function closeAVP() {
    document.getElementById('avpOverlay').style.display = 'none';

    if (xrSession) {
        xrSession.end();
        xrSession = null;
    }

    // --- NEU: WebRTC aufräumen ---
    if (webrtcPeer) {
        webrtcPeer.close();
        webrtcPeer = null;
    }

    // Video stoppen und Quelle entfernen
    const video = document.getElementById('xrVideoSource');
    video.srcObject = null;
    video.src = "";
    // -----------------------------
}

async function startAVPSession() {
    // 1. DIESE ZEILEN HABEN GEFEHLT: Elemente aus dem HTML holen
    const status = document.getElementById('avpStatus');
    const canvas = document.getElementById('xrCanvas');
    const video = document.getElementById('xrVideoSource');

    if (!status || !canvas || !video) {
        console.error("Kritischer Fehler: HTML Elemente nicht gefunden!");
        return;
    }

    // 2. WebRTC Verbindung starten
    status.innerText = "Verbinde WebRTC...";

    // Wir starten WebRTC, aber warten nicht zwingend, bis es fertig ist,
    // damit die XR-Session (der Klick) nicht "abläuft" (Timeout).
    // Das Video bleibt schwarz, bis der Stream da ist.
    connectWebRTC(video).then(pc => {
        webrtcPeer = pc;
        console.log("WebRTC verbunden innerhalb der Session");
    });

    try {
        // 3. WebGL Kontext initialisieren
        gl = canvas.getContext('webgl', { xrCompatible: true });
        if (!gl) throw new Error("WebGL nicht unterstützt");

        // SHADER SETUP (Vertex Shader)
        const vs = `
            attribute vec3 pos; 
            attribute vec2 uv; 
            varying vec2 vUv;
            uniform mat4 uProjectionMatrix;
            uniform mat4 uModelViewMatrix;
            void main() { 
                vUv = uv; 
                gl_Position = uProjectionMatrix * uModelViewMatrix * vec4(pos, 1.0); 
            }
        `;

        // SHADER SETUP (Fragment Shader)
        const fs = `
            precision mediump float; 
            uniform sampler2D tex; 
            varying vec2 vUv; 
            void main() { 
                gl_FragColor = texture2D(tex, vUv); 
            }
        `;

        const program = createProgram(gl, vs, fs);
        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
            const info = gl.getProgramInfoLog(program);
            throw new Error("Shader-Link-Fehler: " + info);
        }

        const loc = {
            pos: gl.getAttribLocation(program, "pos"),
            uv: gl.getAttribLocation(program, "uv"),
            proj: gl.getUniformLocation(program, "uProjectionMatrix"),
            view: gl.getUniformLocation(program, "uModelViewMatrix")
        };

        // GEOMETRIE (Leinwand im Raum)
        const buffer = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        // Z = -1.5 schiebt das Bild 1.5 Meter weg
        const w = 1.6, h = 0.9, z = -1.5;
        const vertices = new Float32Array([
            -w/2, -h/2, z,  0, 0,
             w/2, -h/2, z,  1, 0,
            -w/2,  h/2, z,  0, 1,
             w/2,  h/2, z,  1, 1
        ]);
        gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);

        // TEXTUR ERSTELLEN
        videoTexture = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, videoTexture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

        // Initiales schwarzes Pixel, damit WebGL nicht meckert, bevor Video da ist
        const pixel = new Uint8Array([0, 0, 0]);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, 1, 1, 0, gl.RGB, gl.UNSIGNED_BYTE, pixel);

        // 4. XR Session anfragen
        const session = await navigator.xr.requestSession('immersive-vr', {
            requiredFeatures: ['local']
        });
        xrSession = session;

        const layer = new XRWebGLLayer(session, gl);
        session.updateRenderState({ baseLayer: layer });
        const refSpaceLocal = await session.requestReferenceSpace('local');
        const refSpaceViewer = await session.requestReferenceSpace('viewer');

        // Video abspielen (falls Autoplay blockiert war)
        video.play().catch(e => console.log("Warte auf Stream...", e));

        // RENDER LOOP
        const onFrame = (time, frame) => {
            if (!xrSession) return;

            const poseViewer = frame.getViewerPose(refSpaceViewer);
            const poseLocal = frame.getViewerPose(refSpaceLocal);

            if (poseViewer) {
                const layer = xrSession.renderState.baseLayer;
                gl.bindFramebuffer(gl.FRAMEBUFFER, layer.framebuffer);

                gl.clearColor(0.1, 0.1, 0.1, 1.0); // Dunkelgrauer Hintergrund
                gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

                // Video-Textur Update (nur wenn Video läuft und Daten hat)
                if (video.readyState >= 2 && video.videoWidth > 0) {
                    gl.bindTexture(gl.TEXTURE_2D, videoTexture);
                    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
                    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, video);
                }

                gl.useProgram(program);
                gl.bindBuffer(gl.ARRAY_BUFFER, buffer);

                gl.enableVertexAttribArray(loc.pos);
                gl.vertexAttribPointer(loc.pos, 3, gl.FLOAT, false, 20, 0);
                gl.enableVertexAttribArray(loc.uv);
                gl.vertexAttribPointer(loc.uv, 2, gl.FLOAT, false, 20, 12);

                for (const view of poseViewer.views) {
                    const viewport = layer.getViewport(view);
                    gl.viewport(viewport.x, viewport.y, viewport.width, viewport.height);

                    gl.uniformMatrix4fv(loc.proj, false, view.projectionMatrix);
                    gl.uniformMatrix4fv(loc.view, false, view.transform.inverse.matrix);

                    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
                }
            }

            if (poseLocal) {
                processRobotControl(poseLocal);
            }

            xrSession.requestAnimationFrame(onFrame);
        };

        xrSession.requestAnimationFrame(onFrame);
        status.innerText = "Immersiv aktiv! (WebRTC lädt...)";

    } catch (e) {
        status.innerText = "XR Fehler: " + e.message;
        console.error(e);
        alert("Fehler: " + e.message);
    }
}

function createProgram(gl, vsSource, fsSource) {
    const vShader = gl.createShader(gl.VERTEX_SHADER);
    gl.shaderSource(vShader, vsSource); gl.compileShader(vShader);
    const fShader = gl.createShader(gl.FRAGMENT_SHADER);
    gl.shaderSource(fShader, fsSource); gl.compileShader(fShader);
    const prog = gl.createProgram();
    gl.attachShader(prog, vShader); gl.attachShader(prog, fShader);
    gl.linkProgram(prog); return prog;
}

function processRobotControl(pose) {
    const matrix = pose.transform.matrix;
    let yaw = Math.atan2(-matrix[8], matrix[10]) * (180 / Math.PI);
    let pitch = Math.asin(matrix[9]) * (180 / Math.PI);

    if (initialYaw === null) {
        initialYaw = yaw;
        initialPitch = pitch;
    }

    let targetPan = 90 - (yaw - initialYaw);
    let targetTilt = 90 - (pitch - initialPitch);
    sendAngles(targetPan, targetTilt);
}

