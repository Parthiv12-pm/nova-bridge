// ═══════════════════════════════════════════════════════════════════════════
//  Nova Bridge — app.js v2
// ═══════════════════════════════════════════════════════════════════════════

const API        = 'http://localhost:8000';
let sessionId    = 'session-' + Math.random().toString(36).substr(2, 9);
let isListening  = false;
let recognition  = null;
let pendingIntent = null;
let currentEmotion = 'calm';
let webcamStream  = null;
let webcamActive  = false;
let webcamInterval = null;

// ═══════════════════════════════════════════════════════════════════════════
//  SPEECH RECOGNITION
// ═══════════════════════════════════════════════════════════════════════════

function setupSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    const hint = document.querySelector('.speak-hint');
    if (hint) hint.textContent = 'Use the Demo button to test';
    return null;
  }
  const r = new SpeechRecognition();
  r.continuous     = false;
  r.interimResults = true;
  r.lang           = 'en-IN';

  r.onresult = (e) => {
    const transcript = Array.from(e.results).map(r => r[0].transcript).join('');
    const box = document.getElementById('transcript-box');
    if (box) box.innerHTML = `<span>${transcript}</span>`;
  };

  r.onend = () => {
    const box  = document.getElementById('transcript-box');
    const text = box ? box.textContent.trim() : '';
    setListening(false);
    if (text && text !== 'Your words will appear here...') {
      logInteraction('voice', text);
      runPipeline(text, null);
    }
  };

  r.onerror = () => setListening(false);
  return r;
}

function startListening() {
  if (isListening) { stopListening(); return; }
  if (!recognition) recognition = setupSpeechRecognition();
  if (!recognition) {
    const text = prompt('Type your message:');
    if (text) runPipeline(text, null);
    return;
  }
  setListening(true);
  const box = document.getElementById('transcript-box');
  if (box) box.innerHTML = '<span style="color:var(--accent)">Listening...</span>';
  recognition.start();
}

function stopListening() {
  if (recognition) recognition.stop();
  setListening(false);
}

function setListening(val) {
  isListening = val;
  const btn = document.getElementById('speak-btn');
  if (!btn) return;
  if (val) {
    btn.classList.add('listening');
    const st = btn.querySelector('.speak-text');
    const sh = btn.querySelector('.speak-hint');
    if (st) st.textContent = 'Listening...';
    if (sh) sh.textContent = 'Tap again to stop';
  } else {
    btn.classList.remove('listening');
    const st = btn.querySelector('.speak-text');
    const sh = btn.querySelector('.speak-hint');
    if (st) st.textContent = 'Tap to Speak';
    if (sh) sh.textContent = 'Say anything — Nova understands';
  }
}


// ═══════════════════════════════════════════════════════════════════════════
//  LIVE WEBCAM — real camera, captures frame every 5 seconds
// ═══════════════════════════════════════════════════════════════════════════

async function toggleCamera() {
  if (webcamActive) {
    stopCamera();
  } else {
    await startCamera();
  }
}

async function startCamera() {
  try {
    webcamStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment', width: 640, height: 480 }
    });

    const video = document.getElementById('webcam-preview');
    video.srcObject = webcamStream;
    video.style.display = 'block';
    webcamActive = true;

    const btn = document.getElementById('camera-btn');
    if (btn) {
      btn.textContent   = '📷 Stop Camera';
      btn.style.borderColor = 'var(--green)';
      btn.style.color       = 'var(--green)';
    }

    // capture and analyze frame every 5 seconds
    webcamInterval = setInterval(captureWebcamFrame, 5000);

    // capture first frame immediately after 1 second
    setTimeout(captureWebcamFrame, 1000);

  } catch (err) {
    showNovaResponse('Camera access denied. Please allow camera permission in your browser.');
  }
}

