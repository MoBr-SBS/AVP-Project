// --- GLOBALE VARIABLEN ---
const host = window.location.hostname;
const port = window.location.port;
let currentPan = 90;
let currentTilt = 90;
let isLoggedIn = false;
let currentLoggedInUser = "";
let userRole = 'user';
let lastSend = 0;
let sessionToken = null;
let ws = null;
let youHaveControl = false;
// --- AVP VARIABLEN ---
let xrSession = null;
let initialYaw = null;
let initialPitch = null;
let gl = null;
let videoTexture = null;
let webrtcPeer = null;


// --- STATUS HELPER ---
function setStatus(connected) {
    const dot  = document.getElementById('statusDot');
    const text = document.getElementById('connectionStatus');
    if (connected) {
        dot.classList.add('connected');
        text.textContent = 'Connected';
    } else {
        dot.classList.remove('connected');
        text.textContent = 'Disconnected';
    }
}

// Enter key triggers login
document.addEventListener('DOMContentLoaded', () => {
    ['userInput', 'passInput'].forEach(id => {
        document.getElementById(id)?.addEventListener('keydown', e => {
            if (e.key === 'Enter') performLogin();
        });
    });
});

// --- WEBSOCKET MESSAGE HANDLER ---
function handleWsMessage(event) {
    const data = JSON.parse(event.data);

    if (data.user) {
        currentLoggedInUser = data.user;
    }

    if (data.type === 'control_state') {
        updateControlState(data);
    }
    else if (data.type === 'status') {
        currentPan = parseFloat(data.pan);
        currentTilt = parseFloat(data.tilt);
    }
    else if (data.type === 'config_data') {
        fillAdminFields(data.config);
    }
    else if (data.type === 'config_update_success') {
        alert("Configuration saved!");
    }
    else if (data.type === 'user_list') {
        renderUserList(data.users);
    }
    else if (data.type === 'admin_action_success') {
        alert(data.message);
    }
}

// --- CONTROL FUNCTIONS ---
function sendAngles(p, t) {
    const now = Date.now();
    if (now - lastSend < 50) return; // Rate Limiting
    lastSend = now;

    if (ws && ws.readyState === WebSocket.OPEN && isLoggedIn && youHaveControl) {
        ws.send(JSON.stringify({ type: 'move', pan: Math.round(p), tilt: Math.round(t) }));
    }
}

// Mouse-Control
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

// Arrow-Key-Control
const keyState = {};
window.addEventListener('keydown', (e) => {
    if(document.activeElement.tagName === 'INPUT') return;
    keyState[e.key] = true;
});
window.addEventListener('keyup', (e) => keyState[e.key] = false);

setInterval(() => {
    if (!isLoggedIn) return;

    let moveStep = 5;
    let changed = false;

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

// --- ADMIN & SETTINGS FUNCTIONS ---
function openUserSettings() {
    if(!isLoggedIn) return;
    document.getElementById('settingsOverlay').style.display = 'flex';
    document.getElementById('userSettingsArea').style.display = 'block';
    document.getElementById('adminArea').style.display = 'none';

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

    document.getElementById('userSettingsArea').style.display = 'none';
    document.getElementById('adminArea').style.display = 'block';

    ws.send(JSON.stringify({ type: 'get_config' }));
}

function closeSettings() {
    document.getElementById('settingsOverlay').style.display = 'none';
}

function fillAdminFields(config) {
    // Hardware & Reverse Checkbox
    document.getElementById('cfg-pan-ch').value = config.hardware.pan.channel;
    document.getElementById('cfg-pan-rev').checked = config.hardware.pan.reverse;
    document.getElementById('cfg-pan-min').value = config.hardware.pan.min_angle;
    document.getElementById('cfg-pan-max').value = config.hardware.pan.max_angle;

    document.getElementById('cfg-tilt-ch').value = config.hardware.tilt.channel;
    document.getElementById('cfg-tilt-rev').checked = config.hardware.tilt.reverse;
    document.getElementById('cfg-tilt-min').value = config.hardware.tilt.min_angle;
    document.getElementById('cfg-tilt-max').value = config.hardware.tilt.max_angle;

    // OLED & Network
    document.getElementById('cfg-oled-addr').value = config.oled.address;
    document.getElementById('cfg-oled-clk').value = config.oled.pin_clk;
    document.getElementById('cfg-oled-dt').value = config.oled.pin_dt;
    document.getElementById('cfg-oled-sw').value = config.oled.pin_sw;

    document.getElementById('cfg-stream-width').value  = config.stream?.width  ?? 640;
    document.getElementById('cfg-stream-height').value = config.stream?.height ?? 480;
    document.getElementById('cfg-stream-device').value = config.stream?.device ?? '/dev/video0';

    document.getElementById('cfg-net-port').value = config.network.port;
    document.getElementById('cfg-auth-required').checked = config.auth?.required ?? true;
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
            pin_dt: parseInt(document.getElementById('cfg-oled-dt').value),
            pin_sw: parseInt(document.getElementById('cfg-oled-sw').value),
            bounce_time: 0.3
        },
        auth: { required: document.getElementById('cfg-auth-required').checked },
        stream: {
            device: document.getElementById('cfg-stream-device').value,
            width:  parseInt(document.getElementById('cfg-stream-width').value),
            height: parseInt(document.getElementById('cfg-stream-height').value),
        },
        network: { host: "0.0.0.0", port: parseInt(document.getElementById('cfg-net-port').value) },
        paths: { user_db: "users.json", shm_file: "/dev/shm/robot_status.json" }
    };

    ws.send(JSON.stringify({ type: 'update_config', config: updatedConfig }));
}

