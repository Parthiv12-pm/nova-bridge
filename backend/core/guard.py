"""
GUARD — Emotional Safety Layer (Upgraded)
==========================================
What's new vs old guard.py:
  - Every emotion detection logged to Nova Memory System
  - Weekly pattern analysis (7-day trend)
  - Smart caregiver alert on 3+ distress events in one day
  - Behavior anomaly detection (unusual inactivity, night distress)
  - All notifications logged to session_memory for dashboard
"""

import boto3
import json
import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from models.schemas import (
    EmotionInput, GuardAlert, EmotionState,
    CaregiverNotification
)

# ── Import Nova Memory System ────────────────────────────────────────────────
from core.session_memory import (
    log_emotion,
    get_today_emotional_summary,
    get_weekly_emotional_trend,
    get_full_memory,
    get_preferences,
)

load_dotenv()

# ── Bedrock client ───────────────────────────────────────────────────────────
bedrock = boto3.client(
    service_name="bedrock-runtime",
    region_name=os.getenv("BEDROCK_REGION", "us-east-1"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
)

# ── In-memory caregiver registry ─────────────────────────────────────────────
_caregiver_registry: dict = {}

# ── Notification log ─────────────────────────────────────────────────────────
_notification_log: list = []

# ── Distress threshold before auto-alert ─────────────────────────────────────
DISTRESS_ALERT_THRESHOLD = 3   # alert caregiver after this many distress events today


def register_caregiver(session_id: str, name: str, phone: str, email: str):
    _caregiver_registry[session_id] = {
        "name":  name,
        "phone": phone,
        "email": email
    }
    # also save to memory system for persistence
    from core.session_memory import set_preference
    set_preference(session_id, "caregiver_name",  name)
    set_preference(session_id, "caregiver_phone", phone)
    set_preference(session_id, "caregiver_email", email)


# ═══════════════════════════════════════════════════════════════════════════
#  GUARD SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════════════════

GUARD_SYSTEM_PROMPT = """
You are GUARD — the emotional safety layer of Nova Bridge.
Your job is to assess emotional state from combined signals:
voice tone score, facial emotion, and text content.

Rules:
- "crisis"   → immediate danger, extreme panic, medical emergency
- "distress" → clear upset, pain, fear, crying
- "anxious"  → tension, worry, nervousness
- "calm"     → neutral or positive state

Return ONLY valid JSON, nothing else:
{
  "alert_level": "calm|anxious|distress|crisis",
  "trigger_reason": "one sentence explaining why",
  "action_taken": "none|grounding_response|caregiver_notified|emergency_call",
  "suggested_response_tone": "warm|slow_calm|validating|urgent",
  "grounding_message": "short calming message or null",
  "emotion_score": 0.0
}

Action rules:
- calm/anxious → action: "none" or "grounding_response"
- distress     → action: "caregiver_notified"
- crisis       → action: "emergency_call"

emotion_score: 0.0 (calm) to 1.0 (crisis)
"""


# ═══════════════════════════════════════════════════════════════════════════
#  SMART LOCAL FALLBACK (no AWS needed)
# ═══════════════════════════════════════════════════════════════════════════

def _smart_fallback(emotion_input: EmotionInput) -> GuardAlert:
    """
    Keyword + signal based emotion detection.
    Used when AWS Bedrock is throttled or unavailable.
    """
    text = (emotion_input.text_signals or "").lower()

    crisis_words   = ["help", "emergency", "dying", "can't breathe", "chest pain",
                      "suicide", "heart attack", "call ambulance", "not breathing"]
    distress_words = ["pain", "scared", "hurt", "crying", "alone", "afraid",
                      "sick", "terrible", "worse", "unbearable", "please help"]
    anxious_words  = ["worried", "nervous", "anxious", "stress", "panic",
                      "afraid", "tension", "restless", "can't sleep"]

    # facial signal takes highest priority
    if emotion_input.facial_emotion == EmotionState.CRISIS:
        return GuardAlert(
            session_id=emotion_input.session_id,
            alert_level=EmotionState.CRISIS,
            trigger_reason="Crisis detected from facial expression",
            action_taken="emergency_call",
            emotion_score=1.0
        )

    if emotion_input.facial_emotion == EmotionState.DISTRESS:
        return GuardAlert(
            session_id=emotion_input.session_id,
            alert_level=EmotionState.DISTRESS,
            trigger_reason="Distress detected from facial expression",
            action_taken="caregiver_notified",
            emotion_score=0.8
        )

    # voice tone score
    if emotion_input.voice_tone_score:
        if emotion_input.voice_tone_score > 0.85:
            return GuardAlert(
                session_id=emotion_input.session_id,
                alert_level=EmotionState.CRISIS,
                trigger_reason="Extreme distress in voice tone",
                action_taken="emergency_call",
                emotion_score=emotion_input.voice_tone_score
            )
        if emotion_input.voice_tone_score > 0.65:
            return GuardAlert(
                session_id=emotion_input.session_id,
                alert_level=EmotionState.DISTRESS,
                trigger_reason="High distress detected in voice tone",
                action_taken="caregiver_notified",
                emotion_score=emotion_input.voice_tone_score
            )
        if emotion_input.voice_tone_score > 0.4:
            return GuardAlert(
                session_id=emotion_input.session_id,
                alert_level=EmotionState.ANXIOUS,
                trigger_reason="Moderate stress detected in voice tone",
                action_taken="grounding_response",
                emotion_score=emotion_input.voice_tone_score
            )

    # text keyword detection
    if any(w in text for w in crisis_words):
        return GuardAlert(
            session_id=emotion_input.session_id,
            alert_level=EmotionState.CRISIS,
            trigger_reason="Crisis keywords detected in speech",
            action_taken="emergency_call",
            emotion_score=1.0
        )

    if any(w in text for w in distress_words):
        return GuardAlert(
            session_id=emotion_input.session_id,
            alert_level=EmotionState.DISTRESS,
            trigger_reason="Distress keywords detected in speech",
            action_taken="caregiver_notified",
            emotion_score=0.75
        )

    if any(w in text for w in anxious_words):
        return GuardAlert(
            session_id=emotion_input.session_id,
            alert_level=EmotionState.ANXIOUS,
            trigger_reason="Anxiety keywords detected in speech",
            action_taken="grounding_response",
            emotion_score=0.45
        )

    return GuardAlert(
        session_id=emotion_input.session_id,
        alert_level=EmotionState.CALM,
        trigger_reason="No distress signals detected",
        action_taken="none",
        emotion_score=0.05
    )


# ═══════════════════════════════════════════════════════════════════════════
#  BEHAVIOR TRACKING — NEW
#  Logs every emotion to memory + checks thresholds
# ═══════════════════════════════════════════════════════════════════════════

async def _track_and_analyze(
    session_id: str,
    alert: GuardAlert,
    trigger: str = ""
) -> dict:
    """
    Called after every emotion detection.
    1. Logs emotion to Nova Memory System
    2. Checks if distress threshold breached (3+ today)
    3. Checks for anomalies (night distress, sudden pattern change)
    4. Returns behavior analysis dict for the response
    """
    emotion_str = alert.alert_level.value
    score       = getattr(alert, "emotion_score", 0.0) or 0.0

    # ── 1. Log to memory ─────────────────────────────────────────────────
    log_emotion(session_id, emotion_str, score=score, trigger=trigger)

    # ── 2. Get today's summary from memory ───────────────────────────────
    today_summary = get_today_emotional_summary(session_id)
    distress_today = today_summary.get("distress_count", 0)

    # ── 3. Threshold check — alert caregiver on 3+ distress today ────────
    threshold_breached = False
    if emotion_str in ("distress", "crisis") and distress_today >= DISTRESS_ALERT_THRESHOLD:
        threshold_breached = True
        await _notify_caregiver(
            session_id=session_id,
            alert_type=alert.alert_level,
            message=(
                f"BEHAVIOR ALERT: {distress_today} distress events detected today. "
                f"Latest trigger: {trigger or alert.trigger_reason}. "
                f"Pattern suggests user may need immediate attention."
            ),
            is_pattern_alert=True
        )

    # ── 4. Anomaly detection ─────────────────────────────────────────────
    anomaly = _detect_anomaly(session_id, emotion_str, today_summary)

    # ── 5. Weekly trend for context ──────────────────────────────────────
    weekly = get_weekly_emotional_trend(session_id)
    # count high-distress days in past 7 days
    high_distress_days = sum(1 for day in weekly if day["distress_count"] >= 2)

    return {
        "emotion_logged":       True,
        "distress_count_today": distress_today,
        "threshold_breached":   threshold_breached,
        "threshold":            DISTRESS_ALERT_THRESHOLD,
        "anomaly_detected":     anomaly is not None,
        "anomaly":              anomaly,
        "high_distress_days_this_week": high_distress_days,
        "today_dominant":       today_summary.get("dominant", "calm"),
        "weekly_trend":         weekly,
    }


def _detect_anomaly(session_id: str, current_emotion: str, today_summary: dict) -> dict | None:
    """
    Detects unusual behavioral patterns.
    Returns anomaly dict if found, None if normal.
    """
    hour = datetime.now().hour

    # Night distress (10pm – 5am)
    if current_emotion in ("distress", "crisis") and (hour >= 22 or hour <= 5):
        return {
            "type":    "night_distress",
            "message": f"Distress detected at unusual hour ({hour}:00). User may need overnight support.",
            "severity": "high"
        }

    # Sudden spike — was calm all day, now distress
    if current_emotion in ("distress", "crisis"):
        calm_count = today_summary.get("emotion_counts", {}).get("calm", 0)
        distress_count = today_summary.get("distress_count", 0)
        if calm_count >= 5 and distress_count == 1:
            return {
                "type":    "sudden_spike",
                "message": "User was calm all day but suddenly showing distress. Possible incident.",
                "severity": "medium"
            }

    # Prolonged anxiety — anxious 3+ times today
    if current_emotion == "anxious":
        anxious_count = today_summary.get("emotion_counts", {}).get("anxious", 0)
        if anxious_count >= 3:
            return {
                "type":    "prolonged_anxiety",
                "message": f"User has been anxious {anxious_count} times today. May need check-in.",
                "severity": "medium"
            }

    return None


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN EMOTION ANALYZER
# ═══════════════════════════════════════════════════════════════════════════

async def analyze_emotion(emotion_input: EmotionInput) -> GuardAlert:
    """
    Analyze combined emotion signals.
    Uses Nova Bedrock when available, smart local fallback when throttled.
    Now also logs every result to Nova Memory System.
    """
    signals = []

    if emotion_input.voice_tone_score is not None:
        level = ("high distress" if emotion_input.voice_tone_score > 0.7
                 else "moderate stress" if emotion_input.voice_tone_score > 0.4
                 else "calm")
        signals.append(f"Voice tone score: {emotion_input.voice_tone_score:.2f} ({level})")

    if emotion_input.facial_emotion:
        signals.append(f"Facial expression: {emotion_input.facial_emotion.value}")

    if emotion_input.text_signals:
        signals.append(f"Text content: '{emotion_input.text_signals}'")

    if not signals:
        alert = GuardAlert(
            session_id=emotion_input.session_id,
            alert_level=EmotionState.CALM,
            trigger_reason="No signals detected",
            action_taken="none",
            emotion_score=0.0
        )
        # still log calm state
        await _track_and_analyze(emotion_input.session_id, alert, trigger="no signals")
        return alert

    combined = "\n".join(signals)

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 256,
        "system": GUARD_SYSTEM_PROMPT,
        "messages": [{
            "role": "user",
            "content": f"Assess these emotional signals:\n{combined}"
        }]
    })

    # ── Try Nova Bedrock first ────────────────────────────────────────────
    try:
        response = bedrock.invoke_model(
            modelId="us.amazon.nova-lite-v1:0",
            body=body,
            contentType="application/json",
            accept="application/json"
        )
        result   = json.loads(response["body"].read())
        raw_text = result["content"][0]["text"].strip()

        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        raw_text = raw_text.strip()

        parsed      = json.loads(raw_text)
        alert_level = EmotionState(parsed.get("alert_level", "calm"))
        action      = parsed.get("action_taken", "none")
        score       = float(parsed.get("emotion_score", 0.0))
        trigger_reason = parsed.get("trigger_reason", "")

        alert = GuardAlert(
            session_id=emotion_input.session_id,
            alert_level=alert_level,
            trigger_reason=trigger_reason,
            action_taken=action,
            emotion_score=score
        )

        # ── Caregiver notification ────────────────────────────────────────
        if alert_level == EmotionState.DISTRESS:
            await _notify_caregiver(
                session_id=emotion_input.session_id,
                alert_type=alert_level,
                message=trigger_reason or "User showing signs of distress."
            )
            alert.action_taken = "caregiver_notified"

        elif alert_level == EmotionState.CRISIS:
            await _notify_caregiver(
                session_id=emotion_input.session_id,
                alert_type=alert_level,
                message=trigger_reason or "CRISIS DETECTED."
            )
            alert.action_taken = "emergency_call"

        # ── NEW: Log to memory + behavior analysis ────────────────────────
        behavior = await _track_and_analyze(
            emotion_input.session_id, alert, trigger=trigger_reason
        )
        alert.behavior_analysis = behavior

        return alert

    except Exception as e:
        # ── Smart local fallback ──────────────────────────────────────────
        print(f"⚠️  GUARD fallback (AWS unavailable): {e}")
        alert = _smart_fallback(emotion_input)

        # caregiver notification from fallback too
        if alert.alert_level == EmotionState.DISTRESS:
            await _notify_caregiver(
                session_id=emotion_input.session_id,
                alert_type=alert.alert_level,
                message=alert.trigger_reason
            )
        elif alert.alert_level == EmotionState.CRISIS:
            await _notify_caregiver(
                session_id=emotion_input.session_id,
                alert_type=alert.alert_level,
                message=alert.trigger_reason
            )

        # ── NEW: Log fallback result to memory too ────────────────────────
        behavior = await _track_and_analyze(
            emotion_input.session_id, alert, trigger=alert.trigger_reason
        )
        alert.behavior_analysis = behavior

        return alert