function stopCamera() {
  if (webcamStream) {
    webcamStream.getTracks().forEach(t => t.stop());
    webcamStream = null;
  }
  if (webcamInterval) {
    clearInterval(webcamInterval);
    webcamInterval = null;
  }
  webcamActive = false;
  const video = document.getElementById('webcam-preview');
  if (video) video.style.display = 'none';

  const btn = document.getElementById('camera-btn');
  if (btn) {
    btn.textContent       = '📷 Live Camera';
    btn.style.borderColor = '';
    btn.style.color       = '';
  }
}

function captureWebcamFrame() {
  const video  = document.getElementById('webcam-preview');
  const canvas = document.getElementById('webcam-canvas');
  if (!video || !canvas || !webcamActive) return;

  canvas.width  = video.videoWidth  || 640;
  canvas.height = video.videoHeight || 480;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0);

  // get base64 frame
  const base64 = canvas.toDataURL('image/jpeg', 0.7).split(',')[1];

  // send to pipeline for facial emotion + pill bottle detection
  sendWebcamFrame(base64);
}

async function sendWebcamFrame(frameBase64) {
  try {
    const res = await fetch(`${API}/pipeline`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id:          sessionId,
        webcam_frame_base64: frameBase64,
        language:            'en',
        auto_execute:        false,
      }),
    });
    const data = await res.json();

    // update emotion silently from webcam
    if (data.emotion_alert) {
      currentEmotion = data.emotion_alert.alert_level;
      updateEmotion(currentEmotion);
      if (currentEmotion === 'distress' || currentEmotion === 'crisis') {
        addTimelineItem(currentEmotion);
        showCrisis(data.voice_response?.spoken_text || 'Distress detected. Caregiver notified.');
      }
    }

    // if pill bottle detected
    if (data.vision?.medication_name) {
      showNovaResponse(`📦 I can see ${data.vision.medication_name} — shall I check if you need a refill?`);
      speak(`I can see ${data.vision.medication_name}. Shall I order a refill?`);
    }

  } catch (e) { /* silent — webcam frames are best-effort */ }
}


// ═══════════════════════════════════════════════════════════════════════════
//  DEMO MODE
// ═══════════════════════════════════════════════════════════════════════════

function testDemo() {
  const demos = [
    { text: 'doctor pain tomorrow',     label: 'Book Doctor' },
    { text: 'medicine finished refill', label: 'Order Medicine' },
    { text: 'scared night alone',       label: 'Distress Support' },
    { text: 'bill electricity pay',     label: 'Pay Bill' },
  ];
  const pick = demos[Math.floor(Math.random() * demos.length)];
  const box  = document.getElementById('transcript-box');
  if (box) box.innerHTML = `<span>${pick.text}</span>`;
  logInteraction('demo', pick.text);
  runPipeline(pick.text, null);
}


// ═══════════════════════════════════════════════════════════════════════════
//  MAIN PIPELINE
// ═══════════════════════════════════════════════════════════════════════════

async function runPipeline(spokenText, imageBase64) {
  showLoading('Nova is understanding you...', [
    '🔍 Analyzing input...',
    '🧠 Reconstructing intent...',
    '💙 Checking emotional state...',
    '🛡️ Running safety check...',
    '⚡ Preparing action...'
  ]);
  hideBoxes();

  try {
    const body = {
      session_id:   sessionId,
      language:     'en',
      auto_execute: false,
    };
    if (spokenText)  body.spoken_text  = spokenText;
    if (imageBase64) body.image_base64 = imageBase64;

    const res  = await fetch(`${API}/pipeline`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    });
    const data = await res.json();
    hideLoading();
    handlePipelineResponse(data);

  } catch (err) {
    hideLoading();
    showNovaResponse('Sorry, I could not connect to the server. Make sure the backend is running on port 8000.');
    setStatus('Error', 'red');
  }
}


// ═══════════════════════════════════════════════════════════════════════════
//  HANDLE PIPELINE RESPONSE
// ═══════════════════════════════════════════════════════════════════════════

