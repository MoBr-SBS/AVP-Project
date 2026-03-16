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
        document.getElementById('connectionStatus').innerText = "Connected";
        document.getElementById('connectionStatus').style.color = "#00ff00";
        document.getElementById('camStream').src = data.stream_url;

        if (userRole === 'admin') {
            document.getElementById('btn-system').style.display = 'inline-block';
        } else {
            document.getElementById('btn-system').style.display = 'none';
        }
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
};

// --- CONTROL FUNCTIONS ---
function sendAngles(p, t) {
    const now = Date.now();
    if (now - lastSend < 50) return; // Rate Limiting
    lastSend = now;

    if (ws.readyState === WebSocket.OPEN && isLoggedIn) {
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
    container.innerHTML = '';

    // 1. List existing users
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
        saveBtn.title = "Save changes";
        saveBtn.style = "width: auto; padding: 5px 10px; background: #007bff; margin: 0;";
        saveBtn.onclick = () => submitUserUpdate(u.name);

        row.appendChild(nameLabel);
        row.appendChild(pwInput);
        row.appendChild(roleLabel);
        row.appendChild(saveBtn);
        container.appendChild(row);

        // Delete Button
        const delBtn = document.createElement('button');
        delBtn.innerText = "🗑️";
        delBtn.title = "Delete";

        if (u.name === currentLoggedInUser) {
            delBtn.style = "width: auto; padding: 5px 10px; background: #555; margin: 0; margin-left: 5px; cursor: not-allowed; opacity: 0.5;";
            delBtn.disabled = true;
            delBtn.title = "You cant delete yourself!";
        } else {
            delBtn.style = "width: auto; padding: 5px 10px; background: #dc3545; margin: 0; margin-left: 5px;";
            delBtn.onclick = () => deleteUser(u.name);
        }

        row.appendChild(delBtn);
    });

    // 2. Box for new users
    const newRow = document.createElement('div');
    // Dashed Border
    newRow.style = "display: flex; align-items: center; gap: 10px; background: #222; padding: 10px; margin-top: 20px; border: 1px dashed #666; border-radius: 5px;";

    const newNameInput = document.createElement('input');
    newNameInput.type = "text";
    newNameInput.placeholder = "New Username";
    newNameInput.id = "new-user-name";
    newNameInput.style = "flex: 1; padding: 5px; margin: 0; background: #333; color: #fff; border: 1px solid #555;";

    const newPassInput = document.createElement('input');
    newPassInput.type = "password";
    newPassInput.placeholder = "Password";
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
    addBtn.title = "Add User";
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
    if (confirm(`Do you really want to permanently delete the user '${username}'?`)) {
        ws.send(JSON.stringify({
            type: 'admin_delete_user',
            target_user: username
        }));
    }
}

function triggerSystem(action) {
    let text = "";
    if (action === 'restart_code') text = "Restart code?";
    if (action === 'reboot') text = "Restart System?";
    if (action === 'shutdown') text = "Shutdown System?";

    if (confirm(text)) {
        ws.send(JSON.stringify({
            type: 'system_control',
            command: action
        }));

        if (action !== 'restart_code') {
            closeSettings();
            alert("Action sent. Terminating connection.");
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