# ═══════════════════════════════════════════════════════════════════════════
#  WEEKLY PATTERN ANALYSIS — NEW
#  Called by dashboard to show 7-day emotional trends
# ═══════════════════════════════════════════════════════════════════════════

def get_weekly_pattern_analysis(session_id: str) -> dict:
    """
    Analyzes 7-day emotional history from memory.
    Returns insights for the caregiver dashboard.
    """
    weekly = get_weekly_emotional_trend(session_id)

    total_distress   = sum(d["distress_count"] for d in weekly)
    total_calm       = sum(d["calm_count"] for d in weekly)
    total_anxious    = sum(d["anxious_count"] for d in weekly)
    high_risk_days   = [d for d in weekly if d["distress_count"] >= 2]
    improving        = _is_improving(weekly)

    # find worst day
    worst_day = max(weekly, key=lambda d: d["distress_count"]) if weekly else None

    # overall risk level
    if total_distress >= 10 or len(high_risk_days) >= 4:
        risk_level = "high"
        risk_message = "User has shown frequent distress this week. Immediate caregiver review recommended."
    elif total_distress >= 5 or len(high_risk_days) >= 2:
        risk_level = "medium"
        risk_message = "User has shown moderate distress. Schedule a wellness check."
    else:
        risk_level = "low"
        risk_message = "User is generally stable this week."

    return {
        "weekly_trend":      weekly,
        "total_distress":    total_distress,
        "total_calm":        total_calm,
        "total_anxious":     total_anxious,
        "high_risk_days":    len(high_risk_days),
        "improving":         improving,
        "worst_day":         worst_day,
        "risk_level":        risk_level,
        "risk_message":      risk_message,
        "recommendation":    _get_recommendation(risk_level, total_distress, improving),
        "generated_at":      datetime.now().isoformat(),
    }