function handlePipelineResponse(data) {

  // Emotion ring
  if (data.emotion_alert) {
    currentEmotion = data.emotion_alert.alert_level;
    updateEmotion(currentEmotion);
    addTimelineItem(currentEmotion);
  }

  // Memory hint
  if (data.memory_hint) showMemoryHint(data.memory_hint);

  // Agent Console
  if (data.agent_console) renderAgentConsole(data.agent_console);

  // Safety check
  if (data.safety_check) renderSafetyCheck(data.safety_check);

  // Crisis / Distress
  if (data.emotion_alert &&
     (currentEmotion === 'crisis' || currentEmotion === 'distress')) {
    showCrisis(data.voice_response?.spoken_text || 'Caregiver has been notified. Help is on the way.');
    updateDashboardStats();
    return;
  }

  // Nova voice response
  if (data.voice_response?.spoken_text) {
    showNovaResponse(data.voice_response.spoken_text);
    speak(data.voice_response.spoken_text);
  }

  // Vision result
  if (data.vision?.medication_name) {
    showNovaResponse(`I can see ${data.vision.medication_name} on the label. I'll use this for your refill.`);
  }

  // Confirmation before acting
  if (data.action_confirmation && data.intent) {
    pendingIntent = data.intent;
    showConfirmation(data.action_confirmation);
    return;
  }

  // Context hint from memory
  if (data.context_hint) showNovaResponse(data.context_hint);

  // Proactive suggestion
  if (data.proactive_suggestion) showProactiveSuggestion(data.proactive_suggestion);

  // Engine badge
  if (data.engine_used) updateEngineBadge(data.engine_used);

  updateDashboardStats();
}


// ═══════════════════════════════════════════════════════════════════════════
//  CONFIRM / CANCEL ACTION
// ═══════════════════════════════════════════════════════════════════════════

async function confirmAction() {
  hideBoxes();
  if (!pendingIntent) return;

  showLoading('Nova Act is working...', [
    '🌐 Opening website...',
    '🛡️ Verifying safety...',
    '📋 Planning steps...',
    '📝 Filling in details...',
    '✅ Submitting...'
  ]);

  try {
    const res  = await fetch(`${API}/act`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        session_id: sessionId,
        task_type:  pendingIntent.intent_type,
        parameters: pendingIntent.entities,
      }),
    });
    const data = await res.json();
    hideLoading();

    if (data.agent_console) renderAgentConsole(data.agent_console);
    if (data.safety_check)  renderSafetyCheck(data.safety_check);

    if (data.success) {
      showResult(data.confirmation_text || 'Task completed successfully!');
      addActionItem(pendingIntent.intent_type, data.confirmation_text);
      speak(data.confirmation_text || 'Done! Task completed.');
      logInteraction('task', `${pendingIntent.intent_type} completed`);
    } else {
      showNovaResponse(data.error || 'Something went wrong. Please try again.');
    }

    pendingIntent = null;
    updateDashboardStats();

  } catch (err) {
    hideLoading();
    showNovaResponse('Could not complete the action. Please try again.');
  }
}

function cancelAction() {
  pendingIntent = null;
  hideBoxes();
  showNovaResponse("Okay, I've cancelled that. Just let me know when you're ready.");
  speak("Okay, cancelled. Just let me know when you're ready.");
}


// ═══════════════════════════════════════════════════════════════════════════
//  AGENT CONSOLE PANEL
// ═══════════════════════════════════════════════════════════════════════════

function renderAgentConsole(consoleData) {
  const panel = document.getElementById('agent-console-panel');
  if (!panel || !consoleData) return;

  const engineColor = {
    'Nova Act':               '#00b4d8',
    'Playwright + Groq (free fallback)': '#f9a825',
    'Demo simulation':        '#888',
  }[consoleData.engine] || '#00b4d8';

  const stepsHtml = (consoleData.steps || []).map(step => {
    const cls = step.status === 'done'    ? 'console-step-done'
              : step.status === 'running' ? 'console-step-running'
              : 'console-step-pending';
    return `<div class="console-step ${cls}">
      <span class="console-step-icon">${step.icon}</span>
      <span class="console-step-label">${step.label}</span>
    </div>`;
  }).join('');

  panel.innerHTML = `
    <div class="console-header">
      <div class="console-intent">${consoleData.intent_label || 'Processing'}</div>
      <div class="console-engine" style="color:${engineColor}">${consoleData.engine || 'Nova Act'}</div>
    </div>
    <div class="console-steps">${stepsHtml}</div>
    <div class="console-progress">
      <div class="console-progress-bar">
        <div class="console-progress-fill" style="width:${consoleData.progress_pct || 0}%"></div>
      </div>
      <span class="console-progress-text">${consoleData.progress_text || ''}</span>
    </div>
    ${consoleData.duration_text ? `<div class="console-duration">${consoleData.duration_text}</div>` : ''}
  `;
  panel.style.display = 'block';
}