// --- CONTROL MANAGEMENT ---
function updateControlState(data) {
    youHaveControl = data.you_have_control;
    const label   = document.getElementById('controller-label');
    const btnClaim   = document.getElementById('btn-claim');
    const btnRelease = document.getElementById('btn-release');
    const btnForce   = document.getElementById('btn-force');

    if (!data.controller) {
        label.textContent = 'No active controller';
        label.style.color = '';
        btnClaim.style.display   = isLoggedIn ? '' : 'none';
        btnRelease.style.display = 'none';
        btnForce.style.display   = 'none';
    } else if (data.you_have_control) {
        label.textContent = 'You are controlling';
        label.style.color = '#22c55e';
        btnClaim.style.display   = 'none';
        btnRelease.style.display = '';
        btnForce.style.display   = 'none';
    } else {
        label.textContent = `${data.controller} is controlling`;
        label.style.color = '';
        btnClaim.style.display   = 'none';
        btnRelease.style.display = 'none';
        btnForce.style.display   = userRole === 'admin' ? '' : 'none';
    }
}

function claimControl() {
    if (ws && ws.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'claim_control' }));
}

function releaseControl() {
    if (ws && ws.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'release_control' }));
}

function forceControl() {
    if (ws && ws.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'force_take_control' }));
}

// --- LOGIN / LOGOUT ---
function connectWithToken(data) {
    sessionToken = data.token;
    isLoggedIn = true;
    userRole = data.role;
    currentLoggedInUser = data.user;

    const isGuest = data.user === 'Guest';

    document.getElementById('loginOverlay').style.display = 'none';
    document.getElementById('displayUser').innerText = `${data.user} (${data.role})`;
    setStatus(true);
    const camImg = document.getElementById('camStream');
    camImg.onload = function () {
        if (this.naturalWidth && this.naturalHeight) {
            document.querySelector('.video-container').style.aspectRatio =
                `${this.naturalWidth} / ${this.naturalHeight}`;
            this.onload = null;
        }
    };
    camImg.src = `/stream?token=${sessionToken}`;
    document.getElementById('btn-system').style.display  = userRole === 'admin' ? 'inline-block' : 'none';
    document.getElementById('btn-profile').style.display = isGuest ? 'none' : '';
    document.getElementById('btn-logout').textContent    = isGuest ? 'Admin Login' : 'Sign Out';

    const wsProto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${wsProto}://${host}:${port}/ws?token=${sessionToken}`);
    ws.onmessage = handleWsMessage;
    ws.onerror = (e) => console.error('WebSocket error:', e);
    ws.onclose = () => { isLoggedIn = false; setStatus(false); };
}

// Auto-login when auth is disabled (POST /login with no body returns 200)
window.addEventListener('load', async () => {
    try {
        const resp = await fetch('/login', { method: 'POST' });
        if (resp.ok) {
            const data = await resp.json();
            if (data.token) connectWithToken(data);
        }
    } catch (e) { /* auth required — login overlay stays visible */ }
});

async function performLogin() {
    const u = document.getElementById('userInput').value;
    const p = document.getElementById('passInput').value;

    let data;
    try {
        const resp = await fetch('/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user: u, pass: p })
        });
        data = await resp.json();
        if (!resp.ok) {
            alert(data.error || 'Login failed');
            return;
        }
    } catch (e) {
        alert('Connection error: ' + e.message);
        return;
    }

    connectWithToken(data);
}