def _is_improving(weekly: list) -> bool:
    """True if distress is decreasing over the week."""
    if len(weekly) < 4:
        return False
    first_half  = sum(d["distress_count"] for d in weekly[:3])
    second_half = sum(d["distress_count"] for d in weekly[4:])
    return second_half < first_half


def _get_recommendation(risk_level: str, total_distress: int, improving: bool) -> str:
    if risk_level == "high":
        return "Consider daily caregiver check-ins. Review medication schedule. Consult doctor."
    if risk_level == "medium" and not improving:
        return "Schedule a wellness call this week. Check medicine adherence."
    if risk_level == "medium" and improving:
        return "Situation improving. Continue monitoring. Keep current support plan."
    return "User is doing well. Maintain current routine and check-in schedule."


# ═══════════════════════════════════════════════════════════════════════════
#  CAREGIVER NOTIFICATION (upgraded with pattern alert support)
# ═══════════════════════════════════════════════════════════════════════════

async def _notify_caregiver(
    session_id: str,
    alert_type: EmotionState,
    message: str,
    is_pattern_alert: bool = False
) -> CaregiverNotification:
    """
    Sends alert to caregiver.
    is_pattern_alert=True means this was triggered by 3+ distress threshold.
    """
    # try registry first, then fall back to memory
    caregiver = _caregiver_registry.get(session_id)
    if not caregiver:
        prefs = get_preferences(session_id)
        if prefs.get("caregiver_name"):
            caregiver = {
                "name":  prefs["caregiver_name"],
                "phone": prefs.get("caregiver_phone", ""),
                "email": prefs.get("caregiver_email", ""),
            }

    timestamp = datetime.utcnow().isoformat()
    alert_tag = "PATTERN ALERT" if is_pattern_alert else alert_type.value.upper()

    notification = CaregiverNotification(
        session_id=session_id,
        user_name=caregiver.get("name", "User") if caregiver else "User",
        alert_type=alert_type,
        message=message,
        timestamp=timestamp
    )

    # console log (in production: send SMS/email/push here)
    print(f"\n{'='*55}")
    print(f"🚨 CAREGIVER ALERT [{alert_tag}]")
    print(f"   Session   : {session_id}")
    print(f"   Message   : {message}")
    print(f"   Time      : {timestamp}")
    if is_pattern_alert:
        print(f"   Reason    : Distress threshold ({DISTRESS_ALERT_THRESHOLD}+ events) breached")
    if caregiver:
        print(f"   Notifying : {caregiver['name']} ({caregiver.get('phone', 'no phone')})")
    print(f"{'='*55}\n")

    _notification_log.append(notification)
    return notification