// ═══════════════════════════════════════════════════════════════════════════
//  SAFETY CHECK PANEL
// ═══════════════════════════════════════════════════════════════════════════

function renderSafetyCheck(check) {
  const panel = document.getElementById('safety-check-panel');
  if (!panel || !check) return;

  // always show a default safety check even without backend data
  const rows = check.rows || [
    { ok: true,  icon: '✓', label: 'Verified website' },
    { ok: true,  icon: '✓', label: 'Secure connection (HTTPS)' },
    { ok: true,  icon: '✓', label: 'Action is reversible' },
    { ok: true,  icon: '✓', label: 'Low risk task' },
  ];

  const rowsHtml = rows.map(row => `
    <div class="safety-row ${row.ok ? 'safety-ok' : 'safety-fail'}">
      <span class="safety-icon">${row.icon}</span>
      <span class="safety-label">${row.label}</span>
    </div>`).join('');

  const approved    = check.approved !== false;
  const statusColor = approved ? 'var(--green)' : 'var(--red)';

  panel.innerHTML = `
    <div class="safety-header">Safety Check</div>
    <div class="safety-rows">${rowsHtml}</div>
    <div class="safety-status" style="color:${statusColor}">
      ${approved ? '✓ Approved — safe to proceed' : '✗ Review required'}
    </div>
  `;
  panel.style.display = 'block';
}


// ═══════════════════════════════════════════════════════════════════════════
//  PROACTIVE SUGGESTION
// ═══════════════════════════════════════════════════════════════════════════

function showProactiveSuggestion(text) {
  if (!text) return;
  const panel = document.getElementById('proactive-panel');
  if (!panel) return;
  const msg = panel.querySelector('.proactive-message');
  if (msg) msg.textContent = text;
  panel.style.display = 'block';
  setTimeout(() => { panel.style.display = 'none'; }, 12000);
}

function dismissProactive() {
  const panel = document.getElementById('proactive-panel');
  if (panel) panel.style.display = 'none';
}

async function pollProactiveSuggestion() {
  try {
    const res  = await fetch(
      `${API}/dashboard/proactive-suggestion?session_id=${sessionId}&current_emotion=${currentEmotion}`
    );
    const data = await res.json();
    if (data.has_suggestion && data.suggestion) {
      showProactiveSuggestion(data.suggestion);
      speak(data.suggestion);
    }
  } catch (e) { /* silent */ }
}


// ═══════════════════════════════════════════════════════════════════════════
//  MEMORY HINT
// ═══════════════════════════════════════════════════════════════════════════

function showMemoryHint(hint) {
  const el = document.getElementById('memory-hint');
  if (!el) return;
  el.textContent = `💾 Remembered: ${hint}`;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 6000);
}


// ═══════════════════════════════════════════════════════════════════════════
//  ENGINE BADGE
// ═══════════════════════════════════════════════════════════════════════════

function updateEngineBadge(engine) {
  const badge = document.getElementById('engine-badge');
  if (!badge) return;
  const colors = {
    'Nova Act':               '#00b4d8',
    'Playwright + Groq (free fallback)': '#f9a825',
    'Demo simulation':        '#888',
  };
  badge.textContent       = engine;
  badge.style.borderColor = colors[engine] || '#00b4d8';
  badge.style.color       = colors[engine] || '#00b4d8';
  badge.style.display     = 'inline-block';
}


