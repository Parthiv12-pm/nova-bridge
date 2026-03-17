"""
agents/sonic.py — Upgraded
============================
Nova's voice personality — upgraded with:
  - Proactive suggestion generator (Nova speaks without being asked)
  - Memory-personalized responses (uses preferred doctor/hospital name)
  - Behavior-aware tone (adjusts based on weekly pattern, not just single emotion)
  - Multilingual support (uses preferred_language from memory)
  - Richer fallback responses per skill type
  - Weekly distress pattern detection in response tone
  - Caregiver update messages

Called by:
  - api/main.py   (generate_voice_response, get_action_confirmation)
  - api/voice_routes.py (grounding, confirm-action endpoints)
"""

import boto3
import json
import os
from dotenv import load_dotenv
from botocore.config import Config
from models.schemas import EmotionState, IntentType
from core.session_memory import (
    get_preferences, get_full_memory,
    get_today_emotional_summary,
    get_missed_medicines, get_medicines_due_refill,
    get_proactive_suggestion,
)

load_dotenv()

# ── Bedrock client ────────────────────────────────────────────────────────────
bedrock = boto3.client(
    service_name="bedrock-runtime",
    region_name=os.getenv("BEDROCK_REGION", "us-east-1"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    config=Config(retries={"max_attempts": 1})
)


# ═══════════════════════════════════════════════════════════════════════════
#  NOVA SYSTEM PROMPT (upgraded)
# ═══════════════════════════════════════════════════════════════════════════

SONIC_SYSTEM_PROMPT = """
You are Nova Bridge — a calm, warm, and patient voice assistant
built specifically for elderly people and people with disabilities.

Your personality:
- You are warm, patient, and never rushed
- You remember what the user prefers and use their name
- You are proactive — you notice when something is wrong and offer help
- You adapt your language to the user's preferred language automatically
- You speak in simple, short sentences — never complex language

Your rules:
- Speak slowly and clearly at all times
- Never interrupt — always wait for the user to finish
- If the user speaks only a few words, respond gently and ask one simple question
- If the user sounds anxious, slow down even more and use grounding language
- If the user is in crisis, stay calm, reassure, and confirm help is coming
- Always confirm what action you are about to take before doing it
- Personalize responses — use their preferred hospital/doctor name if known
- If you know medicine is due, gently remind them
- Support all Indian languages — respond in the language the user speaks

Tone by emotion:
- calm    → warm, helpful, natural pace
- anxious → very slow, gentle, grounding phrases
- distress → acknowledge pain first, then help, very soft tone
- crisis  → extremely calm, very short sentences, immediate reassurance
"""


# ═══════════════════════════════════════════════════════════════════════════
#  VOICE CONFIG BY EMOTION (unchanged — backward compatible)
# ═══════════════════════════════════════════════════════════════════════════

def get_sonic_voice_config(emotion: EmotionState) -> dict:
    base = {
        "modelId":               "amazon.nova-sonic-v1:0",
        "turnTakingSensitivity": "LOW",
        "polyglot":              True,
    }
    configs = {
        EmotionState.CALM: {
            **base,
            "speakingRate":   "medium",
            "voiceStyle":     "warm",
            "responsePrefix": ""
        },
        EmotionState.ANXIOUS: {
            **base,
            "speakingRate":   "slow",
            "voiceStyle":     "gentle",
            "responsePrefix": "I'm right here with you. "
        },
        EmotionState.DISTRESS: {
            **base,
            "speakingRate":   "slow",
            "voiceStyle":     "grounding",
            "responsePrefix": "I hear you. You're safe. "
        },
        EmotionState.CRISIS: {
            **base,
            "speakingRate":   "slow",
            "voiceStyle":     "grounding",
            "responsePrefix": "I'm here. Help is on the way. "
        },
    }
    return configs.get(emotion, configs[EmotionState.CALM])


# ═══════════════════════════════════════════════════════════════════════════
#  FALLBACK RESPONSES (upgraded — memory-aware, more skill types)
# ═══════════════════════════════════════════════════════════════════════════

def _get_fallback(intent_key: str, emotion: EmotionState, prefs: dict = {}) -> str:
    """
    Returns a smart fallback response.
    Personalizes with memory preferences when available.
    """
    hospital = prefs.get("preferred_hospital", "your clinic")
    pharmacy = prefs.get("preferred_pharmacy", "your pharmacy")
    doctor   = prefs.get("preferred_doctor", "your doctor")
    caregiver = prefs.get("caregiver_name", "your caregiver")
    name      = prefs.get("user_name", "")
    greeting  = f"{name}, " if name else ""

    FALLBACKS = {
        "book_appointment": {
            EmotionState.CALM:    f"{greeting}I'll book your appointment at {hospital} right away.",
            EmotionState.ANXIOUS: f"I'm right here with you. I'll book your appointment with {doctor} now.",
            EmotionState.DISTRESS:f"I hear you. I'll get your appointment at {hospital} booked immediately.",
            EmotionState.CRISIS:  f"I'm here. I'm contacting {doctor} for urgent help right now.",
        },
        "order_medicine": {
            EmotionState.CALM:    f"{greeting}I'll order your medication from {pharmacy} right away.",
            EmotionState.ANXIOUS: f"I'm right here with you. I'll get your medicine ordered from {pharmacy}.",
            EmotionState.DISTRESS:f"I hear you. I'll order your medication from {pharmacy} now.",
            EmotionState.CRISIS:  f"I'm here. Ordering your medicine immediately.",
        },
        "send_message": {
            EmotionState.CALM:    f"{greeting}I'll send that message to {caregiver} for you.",
            EmotionState.ANXIOUS: f"I'm right here with you. I'll send a message to {caregiver} now.",
            EmotionState.DISTRESS:f"I hear you. I've notified {caregiver} right away.",
            EmotionState.CRISIS:  f"I'm here. {caregiver} has been contacted. You are not alone.",
        },
        "pay_bill": {
            EmotionState.CALM:    f"{greeting}I'll take care of that bill payment for you now.",
            EmotionState.ANXIOUS: f"I'm right here with you. I'll handle the bill payment.",
            EmotionState.DISTRESS:f"I hear you. I'll get that payment done for you right away.",
            EmotionState.CRISIS:  f"I'm here with you. I'll sort the payment. Focus on your breathing.",
        },
        "fill_form": {
            EmotionState.CALM:    f"{greeting}I'll fill in that form for you right away.",
            EmotionState.ANXIOUS: f"I'm right here. I'll handle the form — you don't need to worry.",
            EmotionState.DISTRESS:f"I hear you. Let me take care of that form for you.",
            EmotionState.CRISIS:  f"I'm here. I'll handle everything. You focus on staying calm.",
        },
        "taxi_booking": {
            EmotionState.CALM:    f"{greeting}I'll book a taxi for you right away.",
            EmotionState.ANXIOUS: f"I'm right here with you. I'll get a cab booked for you now.",
            EmotionState.DISTRESS:f"I hear you. I'm booking a taxi to get you help right away.",
            EmotionState.CRISIS:  f"I'm here. A taxi is being arranged for you right now.",
        },
        "default": {
            EmotionState.CALM:    f"{greeting}I understood you. Let me help with that right away.",
            EmotionState.ANXIOUS: f"I'm right here with you. I'll take care of this for you.",
            EmotionState.DISTRESS:f"I hear you. You're safe. I'll help you right now.",
            EmotionState.CRISIS:  f"I'm here. Help is on the way. You are not alone.",
        },
    }

    group = FALLBACKS.get(intent_key, FALLBACKS["default"])
    return group.get(emotion, FALLBACKS["default"][EmotionState.CALM])


# ═══════════════════════════════════════════════════════════════════════════
#  GENERATE VOICE RESPONSE (upgraded)
# ═══════════════════════════════════════════════════════════════════════════

async def generate_voice_response(
    user_text:  str,
    emotion:    EmotionState = EmotionState.CALM,
    context:    str = "",
    session_id: str = None,          # NEW — for memory personalization
) -> dict:
    """
    Generates Nova's spoken response.
    Now uses memory preferences to personalize the response.
    Adjusts tone based on weekly behavior pattern, not just current emotion.
    """
    config = get_sonic_voice_config(emotion)
    prefix = config.get("responsePrefix", "")

    # ── Load preferences for personalization ─────────────────────────────
    prefs = {}
    weekly_context = ""
    if session_id:
        prefs = get_preferences(session_id)
        weekly_context = _get_weekly_context(session_id)

    # ── Emotion-based instruction ─────────────────────────────────────────
    emotion_instruction = {
        EmotionState.CALM:     "Respond warmly and helpfully. Keep it concise.",
        EmotionState.ANXIOUS:  "Respond very slowly and gently. Use grounding language. Start with 'I'm right here with you.'",
        EmotionState.DISTRESS: "Acknowledge their pain first. Speak very softly. Reassure before helping.",
        EmotionState.CRISIS:   "Stay extremely calm. Reassure immediately. Maximum 2 short sentences.",
    }.get(emotion, "Respond warmly.")

    # ── Build personalization context ─────────────────────────────────────
    personalization = ""
    if prefs.get("user_name"):
        personalization += f"User's name: {prefs['user_name']}. "
    if prefs.get("preferred_hospital"):
        personalization += f"Preferred hospital: {prefs['preferred_hospital']}. "
    if prefs.get("preferred_doctor"):
        personalization += f"Preferred doctor: {prefs['preferred_doctor']}. "
    if prefs.get("preferred_language") and prefs["preferred_language"] != "en":
        personalization += f"IMPORTANT: Respond in {_language_name(prefs['preferred_language'])}. "

    # ── Assemble system prompt ────────────────────────────────────────────
    system = f"{SONIC_SYSTEM_PROMPT}\n\nCurrent emotion: {emotion.value}\n{emotion_instruction}"
    if personalization:
        system += f"\n\nUser preferences:\n{personalization}"
    if weekly_context:
        system += f"\n\nWeekly context:\n{weekly_context}"
    if context:
        system += f"\n\nScene context: {context}"

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 180,
        "system":     system,
        "messages":   [{"role": "user", "content": user_text or "Hello"}]
    })

    # ── Try Nova Bedrock first ────────────────────────────────────────────
    try:
        response = bedrock.invoke_model(
            modelId      = "us.amazon.nova-lite-v1:0",
            body         = body,
            contentType  = "application/json",
            accept       = "application/json"
        )
        result      = json.loads(response["body"].read())
        raw_text    = result["content"][0]["text"].strip()
        spoken_text = f"{prefix}{raw_text}" if prefix else raw_text

    except Exception as e:
        # ── Smart fallback ────────────────────────────────────────────────
        print(f"⚠️  SONIC fallback (AWS unavailable): {e}")
        intent_key  = _detect_intent_from_text(user_text or "")
        fallback    = _get_fallback(intent_key, emotion, prefs)
        spoken_text = f"{prefix}{fallback}" if prefix else fallback

    return {
        "spoken_text":  spoken_text,
        "sonic_config": config,
        "emotion":      emotion.value,
        "personalized": bool(prefs.get("user_name") or prefs.get("preferred_hospital")),
        "language":     prefs.get("preferred_language", "en"),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  PROACTIVE SUGGESTION GENERATOR (NEW)
#  Nova speaks without user asking — based on memory + behavior patterns
# ═══════════════════════════════════════════════════════════════════════════

async def generate_proactive_message(
    session_id: str,
    current_emotion: str = "calm"
) -> dict:
    """
    Generates a proactive message Nova says without being asked.
    Called by api/main.py after every pipeline run.
    Also called by frontend every 30 seconds via /dashboard/proactive-suggestion.

    Examples Nova says proactively:
      "You seem anxious today. Want me to book a check-up with Dr. Sharma?"
      "Reminder — you haven't taken Metformin yet today."
      "Your Amlodipine needs a refill in 3 days. Shall I order from MedPlus?"
      "Good morning! Want me to schedule your routine check-up?"
    """
    suggestion = get_proactive_suggestion(session_id, current_emotion)

    if not suggestion:
        return {
            "has_suggestion": False,
            "spoken_text":    None,
            "emotion":        current_emotion,
        }

    # generate warm voice wrapper for the suggestion
    prefs = get_preferences(session_id)
    try:
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 100,
            "system": (
                f"{SONIC_SYSTEM_PROMPT}\n\n"
                f"Deliver this suggestion warmly in 1-2 sentences: {suggestion}\n"
                f"Current emotion: {current_emotion}. "
                f"Be gentle and caring, not robotic."
            ),
            "messages": [{"role": "user", "content": "Nova, what do you suggest?"}]
        })
        response    = bedrock.invoke_model(
            modelId="us.amazon.nova-lite-v1:0", body=body,
            contentType="application/json", accept="application/json"
        )
        result      = json.loads(response["body"].read())
        spoken_text = result["content"][0]["text"].strip()
    except Exception:
        spoken_text = suggestion   # fallback: use raw suggestion text

    return {
        "has_suggestion": True,
        "spoken_text":    spoken_text,
        "raw_suggestion": suggestion,
        "emotion":        current_emotion,
        "language":       prefs.get("preferred_language", "en"),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  ACTION CONFIRMATION (upgraded — memory-personalized)
# ═══════════════════════════════════════════════════════════════════════════

def get_action_confirmation(
    intent_type: str,
    entities:    dict,
    session_id:  str = None,         # NEW — for memory personalization
) -> str:
    """
    Generates a confirmation message before Nova Act executes.
    Now uses memory to fill in preferred clinic/pharmacy names.
    """
    prefs = get_preferences(session_id) if session_id else {}

    # resolve clinic — entities first, then memory preference
    clinic = (
        entities.get("clinic") or
        entities.get("clinic_url", "").replace("https://www.", "").split(".")[0].title() or
        prefs.get("preferred_hospital") or
        "your clinic"
    )
    doctor   = entities.get("doctor") or prefs.get("preferred_doctor") or "your doctor"
    date     = entities.get("date", "tomorrow")
    med      = entities.get("medication_name", "your medication")
    pharmacy = entities.get("pharmacy") or prefs.get("preferred_pharmacy") or "your pharmacy"
    caregiver = prefs.get("caregiver_name", "your caregiver")

    confirmations = {
        "book_appointment": (
            f"I'll book an appointment at {clinic} with {doctor} for {date}. "
            "Shall I go ahead?"
        ),
        "order_medicine": (
            f"I'll order {med} from {pharmacy} for you. "
            "Shall I go ahead?"
        ),
        "send_message": (
            f"I'll send a message to {caregiver} for you. "
            "Shall I go ahead?"
        ),
        "fill_form": (
            "I'll fill in the form for you. "
            "Shall I go ahead?"
        ),
        "pay_bill": (
            f"I'll take care of that payment for you. "
            "Shall I go ahead?"
        ),
        "taxi_booking": (
            "I'll book a taxi for you. "
            "Shall I go ahead?"
        ),
    }
    return confirmations.get(
        intent_type,
        "I'll take care of that for you. Shall I go ahead?"
    )


# ═══════════════════════════════════════════════════════════════════════════
#  CAREGIVER UPDATE MESSAGE (NEW)
#  Nova tells the caregiver what it did — sent after every task
# ═══════════════════════════════════════════════════════════════════════════

def get_caregiver_update_message(
    intent_type:   str,
    result_summary: str,
    session_id:    str = None
) -> str:
    """
    Generates a message Nova sends to the caregiver after completing a task.
    Example: "Nova Bridge update: Appointment booked at Apollo for tomorrow 10am.
              Confirmation #NB-X7K2P — Ramesh Kumar"
    """
    prefs = get_preferences(session_id) if session_id else {}
    name  = prefs.get("user_name", "your family member")
    ts    = _current_time()

    messages = {
        "book_appointment": f"Nova Bridge: Appointment booked for {name} at {ts}. {result_summary}",
        "order_medicine":   f"Nova Bridge: Medicine ordered for {name} at {ts}. {result_summary}",
        "pay_bill":         f"Nova Bridge: Bill paid for {name} at {ts}. {result_summary}",
        "send_message":     f"Nova Bridge: Message sent by {name} at {ts}.",
        "fill_form":        f"Nova Bridge: Form completed for {name} at {ts}. {result_summary}",
    }
    return messages.get(
        intent_type,
        f"Nova Bridge: Task completed for {name} at {ts}. {result_summary}"
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GROUNDING MESSAGES (unchanged — backward compatible)
# ═══════════════════════════════════════════════════════════════════════════

GROUNDING_MESSAGES = {
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

def get_grounding_message(emotion: EmotionState) -> str:
    return GROUNDING_MESSAGES.get(emotion, "")


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _detect_intent_from_text(text: str) -> str:
    """Detects likely intent from user text for fallback selection."""
    text = text.lower()
    if any(w in text for w in ["doctor", "appointment", "pain", "clinic", "hospital"]):
        return "book_appointment"
    if any(w in text for w in ["medicine", "tablet", "pill", "refill", "pharmacy"]):
        return "order_medicine"
    if any(w in text for w in ["message", "scared", "alone", "help", "send", "call"]):
        return "send_message"
    if any(w in text for w in ["bill", "electricity", "pay", "payment"]):
        return "pay_bill"
    if any(w in text for w in ["taxi", "cab", "ride", "auto", "uber", "ola"]):
        return "taxi_booking"
    if any(w in text for w in ["form", "fill", "document", "government"]):
        return "fill_form"
    return "default"


def _get_weekly_context(session_id: str) -> str:
    """
    Builds a brief weekly behavior context string for the system prompt.
    Helps Nova adjust its tone based on the week's pattern.
    """
    try:
        today = get_today_emotional_summary(session_id)
        distress_today = today.get("distress_count", 0)
        missed_meds    = get_missed_medicines(session_id)
        due_refills    = get_medicines_due_refill(session_id)

        parts = []
        if distress_today >= 2:
            parts.append(f"User has had {distress_today} distress events today — be extra gentle.")
        if missed_meds:
            names = ", ".join([m["name"] for m in missed_meds[:2]])
            parts.append(f"User has not taken: {names} — gently remind if relevant.")
        if due_refills:
            names = ", ".join([m["name"] for m in due_refills[:2]])
            parts.append(f"Medicine refill due soon: {names}.")

        return " ".join(parts) if parts else ""
    except Exception:
        return ""


def _language_name(code: str) -> str:
    """Converts language code to full name."""
    names = {
        "en": "English", "hi": "Hindi", "gu": "Gujarati",
        "ta": "Tamil",   "te": "Telugu", "bn": "Bengali",
        "mr": "Marathi", "kn": "Kannada", "ml": "Malayalam",
    }
    return names.get(code, "English")


def _current_time() -> str:
    from datetime import datetime
    return datetime.now().strftime("%B %d at %I:%M %p")