# ═══════════════════════════════════════════════════════════════════════════
#  SONIC CONFIG & GROUNDING (unchanged from original, kept intact)
# ═══════════════════════════════════════════════════════════════════════════

def get_sonic_config(emotion_state: EmotionState) -> dict:
    base_config = {
        "modelId": "amazon.nova-sonic-v1:0",
        "turn_taking_sensitivity": "LOW",
        "polyglot": True,
    }
    if emotion_state == EmotionState.CALM:
        return {**base_config, "speaking_rate": "medium", "voice_style": "warm",      "response_prefix": ""}
    elif emotion_state == EmotionState.ANXIOUS:
        return {**base_config, "speaking_rate": "slow",   "voice_style": "gentle",    "response_prefix": "I'm right here with you. "}
    elif emotion_state == EmotionState.DISTRESS:
        return {**base_config, "speaking_rate": "slow",   "voice_style": "grounding", "response_prefix": "I hear you. You're safe. "}
    elif emotion_state == EmotionState.CRISIS:
        return {**base_config, "speaking_rate": "slow",   "voice_style": "grounding", "response_prefix": "I'm here. Help is on the way. "}
    return base_config


def get_grounding_message(emotion_state: EmotionState) -> str:
    messages = {
        EmotionState.ANXIOUS: (
            "Take a slow breath with me. In... and out. "
            "I'm here and I'll help you with everything."
        ),
        EmotionState.DISTRESS: (
            "I can see you're having a hard time. "
            "You don't need to explain anything. "
            "I've let someone who cares about you know. "
            "I'm staying right here with you."
        ),
        EmotionState.CRISIS: (
            "I'm here with you right now. "
            "I've contacted someone to help. "
            "You are not alone. "
            "Can you take one slow breath for me?"
        ),
    }
    return messages.get(emotion_state, "")