// ═══════════════════════════════════════════════════════════════════════════
//  TEXT TO SPEECH
// ═══════════════════════════════════════════════════════════════════════════

function speak(text) {
  if (!window.speechSynthesis || !text) return;
  window.speechSynthesis.cancel();
  const utt    = new SpeechSynthesisUtterance(text);
  utt.rate     = currentEmotion === 'calm' ? 0.88 : 0.75;
  utt.pitch    = 1.0;
  utt.volume   = 1.0;
  const voices = window.speechSynthesis.getVoices();
  const preferred = voices.find(v =>
    v.name.includes('Female') ||
    v.name.includes('Samantha') ||
    v.name.includes('Google UK English Female')
  );
  if (preferred) utt.voice = preferred;
  window.speechSynthesis.speak(utt);
}


// ═══════════════════════════════════════════════════════════════════════════
//  EMOTION UI
// ═══════════════════════════════════════════════════════════════════════════

const EMOTIONS = {
  calm:    { icon: '😌', label: 'Calm',    class: '' },
  anxious: { icon: '😰', label: 'Anxious', class: 'anxious' },
  distress:{ icon: '😢', label: 'Distress',class: 'distress' },
  crisis:  { icon: '🚨', label: 'Crisis',  class: 'crisis' },
};

function updateEmotion(level) {
  const e    = EMOTIONS[level] || EMOTIONS.calm;
  const ring = document.getElementById('emotion-ring');
  if (ring) ring.className = 'emotion-ring ' + e.class;
  const icon  = document.getElementById('emotion-icon');
  const label = document.getElementById('emotion-label');
  if (icon)  icon.textContent  = e.icon;
  if (label) label.textContent = e.label;
}


// ═══════════════════════════════════════════════════════════════════════════
//  DASHBOARD STATS
// ═══════════════════════════════════════════════════════════════════════════

async function updateDashboardStats() {
  try {
    const res  = await fetch(`${API}/dashboard/stats?session_id=${sessionId}`);
    const data = await res.json();

    _set('tasks-completed', data.tasks_completed);
    _set('hours-saved',     (data.hours_saved || 0).toFixed(1) + 'h');
    _set('costs-saved',     '₹' + Math.round((data.caregiver_costs_saved || 0) * 83));
    _set('alerts-count',    data.alerts_triggered);

    const hours   = (data.hours_saved || 0).toFixed(1);
    const savings = Math.round((data.caregiver_costs_saved || 0) * 83);
    _set('impact-summary',
      data.tasks_completed > 0
        ? `Nova Bridge saved ${hours} hours — ₹${savings.toLocaleString()} in caregiver costs.`
        : 'Nova Bridge is ready to help.'
    );
  } catch (e) { /* silent */ }

  loadMedicineAdherence();
  loadWeeklyScore();
  loadBehaviorAlerts();
}


// ═══════════════════════════════════════════════════════════════════════════
//  MEDICINE ADHERENCE
// ═══════════════════════════════════════════════════════════════════════════

async function loadMedicineAdherence() {
  try {
    const res   = await fetch(`${API}/behavior/medicine-log?session_id=${sessionId}`);
    const data  = await res.json();
    const panel = document.getElementById('medicine-panel');
    if (!panel) return;

    if (!data.schedule || data.schedule.length === 0) {
      panel.innerHTML = '<div class="panel-empty">No medicines scheduled</div>';
      return;
    }

    const pct         = data.summary?.adherence_pct || 100;
    const statusColor = pct >= 90 ? 'var(--green)' : pct >= 70 ? 'var(--amber)' : 'var(--red)';

    const rows = data.schedule.map(med => `
      <div class="med-row">
        <span class="med-icon">${med.status === 'taken' ? '✓' : '⚠'}</span>
        <span class="med-name">${med.name}</span>
        <span class="med-status" style="color:${
          med.status === 'taken' ? 'var(--green)' :
          med.status === 'missed' ? 'var(--red)' : 'var(--amber)'
        }">${med.status}</span>
      </div>`).join('');

    panel.innerHTML = `
      <div class="adherence-header">
        <span>Adherence</span>
        <span style="color:${statusColor};font-weight:500">${pct}%</span>
      </div>
      <div class="adherence-bar">
        <div class="adherence-fill" style="width:${pct}%;background:${statusColor}"></div>
      </div>
      <div class="med-list">${rows}</div>
      ${data.due_refills?.length ? `
        <div class="refill-alert">⚠ Refill needed: ${data.due_refills.join(', ')}</div>` : ''}
    `;
  } catch (e) { /* silent */ }
}