async function performLogout() {
    if (sessionToken) {
        await fetch('/logout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: sessionToken })
        }).catch(() => {});
    }
    if (ws) {
        ws.close();
        ws = null;
    }
    sessionToken = null;
    isLoggedIn = false;
    userRole = 'user';
    currentLoggedInUser = '';
    youHaveControl = false;

    document.getElementById('camStream').src = '';
    setStatus(false);
    document.getElementById('displayUser').innerText = '—';
    document.getElementById('btn-system').style.display  = 'none';
    document.getElementById('btn-profile').style.display = '';
    document.getElementById('btn-logout').textContent    = 'Sign Out';
    document.getElementById('btn-claim').style.display   = 'none';
    document.getElementById('btn-release').style.display = 'none';
    document.getElementById('btn-force').style.display   = 'none';
    document.getElementById('controller-label').textContent = 'No active controller';
    document.getElementById('controller-label').style.color = '';
    document.getElementById('loginOverlay').style.display = 'flex';
    closeSettings();
}

function renderUserList(users) {
    const container = document.getElementById('userListContainer');
    container.innerHTML = '';

    users.forEach(u => {
        const isSelf = u.name === currentLoggedInUser;
        const initials = u.name.slice(0, 2).toUpperCase();
        const badgeClass = u.role === 'admin' ? 'badge-admin' : 'badge-user';

        const card = document.createElement('div');
        card.className = 'user-card';
        card.innerHTML = `
            <div class="user-avatar">${initials}</div>
            <span class="user-name">
                ${u.name}
                <span class="badge ${badgeClass}">${u.role}</span>
            </span>
            <div class="user-controls">
                <input type="password" id="pw-reset-${u.name}" placeholder="New password">
                <label class="admin-toggle">
                    <input type="checkbox" id="role-check-${u.name}" ${u.role === 'admin' ? 'checked' : ''}>
                    Admin
                </label>
                <button class="icon-btn save" title="Save" onclick="submitUserUpdate('${u.name}')">💾</button>
                <button class="icon-btn del" title="Delete" onclick="deleteUser('${u.name}')" ${isSelf ? 'disabled' : ''}>🗑</button>
            </div>
        `;
        container.appendChild(card);
    });

    // Add user row
    const addRow = document.createElement('div');
    addRow.className = 'add-user-row';
    addRow.innerHTML = `
        <input type="text" id="new-user-name" placeholder="Username">
        <input type="password" id="new-user-pass" placeholder="Password">
        <label class="admin-toggle">
            <input type="checkbox" id="new-user-admin"> Admin
        </label>
        <button class="btn-add" onclick="createNewUser()">+ Add</button>
    `;
    container.appendChild(addRow);
}

function createNewUser() {
    const name = document.getElementById('new-user-name').value;
    const pass = document.getElementById('new-user-pass').value;
    const isAdmin = document.getElementById('new-user-admin').checked;

    if (!name || !pass) {
        alert("Please enter username and password for the new user!");
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
        alert("Please fill out both fields!");
        return;
    }

    ws.send(JSON.stringify({
        type: 'change_password',
        old: oldPass,
        new: newPass
    }));
}

// 2. Admin: User Update
function submitUserUpdate(username) {
    const newPassInput = document.getElementById(`pw-reset-${username}`);
    const roleCheck = document.getElementById(`role-check-${username}`);

    if(!newPassInput || !roleCheck) return;

    const newPass = newPassInput.value;
    const isAdmin = roleCheck.checked;

    ws.send(JSON.stringify({
        type: 'admin_update_user',
        target_user: username,
        new_pass: newPass,
        is_admin: isAdmin
    }));
}

function deleteUser(username) {
    if (confirm(`Permanently delete user '${username}'?`)) {
        ws.send(JSON.stringify({
            type: 'admin_delete_user',
            target_user: username
        }));
    }
}

function triggerSystem(action) {
    let text = "";
    if (action === 'restart_code') text = "Restart the server code?";
    if (action === 'reboot')       text = "Reboot the Raspberry Pi?";
    if (action === 'shutdown')     text = "Shut down the Raspberry Pi?";

    if (confirm(text)) {
        ws.send(JSON.stringify({
            type: 'system_control',
            command: action
        }));

        if (action !== 'restart_code') {
            closeSettings();
            alert("Command sent. The connection will close.");
        }
    }
}