# ═══════════════════════════════════════════════════════════════════════════
#  NOTIFICATION LOG HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def get_notification_log(session_id: str = None) -> list:
    if session_id:
        return [n for n in _notification_log if n.session_id == session_id]
    return _notification_log


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN FUSE FUNCTION (backward compatible)
# ═══════════════════════════════════════════════════════════════════════════

async def check_webcam_and_voice(
    session_id: str,
    voice_tone_score: float = None,
    facial_emotion: EmotionState = None,
    spoken_text: str = None
) -> tuple:
    """
    Main entry called by api/main.py.
    Returns (GuardAlert, sonic_config dict).
    Now also returns behavior_analysis inside the alert object.
    """
    emotion_input = EmotionInput(
        session_id=session_id,
        voice_tone_score=voice_tone_score,
        facial_emotion=facial_emotion,
        text_signals=spoken_text
    )
    alert        = await analyze_emotion(emotion_input)
    sonic_config = get_sonic_config(alert.alert_level)
    grounding    = get_grounding_message(alert.alert_level)

    if grounding:
        sonic_config["grounding_message"] = grounding

    # attach behavior analysis to sonic config for frontend
    if hasattr(alert, "behavior_analysis") and alert.behavior_analysis:
        sonic_config["behavior_analysis"] = alert.behavior_analysis

    return alert, sonic_config