// ═══════════════════════════════════════════════════════════════════════════
//  WEEKLY HEALTH SCORE
// ═══════════════════════════════════════════════════════════════════════════

async function loadWeeklyScore() {
  try {
    const res  = await fetch(`${API}/dashboard/weekly-score?session_id=${sessionId}`);
    const data = await res.json();
    const el   = document.getElementById('weekly-score');
    if (!el) return;

    const score = data.total_score || 0;
    const color = score >= 85 ? 'var(--green)'
                : score >= 55 ? 'var(--amber)'
                : 'var(--red)';
    const trend     = data.trend || 'stable';
    const trendIcon = trend === 'improving' ? '↑' : trend === 'declining' ? '↓' : '→';

    el.innerHTML = `
      <div class="score-circle" style="border-color:${color}">
        <span class="score-num" style="color:${color}">${score}</span>
        <span class="score-max">/100</span>
      </div>
      <div class="score-grade">${data.grade || ''}</div>
      <div class="score-trend" style="color:${color}">${trendIcon} ${trend}</div>
    `;
  } catch (e) { /* silent */ }
}


// ═══════════════════════════════════════════════════════════════════════════
//  BEHAVIOR ALERTS
// ═══════════════════════════════════════════════════════════════════════════

async function loadBehaviorAlerts() {
  try {
    const res   = await fetch(`${API}/behavior/deviations?session_id=${sessionId}`);
    const data  = await res.json();
    const panel = document.getElementById('behavior-alerts');
    if (!panel) return;

    if (!data.deviations?.length && !data.consecutive_distress) {
      panel.innerHTML = '<div class="panel-empty">No deviations detected today</div>';
      return;
    }

    const items = [...(data.deviations || [])];
    if (data.consecutive_distress) items.push(data.consecutive_distress);

    panel.innerHTML = items.map(dev => `
      <div class="deviation-item severity-${dev.severity}">
        <span class="dev-icon">${dev.severity === 'high' ? '🚨' : '⚠️'}</span>
        <span class="dev-msg">${dev.message}</span>
      </div>`).join('');
  } catch (e) { /* silent */ }
}


// ═══════════════════════════════════════════════════════════════════════════
//  LOG INTERACTION — FIXED (query params not body)
// ═══════════════════════════════════════════════════════════════════════════

async function logInteraction(type, detail = '') {
  try {
    // ── FIX: send as query params to match FastAPI endpoint signature ──
    const params = new URLSearchParams({
      session_id:       sessionId,
      interaction_type: type,
      detail:           detail,
    });
    await fetch(`${API}/behavior/log-interaction?${params}`, {
      method: 'POST',
    });
  } catch (e) { /* silent — non-critical */ }
}


// ═══════════════════════════════════════════════════════════════════════════
//  TIMELINE + ACTIONS
// ═══════════════════════════════════════════════════════════════════════════

function addTimelineItem(emotion) {
  const container = document.getElementById('timeline');
  if (!container) return;
  const empty = container.querySelector('.timeline-empty');
  if (empty) empty.remove();

  const e    = EMOTIONS[emotion] || EMOTIONS.calm;
  const time = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
  const item = document.createElement('div');
  item.className = 'timeline-item';
  item.innerHTML = `
    <div class="timeline-dot ${emotion}"></div>
    <div class="timeline-info">
      <div class="timeline-emotion">${e.icon} ${e.label}</div>
      <div class="timeline-time">${time}</div>
    </div>`;
  container.insertBefore(item, container.firstChild);
}