async function connectWebRTC(videoElement) {
    //PeerConnection (not needed)
    const pc = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
    });

    //Transceiver
    pc.addTransceiver('video', { direction: 'recvonly' });

    pc.ontrack = (event) => {
        if (event.streams && event.streams[0]) {
            videoElement.srcObject = event.streams[0];
            // Sicherstellen, dass das Video abspielt (wichtig für WebGL Textur!)
            videoElement.play().catch(e => console.error("Autoplay Fehler:", e));
        }
    };

    //Offer
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    const go2rtcUrl = `https://${window.location.hostname}:1985/api/webrtc?src=cam`;

    try {
        const response = await fetch(go2rtcUrl, {
            method: 'POST',
            body: offer.sdp
        });

        if (!response.ok) throw new Error("Go2RTC Antwort nicht OK");

        const answerSdp = await response.text();

        // Remote Description (Answer) setzen
        await pc.setRemoteDescription({
            type: 'answer',
            sdp: answerSdp
        });

        console.log("WebRTC Connection Successful.");

        return pc;

    } catch (e) {
        console.error("WebRTC Error:", e);
        alert("Couldn't start WebRTC Connection: " + e.message);
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

    // ---WebRTC cleanup ---
    if (webrtcPeer) {
        webrtcPeer.close();
        webrtcPeer = null;
    }

    const video = document.getElementById('xrVideoSource');
    video.srcObject = null;
    video.src = "";
}

async function startAVPSession() {
    const status = document.getElementById('avpStatus');
    const canvas = document.getElementById('xrCanvas');
    const video = document.getElementById('xrVideoSource');

    if (!status || !canvas || !video) {
        console.error("Critical Error: HTML Elements not found!");
        return;
    }

    // 2. WebRTC starting connection
    status.innerText = "Connecting WebRTC...";

    connectWebRTC(video).then(pc => {
        webrtcPeer = pc;
        console.log("WebRTC verbunden innerhalb der Session");
    });

    try {
        // 3. Initialize WebGL Context
        gl = canvas.getContext('webgl', { xrCompatible: true });
        if (!gl) throw new Error("WebGL not supported");

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
            throw new Error("Shader-Link-Error: " + info);
        }

        const loc = {
            pos: gl.getAttribLocation(program, "pos"),
            uv: gl.getAttribLocation(program, "uv"),
            proj: gl.getUniformLocation(program, "uProjectionMatrix"),
            view: gl.getUniformLocation(program, "uModelViewMatrix")
        };

        // GEOMETRY
        const buffer = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        // Z = -1.5 moves the image 1.5 meters away
        const w = 1.6, h = 0.9, z = -1.5;
        const vertices = new Float32Array([
            -w/2, -h/2, z,  0, 0,
             w/2, -h/2, z,  1, 0,
            -w/2,  h/2, z,  0, 1,
             w/2,  h/2, z,  1, 1
        ]);
        gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);

        // TEXTUR
        videoTexture = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, videoTexture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

        const pixel = new Uint8Array([0, 0, 0]);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, 1, 1, 0, gl.RGB, gl.UNSIGNED_BYTE, pixel);

        // 4. XR Session
        const session = await navigator.xr.requestSession('immersive-vr', {
            requiredFeatures: ['local']
        });
        xrSession = session;

        const layer = new XRWebGLLayer(session, gl);
        session.updateRenderState({ baseLayer: layer });
        const refSpaceLocal = await session.requestReferenceSpace('local');
        const refSpaceViewer = await session.requestReferenceSpace('viewer');

        // Play Video
        video.play().catch(e => console.log("Waiting for Stream...", e));

        // RENDER LOOP
        const onFrame = (time, frame) => {
            if (!xrSession) return;

            const poseViewer = frame.getViewerPose(refSpaceViewer);
            const poseLocal = frame.getViewerPose(refSpaceLocal);

            if (poseViewer) {
                const layer = xrSession.renderState.baseLayer;
                gl.bindFramebuffer(gl.FRAMEBUFFER, layer.framebuffer);

                gl.clearColor(0.1, 0.1, 0.1, 1.0);
                gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

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
        status.innerText = "Immersiv activ! (WebRTC loading...)";

    } catch (e) {
        status.innerText = "XR Error: " + e.message;
        console.error(e);
        alert("Error: " + e.message);
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