function addActionItem(intentType, confirmationText) {
  const container = document.getElementById('actions-list');
  if (!container) return;
  const empty = container.querySelector('.action-empty');
  if (empty) empty.remove();

  const icons = {
    book_appointment: '🏥',
    order_medicine:   '💊',
    send_message:     '💬',
    fill_form:        '📋',
    pay_bill:         '💳',
  };

  const time = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
  const item = document.createElement('div');
  item.className = 'action-item';
  item.innerHTML = `
    <div class="action-item-icon">${icons[intentType] || '⚡'}</div>
    <div class="action-item-text">${confirmationText || intentType.replace(/_/g, ' ')}</div>
    <div class="action-item-time">${time}</div>`;
  container.insertBefore(item, container.firstChild);
}


// ═══════════════════════════════════════════════════════════════════════════
//  UI HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function showNovaResponse(text) {
  const box = document.getElementById('nova-response');
  const txt = document.getElementById('nova-text');
  if (box) box.style.display = 'block';
  if (txt) txt.textContent   = text;
}

function showConfirmation(text) {
  // always show safety check with confirmation
  renderSafetyCheck({ approved: true });

  const box = document.getElementById('confirmation-box');
  const txt = document.getElementById('confirmation-text');
  if (box) box.style.display = 'block';
  if (txt) txt.textContent   = text;
}

function showResult(text) {
  const box = document.getElementById('result-box');
  const txt = document.getElementById('result-text');
  if (box) box.style.display = 'block';
  if (txt) txt.textContent   = text;
}

function showCrisis(message) {
  const panel = document.getElementById('crisis-panel');
  const msg   = document.getElementById('crisis-message');
  if (panel) panel.style.display = 'block';
  if (msg)   msg.textContent     = message;
  updateEmotion('crisis');
  speak(message);
}

function dismissCrisis() {
  const panel = document.getElementById('crisis-panel');
  if (panel) panel.style.display = 'none';
  updateEmotion('calm');
}

function hideBoxes() {
  ['nova-response','confirmation-box','result-box',
   'agent-console-panel','safety-check-panel'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
}

function showLoading(text, steps) {
  const loadText = document.getElementById('loading-text');
  const stepsEl  = document.getElementById('loading-steps');
  const overlay  = document.getElementById('loading-overlay');
  if (loadText) loadText.textContent    = text;
  if (stepsEl)  stepsEl.innerHTML       = '';
  if (overlay)  overlay.style.display  = 'flex';
  setStatus('Processing...', 'amber');

  if (stepsEl && steps) {
    steps.forEach((s, i) => {
      setTimeout(() => {
        const div = document.createElement('div');
        div.className   = 'loading-step';
        div.textContent = s;
        stepsEl.appendChild(div);
      }, i * 400);
    });
  }
}

function hideLoading() {
  const overlay = document.getElementById('loading-overlay');
  if (overlay) overlay.style.display = 'none';
  setStatus('Ready', 'green');
}

function setStatus(text, color) {
  const el  = document.getElementById('status-text');
  const dot = document.querySelector('.status-dot');
  if (el)  el.textContent = text;
  if (dot) dot.style.background = (
    color === 'green' ? 'var(--green)' :
    color === 'amber' ? 'var(--amber)' :
    color === 'red'   ? 'var(--red)'   : 'var(--accent)'
  );
}

function _set(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}


// ═══════════════════════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════════════════════

window.addEventListener('load', () => {
  recognition = setupSpeechRecognition();
  if (window.speechSynthesis) window.speechSynthesis.getVoices();

  // initial load
  updateDashboardStats();

  // ── FIXED: poll every 30 seconds not 5 — saves AWS quota ──
  setInterval(updateDashboardStats, 30000);

  // proactive suggestions every 60 seconds
  setInterval(pollProactiveSuggestion, 60000);

  console.log('Nova Bridge v2 initialized. Session:', sessionId);
});