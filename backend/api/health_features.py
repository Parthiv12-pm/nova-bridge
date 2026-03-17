"""
nova_bridge/api/health_features.py
===================================
Advanced AI-Powered Health Features with SQLite persistence.

FEATURES:
- Psychology report from patient conversations
- Auto-inform relatives on distress / depression
- Medicine missed → notify registered contacts
- Depression detection → contact family/friend
- Monthly combined activity charts (PNG + base64)
- Amazon Nova (primary) + Groq (fallback) AI
- All endpoints error-safe
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import json
import sqlite3
import os
import math
import random
import traceback
import base64
import io

router = APIRouter(prefix="/health", tags=["Health Features"])

# ═══════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════

DB_PATH = "nova_bridge_health.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    try:
        conn = get_db()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS relatives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                relationship TEXT DEFAULT 'family',
                notify_on TEXT DEFAULT '["distress","crisis","depression","medicine_missed"]',
                registered_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS medicines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                name TEXT NOT NULL,
                dose TEXT NOT NULL,
                times TEXT NOT NULL,
                days TEXT DEFAULT '["mon","tue","wed","thu","fri","sat","sun"]',
                category TEXT DEFAULT 'general',
                color TEXT DEFAULT '#4361ee',
                taken_today INTEGER DEFAULT 0,
                last_taken TEXT,
                refill_count INTEGER DEFAULT 30,
                refill_remaining INTEGER DEFAULT 30,
                consecutive_missed INTEGER DEFAULT 0,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS mental_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                mood INTEGER NOT NULL,
                notes TEXT,
                activities TEXT DEFAULT '[]',
                energy_level INTEGER DEFAULT 5,
                anxiety_level INTEGER DEFAULT 3,
                sleep_hours REAL DEFAULT 7,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                date TEXT NOT NULL,
                ai_analysis TEXT,
                sentiment TEXT DEFAULT 'neutral'
            );
            CREATE TABLE IF NOT EXISTS vitals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                bp_systolic INTEGER,
                bp_diastolic INTEGER,
                pulse INTEGER,
                blood_sugar REAL,
                temperature REAL,
                oxygen_saturation INTEGER,
                weight REAL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                ai_assessment TEXT
            );
            CREATE TABLE IF NOT EXISTS pain_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                pain_level INTEGER NOT NULL,
                body_location TEXT NOT NULL,
                pain_type TEXT DEFAULT 'aching',
                duration_minutes INTEGER DEFAULT 0,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                ai_recommendation TEXT
            );
            CREATE TABLE IF NOT EXISTS sleep_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                sleep_hours REAL NOT NULL,
                quality INTEGER NOT NULL,
                bedtime TEXT,
                wake_time TEXT,
                disturbances INTEGER DEFAULT 0,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                ai_tip TEXT
            );
            CREATE TABLE IF NOT EXISTS hydration_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                glasses INTEGER NOT NULL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                doctor_name TEXT NOT NULL,
                specialty TEXT DEFAULT 'General',
                appointment_date TEXT NOT NULL,
                appointment_time TEXT NOT NULL,
                hospital TEXT DEFAULT '',
                notes TEXT,
                status TEXT DEFAULT 'upcoming',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS symptoms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                symptom_list TEXT NOT NULL,
                severity INTEGER NOT NULL,
                duration_hours INTEGER DEFAULT 1,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                ai_assessment TEXT,
                recommended_action TEXT,
                urgency_level TEXT DEFAULT 'low'
            );
            CREATE TABLE IF NOT EXISTS health_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT DEFAULT 'medium',
                is_read INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS journal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                content TEXT NOT NULL,
                mood_tag TEXT DEFAULT 'neutral',
                ai_sentiment TEXT,
                ai_response TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS comm_phrases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                label TEXT NOT NULL,
                phrase TEXT NOT NULL,
                icon TEXT DEFAULT '💬',
                category TEXT DEFAULT 'basic',
                use_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS fall_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                severity TEXT DEFAULT 'medium',
                responded INTEGER DEFAULT 0,
                location TEXT DEFAULT 'home'
            );
            CREATE TABLE IF NOT EXISTS daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                report_date TEXT NOT NULL,
                report_data TEXT NOT NULL,
                ai_summary TEXT,
                health_score INTEGER DEFAULT 0,
                generated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                speaker TEXT DEFAULT 'patient',
                message TEXT NOT NULL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                emotion_detected TEXT DEFAULT 'neutral',
                keywords TEXT DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS psychology_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                report_date TEXT NOT NULL,
                emotional_state TEXT,
                depression_score INTEGER DEFAULT 0,
                anxiety_score INTEGER DEFAULT 0,
                stress_score INTEGER DEFAULT 0,
                key_concerns TEXT DEFAULT '[]',
                ai_assessment TEXT,
                recommendations TEXT DEFAULT '[]',
                family_alert_sent INTEGER DEFAULT 0,
                generated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS family_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                relative_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                reason TEXT NOT NULL,
                message TEXT NOT NULL,
                alert_type TEXT DEFAULT 'info',
                sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'sent'
            );
        """)
        conn.commit()
        conn.close()
        print("✅ Nova Bridge Health DB initialized")
    except Exception as e:
        print(f"DB init error: {e}")

init_db()

# ── In-memory fallback ───────────────────────────────
_relatives:   dict = {}
_medicines:   dict = {}
_mental_log:  dict = {}
_comm_phrases:dict = {}


# ═══════════════════════════════════════════════════════
#  AI ENGINE — Amazon Nova (primary) → Groq (fallback)
# ═══════════════════════════════════════════════════════

def ai_analyze(prompt: str, context: str = "", mode: str = "health") -> str:
    """
    Primary:  Amazon Nova via boto3 (bedrock-runtime)
    Fallback: Groq llama3
    Final:    Rule-based (always works, no API needed)
    """

    system_prompt = (
        "You are Nova Bridge — an empathetic AI health assistant for elderly and disabled patients. "
        "Respond in 1-3 sentences. Be warm, medically aware, and actionable. "
        "Never be alarming. Always encourage seeking professional help for serious issues."
    )

    full_prompt = f"{context}\n\n{prompt}".strip() if context else prompt

    # ── Try Amazon Nova (Bedrock) ────────────────────
    try:
        import boto3
        import json as _json
        bedrock = boto3.client(
            service_name="bedrock-runtime",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        )
        body = _json.dumps({
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": full_prompt}]}
            ],
            "system": [{"type": "text", "text": system_prompt}],
            "max_tokens": 200,
            "anthropic_version": "bedrock-2023-05-31"
        })
        response = bedrock.invoke_model(
            modelId="amazon.nova-micro-v1:0",
            body=body,
            contentType="application/json",
            accept="application/json"
        )
        result = _json.loads(response["body"].read())
        text = result.get("content", [{}])[0].get("text", "").strip()
        if text:
            return text
    except Exception as e:
        print(f"⚠️ Amazon Nova unavailable: {e}")

    # ── Try Groq ─────────────────────────────────────
    try:
        import groq as _groq
        client = _groq.Groq(api_key=os.getenv("GROQ_API_KEY", ""))
        response = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": full_prompt}
            ],
            max_tokens=200,
            temperature=0.7
        )
        text = response.choices[0].message.content.strip()
        if text:
            return text
    except Exception as e:
        print(f"⚠️ Groq unavailable: {e}")

    # ── Rule-based fallback ───────────────────────────
    return _rule_based_ai(prompt)


def _rule_based_ai(prompt: str) -> str:
    p = prompt.lower()
    if any(w in p for w in ["depress", "hopeless", "worthless", "suicid", "end my life"]):
        return "I hear you and I care deeply. Please reach out to someone you trust right now — you are not alone and help is available."
    if "pain" in p and any(x in p for x in ["8","9","10","severe","unbearable"]):
        return "Severe pain needs attention. Please rest and contact your doctor or family immediately."
    if any(w in p for w in ["anxious","anxiety","panic","scared","fear"]):
        return "Take slow deep breaths — in for 4 counts, hold for 4, out for 4. You are safe and I am here with you."
    if "medicine" in p and "miss" in p:
        return "Missed medications can affect your health. Please take your medicine now if it's not too late, or contact your doctor."
    if "mood" in p and any(x in p for x in ["1","2","3","bad","terrible","sad"]):
        return "I'm sorry you're feeling this way. Would you like me to connect you with someone who cares about you?"
    if any(w in p for w in ["sleep","insomnia","tired","exhausted"]):
        return "Rest is vital for recovery. Try a consistent bedtime, dim lights, and avoid screens 30 minutes before sleep."
    if any(w in p for w in ["lonely","alone","isolated","nobody"]):
        return "Feeling lonely is hard. Would you like me to call one of your family members so you can talk to someone?"
    if any(w in p for w in ["bp","blood pressure","hypertension"]):
        return "Monitor your blood pressure daily and keep a log to share with your doctor at your next visit."
    if any(w in p for w in ["sugar","glucose","diabetes"]):
        return "Keep tracking your blood sugar and maintain a balanced diet. Consistency is key for managing diabetes."
    if any(w in p for w in ["water","hydrat","drink"]):
        return "Aim for 8 glasses of water a day. Staying hydrated improves energy and helps your medicines work better."
    return "Thank you for sharing with me. Your health matters — I am always here to help you stay well."


# ═══════════════════════════════════════════════════════
#  FAMILY NOTIFICATION ENGINE
# ═══════════════════════════════════════════════════════

def notify_relatives(session_id: str, reason: str, message: str,
                     alert_type: str = "info", notify_on_event: str = "distress"):
    """
    Send notifications to all registered relatives who subscribed to this event.
    In production: integrate Twilio SMS / WhatsApp / email here.
    Logs every notification to DB.
    """
    try:
        conn = get_db()
        relatives = conn.execute(
            "SELECT * FROM relatives WHERE session_id=?", (session_id,)
        ).fetchall()

        notified = []
        for rel in relatives:
            try:
                notify_on = json.loads(rel["notify_on"] or '[]')
            except Exception:
                notify_on = ["distress", "crisis"]

            if notify_on_event in notify_on or alert_type == "emergency":
                sms_text = (
                    f"[Nova Bridge Alert] {rel['name']}, "
                    f"your family member needs your attention.\n"
                    f"Reason: {reason}\n"
                    f"Message: {message}\n"
                    f"Please call or visit them."
                )
                # ── Production hook: uncomment & configure ──
                # twilio_client.messages.create(
                #     body=sms_text, from_=TWILIO_FROM, to=rel["phone"]
                # )
                print(f"📲 NOTIFY → {rel['name']} ({rel['phone']}): {reason}")

                conn.execute(
                    """INSERT INTO family_notifications
                       (session_id,relative_name,phone,reason,message,alert_type)
                       VALUES (?,?,?,?,?,?)""",
                    (session_id, rel["name"], rel["phone"], reason, message, alert_type)
                )
                notified.append({"name": rel["name"], "phone": rel["phone"]})

        conn.commit()
        conn.close()
        return notified
    except Exception as e:
        print(f"Notification error: {e}")
        return []


# ═══════════════════════════════════════════════════════
#  MODELS
# ═══════════════════════════════════════════════════════

class Relative(BaseModel):
    name:         str
    phone:        str
    relationship: str = "family"
    notify_on:    List[str] = ["distress", "crisis", "depression", "medicine_missed"]

class MedicineReminder(BaseModel):
    name:         str
    dose:         str
    times:        List[str]
    days:         List[str] = ["mon","tue","wed","thu","fri","sat","sun"]
    category:     str = "general"
    color:        str = "#4361ee"
    refill_count: int = 30

class MentalCheckIn(BaseModel):
    mood:          int
    notes:         Optional[str] = None
    activities:    List[str] = []
    energy_level:  int = 5
    anxiety_level: int = 3
    sleep_hours:   float = 7.0

class ConversationLog(BaseModel):
    message:  str
    speaker:  str = "patient"

class VitalsEntry(BaseModel):
    bp_systolic:       Optional[int]   = None
    bp_diastolic:      Optional[int]   = None
    pulse:             Optional[int]   = None
    blood_sugar:       Optional[float] = None
    temperature:       Optional[float] = None
    oxygen_saturation: Optional[int]   = None
    weight:            Optional[float] = None
    notes:             Optional[str]   = None

class PainEntry(BaseModel):
    pain_level:       int
    body_location:    str
    pain_type:        str = "aching"
    duration_minutes: int = 0
    notes:            Optional[str] = None

class SleepEntry(BaseModel):
    sleep_hours:  float
    quality:      int
    bedtime:      Optional[str] = None
    wake_time:    Optional[str] = None
    disturbances: int = 0

class HydrationEntry(BaseModel):
    glasses: int

class AppointmentEntry(BaseModel):
    doctor_name:      str
    specialty:        str = "General"
    appointment_date: str
    appointment_time: str
    hospital:         str = ""
    notes:            Optional[str] = None

class SymptomEntry(BaseModel):
    symptom_list:   List[str]
    severity:       int
    duration_hours: int = 1

class JournalEntry(BaseModel):
    content:  str
    mood_tag: str = "neutral"

class CommunicationPhrase(BaseModel):
    label:    str
    phrase:   str
    icon:     str = "💬"
    category: str = "basic"


# ═══════════════════════════════════════════════════════
#  PSYCHOLOGY — conversation logging + report generation
# ═══════════════════════════════════════════════════════

DEPRESSION_KEYWORDS = [
    "hopeless","worthless","no point","end it","give up","useless","nobody cares",
    "want to die","can't go on","empty","numb","dark","suicid","hate myself",
    "burden","better off without me","tired of living","no future"
]
ANXIETY_KEYWORDS = [
    "panic","can't breathe","heart racing","terrified","overwhelmed","spiraling",
    "scared","anxious","nervous","worry","dread","fear","shaking","trembling"
]
STRESS_KEYWORDS = [
    "stressed","pressure","too much","can't cope","breaking down","exhausted",
    "falling apart","losing control","no energy","burnt out","overwhelmed"
]
LONELINESS_KEYWORDS = [
    "alone","lonely","nobody","no one","isolated","forgotten","abandoned",
    "no friends","no family","nobody visits","nobody calls"
]
POSITIVE_KEYWORDS = [
    "happy","good","great","better","wonderful","grateful","thankful",
    "improved","hopeful","positive","cheerful","excited","loving"
]


@router.post("/conversation/log")
async def log_conversation(session_id: str, log: ConversationLog):
    """
    Log every patient message.
    Detects depression/anxiety/stress keywords.
    Auto-notifies relatives if concerning content found.
    """
    try:
        msg_lower = log.message.lower()

        # Score keywords
        dep_hits    = [w for w in DEPRESSION_KEYWORDS if w in msg_lower]
        anx_hits    = [w for w in ANXIETY_KEYWORDS    if w in msg_lower]
        str_hits    = [w for w in STRESS_KEYWORDS     if w in msg_lower]
        lone_hits   = [w for w in LONELINESS_KEYWORDS if w in msg_lower]
        pos_hits    = [w for w in POSITIVE_KEYWORDS   if w in msg_lower]

        # Emotion detection
        if dep_hits:
            emotion = "depression"
        elif anx_hits:
            emotion = "anxiety"
        elif str_hits:
            emotion = "stress"
        elif lone_hits:
            emotion = "loneliness"
        elif pos_hits:
            emotion = "positive"
        else:
            emotion = "neutral"

        all_keywords = dep_hits + anx_hits + str_hits + lone_hits
        conn = get_db()
        conn.execute(
            """INSERT INTO conversations
               (session_id,speaker,message,emotion_detected,keywords)
               VALUES (?,?,?,?,?)""",
            (session_id, log.speaker, log.message, emotion, json.dumps(all_keywords))
        )
        conn.commit()
        conn.close()

        # Auto-notify relatives for concerning content
        notified = []
        if dep_hits:
            ai_msg = ai_analyze(
                f"Patient said something concerning: '{log.message}'. "
                "They may be experiencing depression. Give a very brief empathetic response."
            )
            notified = notify_relatives(
                session_id,
                reason="Depression indicators detected in patient conversation",
                message=(
                    f"Patient expressed: '{log.message[:100]}...'\n"
                    f"Keywords detected: {', '.join(dep_hits)}\n"
                    "Please check on them."
                ),
                alert_type="critical",
                notify_on_event="depression"
            )
            _create_alert(session_id, "depression_detected",
                f"Depression keywords detected: {', '.join(dep_hits)}", "critical")
            return {
                "logged": True,
                "emotion": emotion,
                "ai_response": ai_msg,
                "alert_level": "critical",
                "family_notified": notified,
                "keywords_detected": dep_hits,
                "action": "Family has been notified. Please stay with the patient."
            }

        if lone_hits:
            notified = notify_relatives(
                session_id,
                reason="Patient is feeling lonely and isolated",
                message=(
                    f"Patient said: '{log.message[:100]}'\n"
                    "Please call or visit them soon."
                ),
                alert_type="warning",
                notify_on_event="distress"
            )

        ai_response = ai_analyze(
            f"Patient said: '{log.message}'. Emotion: {emotion}. "
            "Give a warm supportive response in 1-2 sentences."
        )

        return {
            "logged": True,
            "emotion": emotion,
            "ai_response": ai_response,
            "alert_level": "high" if anx_hits else "medium" if str_hits else "low",
            "family_notified": notified,
            "keywords_detected": all_keywords
        }

    except Exception as e:
        print(f"Conversation log error: {e}")
        return {"logged": False, "error": str(e), "emotion": "neutral", "ai_response": ""}


@router.get("/conversation/history/{session_id}")
async def conversation_history(session_id: str):
    """Get full conversation history with emotion analysis."""
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT 50",
            (session_id,)
        ).fetchall()
        conn.close()
        convs = []
        for r in rows:
            d = dict(r)
            try:
                d["keywords"] = json.loads(d.get("keywords") or "[]")
            except Exception:
                d["keywords"] = []
            convs.append(d)

        # Emotion breakdown
        emotions = [c["emotion_detected"] for c in convs]
        breakdown = {e: emotions.count(e) for e in set(emotions)}

        return {
            "history": list(reversed(convs)),
            "total": len(convs),
            "emotion_breakdown": breakdown
        }
    except Exception as e:
        return {"history": [], "total": 0, "emotion_breakdown": {}, "error": str(e)}


@router.post("/psychology/report/{session_id}")
async def generate_psychology_report(session_id: str):
    """
    Generate AI psychology report from patient conversations + mood logs.
    Automatically notifies family if depression/crisis detected.
    """
    try:
        conn = get_db()

        # Get last 30 conversations
        convs = conn.execute(
            "SELECT * FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT 30",
            (session_id,)
        ).fetchall()

        # Get last 7 mood entries
        moods = conn.execute(
            "SELECT mood, notes, anxiety_level, energy_level, sentiment FROM mental_log "
            "WHERE session_id=? ORDER BY id DESC LIMIT 7",
            (session_id,)
        ).fetchall()

        # Get last 5 journal entries
        journals = conn.execute(
            "SELECT content, ai_sentiment FROM journal_entries "
            "WHERE session_id=? ORDER BY id DESC LIMIT 5",
            (session_id,)
        ).fetchall()

        conn.close()

        # Score depression, anxiety, stress
        dep_score  = 0
        anx_score  = 0
        str_score  = 0
        key_concerns = []

        for c in convs:
            try:
                kw = json.loads(c["keywords"] or "[]")
            except Exception:
                kw = []
            emo = c.get("emotion_detected", "neutral")
            if emo == "depression":   dep_score  += 3
            elif emo == "anxiety":    anx_score  += 2
            elif emo == "stress":     str_score  += 2
            elif emo == "loneliness": dep_score  += 1
            for k in kw:
                if k not in key_concerns:
                    key_concerns.append(k)

        # Mood average
        avg_mood = 0
        if moods:
            avg_mood = sum(m["mood"] for m in moods) / len(moods)
            if avg_mood <= 3:     dep_score += 5
            elif avg_mood <= 5:   dep_score += 2
            avg_anx = sum(m["anxiety_level"] or 0 for m in moods) / len(moods)
            if avg_anx >= 7:      anx_score += 4

        # Normalize scores (0-100)
        dep_score  = min(100, dep_score  * 5)
        anx_score  = min(100, anx_score  * 6)
        str_score  = min(100, str_score  * 6)

        # Emotional state label
        if dep_score >= 60:
            emotional_state = "Depressive Episode — Immediate Support Needed"
        elif dep_score >= 35:
            emotional_state = "Moderate Low Mood — Monitoring Required"
        elif anx_score >= 60:
            emotional_state = "High Anxiety — Therapeutic Support Recommended"
        elif anx_score >= 30:
            emotional_state = "Mild Anxiety — Lifestyle Support Helpful"
        elif avg_mood >= 7:
            emotional_state = "Positive & Stable — Doing Well"
        else:
            emotional_state = "Generally Stable — Regular Check-ins Advised"

        # Build context for AI
        conv_text = " | ".join([c["message"][:80] for c in list(convs)[:10]]) if convs else "No conversations"
        mood_text = f"Average mood {round(avg_mood,1)}/10 over last {len(moods)} check-ins."
        journal_text = " ".join([j["content"][:60] for j in journals]) if journals else "No journal entries"

        ai_prompt = (
            f"Patient psychology analysis:\n"
            f"Conversations: {conv_text}\n"
            f"Mood: {mood_text}\n"
            f"Journal: {journal_text}\n"
            f"Depression score: {dep_score}/100. Anxiety: {anx_score}/100. Stress: {str_score}/100.\n"
            f"Key concerns: {', '.join(key_concerns[:5]) if key_concerns else 'none'}.\n"
            "Write a professional 3-sentence psychology assessment and 2 concrete recommendations."
        )
        ai_assessment = ai_analyze(ai_prompt, mode="psychology")

        # Recommendations
        recommendations = []
        if dep_score >= 60:
            recommendations.append("Immediate family support and professional counseling recommended")
            recommendations.append("Daily check-ins with Nova Bridge and a trusted person")
        elif dep_score >= 35:
            recommendations.append("Increase social interaction and physical activity")
            recommendations.append("Schedule a mental health consultation")
        if anx_score >= 40:
            recommendations.append("Practice daily breathing exercises and mindfulness")
            recommendations.append("Reduce stimulants and maintain consistent sleep schedule")
        if str_score >= 40:
            recommendations.append("Identify stress triggers and discuss with caregiver")
        if not recommendations:
            recommendations = [
                "Maintain regular mood check-ins",
                "Continue positive daily routines",
                "Stay connected with family and friends"
            ]

        # Save report
        conn = get_db()
        conn.execute(
            """INSERT INTO psychology_reports
               (session_id,report_date,emotional_state,depression_score,anxiety_score,
                stress_score,key_concerns,ai_assessment,recommendations)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (session_id, datetime.now().strftime("%Y-%m-%d"), emotional_state,
             dep_score, anx_score, str_score, json.dumps(key_concerns[:10]),
             ai_assessment, json.dumps(recommendations))
        )
        conn.commit()
        conn.close()

        # Auto-notify family if depression is high
        family_alerted = []
        if dep_score >= 60:
            family_alerted = notify_relatives(
                session_id,
                reason="High depression score detected in psychology report",
                message=(
                    f"Nova Bridge psychology analysis detected:\n"
                    f"Emotional State: {emotional_state}\n"
                    f"Depression Score: {dep_score}/100\n"
                    f"Key Concerns: {', '.join(key_concerns[:5]) if key_concerns else 'none'}\n"
                    "Please contact your family member immediately."
                ),
                alert_type="critical",
                notify_on_event="depression"
            )
            _create_alert(session_id, "psychology_crisis",
                f"Psychology report: Depression {dep_score}/100 — {emotional_state}", "critical")
        elif dep_score >= 35:
            notify_relatives(
                session_id,
                reason="Moderate low mood detected",
                message=f"Patient mood has been low. Depression score: {dep_score}/100. Please check in on them.",
                alert_type="warning",
                notify_on_event="distress"
            )

        return {
            "session_id": session_id,
            "report_date": datetime.now().strftime("%Y-%m-%d"),
            "emotional_state": emotional_state,
            "scores": {
                "depression": dep_score,
                "anxiety": anx_score,
                "stress": str_score,
                "overall_risk": round((dep_score * 0.5 + anx_score * 0.3 + str_score * 0.2))
            },
            "key_concerns": key_concerns[:10],
            "ai_assessment": ai_assessment,
            "recommendations": recommendations,
            "family_alerted": family_alerted,
            "generated_at": datetime.now().isoformat()
        }

    except Exception as e:
        print(f"Psychology report error: {traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/psychology/reports/{session_id}")
async def get_psychology_reports(session_id: str):
    """Get all psychology reports for a session."""
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM psychology_reports WHERE session_id=? ORDER BY id DESC LIMIT 10",
            (session_id,)
        ).fetchall()
        conn.close()
        reports = []
        for r in rows:
            d = dict(r)
            for field in ["key_concerns", "recommendations"]:
                try:
                    d[field] = json.loads(d.get(field) or "[]")
                except Exception:
                    d[field] = []
            reports.append(d)
        return {"reports": reports, "total": len(reports)}
    except Exception as e:
        return {"reports": [], "total": 0, "error": str(e)}


# ═══════════════════════════════════════════════════════
#  RELATIVES
# ═══════════════════════════════════════════════════════

@router.post("/relatives/register")
async def register_relative(session_id: str, relative: Relative):
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO relatives (session_id,name,phone,relationship,notify_on) VALUES (?,?,?,?,?)",
            (session_id, relative.name, relative.phone,
             relative.relationship, json.dumps(relative.notify_on))
        )
        conn.commit()
        conn.close()
        if session_id not in _relatives:
            _relatives[session_id] = []
        _relatives[session_id].append(relative.dict())
        return {"status": "registered", "name": relative.name,
                "message": f"{relative.name} will be notified in emergencies."}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/relatives/{session_id}")
async def get_relatives(session_id: str):
    try:
        conn = get_db()
        rows = conn.execute("SELECT * FROM relatives WHERE session_id=?", (session_id,)).fetchall()
        conn.close()
        relatives = []
        for r in rows:
            try:
                notify_on = json.loads(r["notify_on"] or "[]")
            except Exception:
                notify_on = []
            relatives.append({
                "id": r["id"], "name": r["name"], "phone": r["phone"],
                "relationship": r["relationship"], "notify_on": notify_on,
                "registered_at": r["registered_at"]
            })
        return {"relatives": relatives, "total": len(relatives)}
    except Exception as e:
        return {"relatives": [], "total": 0, "error": str(e)}


@router.post("/relatives/call")
async def call_relative(session_id: str, emotion: str = "distress"):
    try:
        conn = get_db()
        rows = conn.execute("SELECT * FROM relatives WHERE session_id=?", (session_id,)).fetchall()
        conn.close()
        notified = []
        for rel in rows:
            try:
                notify_on = json.loads(rel["notify_on"] or "[]")
            except Exception:
                notify_on = ["distress", "crisis"]
            if emotion in notify_on or emotion == "crisis":
                notified.append({
                    "name": rel["name"], "phone": rel["phone"],
                    "status": "call_initiated",
                    "timestamp": datetime.now().isoformat()
                })
                print(f"📞 CALLING {rel['name']} at {rel['phone']} — emotion: {emotion}")
        if emotion in ["crisis", "distress"]:
            _create_alert(session_id, "emergency_call",
                f"Emergency call for {len(notified)} contacts — {emotion}", "high")
        return {"called": len(notified), "notified": notified,
                "emotion": emotion, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"called": 0, "notified": [], "error": str(e)}


@router.get("/family/notifications/{session_id}")
async def get_family_notifications(session_id: str):
    """Get all family notification history."""
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM family_notifications WHERE session_id=? ORDER BY id DESC LIMIT 30",
            (session_id,)
        ).fetchall()
        conn.close()
        return {"notifications": [dict(r) for r in rows], "total": len(rows)}
    except Exception as e:
        return {"notifications": [], "total": 0, "error": str(e)}


# ═══════════════════════════════════════════════════════
#  MEDICINE — with missed-dose family notification
# ═══════════════════════════════════════════════════════

MEDICINE_CONFLICTS = {
    "warfarin":     ["aspirin","ibuprofen","naproxen"],
    "metformin":    ["alcohol"],
    "lisinopril":   ["potassium","spironolactone"],
    "atorvastatin": ["gemfibrozil","niacin"],
}


@router.post("/medicine/add")
async def add_medicine(session_id: str, medicine: MedicineReminder):
    try:
        conn = get_db()
        existing = conn.execute(
            "SELECT name FROM medicines WHERE session_id=?", (session_id,)
        ).fetchall()
        existing_names = [r["name"].lower() for r in existing]
        conflicts = []
        med_lower = medicine.name.lower()
        for drug, conflict_list in MEDICINE_CONFLICTS.items():
            if drug in med_lower:
                for c in conflict_list:
                    if any(c in e for e in existing_names):
                        conflicts.append(c)
            for c in conflict_list:
                if c in med_lower and drug in existing_names:
                    conflicts.append(drug)

        conn.execute(
            """INSERT INTO medicines
               (session_id,name,dose,times,days,category,color,refill_count,refill_remaining)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (session_id, medicine.name, medicine.dose, json.dumps(medicine.times),
             json.dumps(medicine.days), medicine.category, medicine.color,
             medicine.refill_count, medicine.refill_count)
        )
        conn.commit()
        conn.close()

        ai_note = (
            f"⚠️ Potential interaction with: {', '.join(conflicts)}. Consult your doctor."
            if conflicts else
            ai_analyze(f"Patient added {medicine.name} {medicine.dose}. Brief helpful tip.")
        )
        return {"status": "added", "medicine": medicine.name,
                "conflicts_detected": conflicts, "ai_note": ai_note}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/medicine/schedule/{session_id}")
async def get_medicine_schedule(session_id: str):
    try:
        conn = get_db()
        rows = conn.execute("SELECT * FROM medicines WHERE session_id=?", (session_id,)).fetchall()
        conn.close()
        schedule = []
        now = datetime.now()
        due_now = []
        low_refill = []

        for r in rows:
            try:
                times = json.loads(r["times"] or "[]")
            except Exception:
                times = []
            med = {
                "id": r["id"], "name": r["name"], "dose": r["dose"],
                "times": times, "category": r["category"], "color": r["color"],
                "taken_today": bool(r["taken_today"]), "last_taken": r["last_taken"],
                "refill_remaining": r["refill_remaining"], "refill_count": r["refill_count"],
            }
            schedule.append(med)
            for t in times:
                try:
                    h, m = map(int, t.split(":"))
                    diff = abs((now.hour * 60 + now.minute) - (h * 60 + m))
                    if diff <= 30 and not r["taken_today"]:
                        due_now.append({"name": r["name"], "dose": r["dose"], "time": t})
                except Exception:
                    pass
            if r["refill_remaining"] and r["refill_remaining"] <= 7:
                low_refill.append(r["name"])

        total = len(schedule)
        taken = sum(1 for m in schedule if m["taken_today"])
        adherence = round(taken / total * 100, 1) if total else 100

        return {
            "session_id": session_id, "schedule": schedule,
            "due_now": due_now, "low_refill_alert": low_refill,
            "adherence_today": adherence,
            "reminder_message": (
                f"Time to take {due_now[0]['name']} — {due_now[0]['dose']}"
                if due_now else None
            ),
            "refill_message": (
                f"Refill needed soon: {', '.join(low_refill)}" if low_refill else None
            )
        }
    except Exception as e:
        return {"session_id": session_id, "schedule": [], "due_now": [],
                "low_refill_alert": [], "adherence_today": 100, "error": str(e)}


@router.post("/medicine/taken")
async def mark_medicine_taken(session_id: str, medicine_name: str):
    try:
        now = datetime.now().isoformat()
        conn = get_db()
        conn.execute(
            """UPDATE medicines SET taken_today=1, last_taken=?,
               consecutive_missed=0,
               refill_remaining=MAX(0,refill_remaining-1)
               WHERE session_id=? AND LOWER(name)=LOWER(?)""",
            (now, session_id, medicine_name)
        )
        conn.commit()
        conn.close()
        return {"status": "marked", "medicine": medicine_name,
                "timestamp": now, "message": "Great job taking your medicine on time! 💊"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/medicine/check-missed/{session_id}")
async def check_missed_medicines(session_id: str):
    """
    Check for missed medicines and notify relatives if consecutive misses >= 2.
    Call this endpoint daily (e.g., at 10pm via a scheduler).
    """
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM medicines WHERE session_id=? AND taken_today=0",
            (session_id,)
        ).fetchall()

        missed = []
        notified = []
        for r in rows:
            missed.append(r["name"])
            consecutive = (r["consecutive_missed"] or 0) + 1
            conn.execute(
                "UPDATE medicines SET consecutive_missed=? WHERE id=?",
                (consecutive, r["id"])
            )
            if consecutive >= 2:
                # Notify family about missed medicines
                note = notify_relatives(
                    session_id,
                    reason=f"Patient missed {r['name']} for {consecutive} consecutive days",
                    message=(
                        f"Your family member has not taken {r['name']} ({r['dose']}) "
                        f"for {consecutive} days in a row. "
                        "Please remind them or check if they need help."
                    ),
                    alert_type="warning",
                    notify_on_event="medicine_missed"
                )
                notified.extend(note)
                _create_alert(session_id, "medicine_missed",
                    f"Missed {r['name']} for {consecutive} days", "high")

        conn.commit()
        conn.close()

        ai_msg = ""
        if missed:
            ai_msg = ai_analyze(
                f"Patient missed medicines: {', '.join(missed)}. "
                "Give a gentle reminder in 1 sentence."
            )

        return {
            "missed_medicines": missed,
            "family_notified": notified,
            "ai_reminder": ai_msg,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"missed_medicines": [], "family_notified": [], "error": str(e)}


@router.get("/medicine/reminder/{session_id}")
async def get_voice_reminder(session_id: str):
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM medicines WHERE session_id=? AND taken_today=0", (session_id,)
        ).fetchall()
        conn.close()
        now = datetime.now()
        reminders = []
        for r in rows:
            try:
                for t in json.loads(r["times"] or "[]"):
                    h, m = map(int, t.split(":"))
                    diff = (now.hour * 60 + now.minute) - (h * 60 + m)
                    if 0 <= diff <= 60:
                        reminders.append(r["name"])
            except Exception:
                pass
        if reminders:
            names = ", ".join(reminders)
            return {"has_reminder": True,
                    "message": f"Reminder: It's time to take {names}. Shall I mark it as taken?",
                    "medicines": reminders}
        return {"has_reminder": False, "message": None, "medicines": []}
    except Exception as e:
        return {"has_reminder": False, "message": None, "medicines": [], "error": str(e)}


@router.get("/medicine/refill-prediction/{session_id}")
async def refill_prediction(session_id: str):
    try:
        conn = get_db()
        rows = conn.execute("SELECT * FROM medicines WHERE session_id=?", (session_id,)).fetchall()
        conn.close()
        predictions = []
        for r in rows:
            try:
                times_per_day = len(json.loads(r["times"] or "[]"))
            except Exception:
                times_per_day = 1
            remaining = r["refill_remaining"] or 30
            days_left = remaining // times_per_day if times_per_day > 0 else remaining
            refill_date = (datetime.now() + timedelta(days=days_left)).strftime("%Y-%m-%d")
            urgency = "critical" if days_left <= 3 else "soon" if days_left <= 7 else "normal"
            predictions.append({
                "medicine": r["name"], "doses_remaining": remaining,
                "days_left": days_left, "predicted_refill_date": refill_date, "urgency": urgency
            })
        return {"predictions": predictions, "generated_at": datetime.now().isoformat()}
    except Exception as e:
        return {"predictions": [], "error": str(e)}


# ═══════════════════════════════════════════════════════
#  MENTAL HEALTH — with depression auto-detection
# ═══════════════════════════════════════════════════════

@router.post("/mental/checkin")
async def mental_checkin(session_id: str, checkin: MentalCheckIn):
    try:
        sentiment = "positive" if checkin.mood >= 7 else "negative" if checkin.mood <= 3 else "neutral"
        ai_prompt = (
            f"Mood: {checkin.mood}/10, energy: {checkin.energy_level}/10, "
            f"anxiety: {checkin.anxiety_level}/10, sleep: {checkin.sleep_hours}hrs. "
            f"Notes: {checkin.notes or 'none'}. Give a brief empathetic response."
        )
        ai_analysis = ai_analyze(ai_prompt)

        conn = get_db()
        conn.execute(
            """INSERT INTO mental_log
               (session_id,mood,notes,activities,energy_level,anxiety_level,sleep_hours,date,ai_analysis,sentiment)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (session_id, checkin.mood, checkin.notes, json.dumps(checkin.activities),
             checkin.energy_level, checkin.anxiety_level, checkin.sleep_hours,
             datetime.now().strftime("%Y-%m-%d"), ai_analysis, sentiment)
        )
        conn.commit()

        recent = conn.execute(
            "SELECT mood FROM mental_log WHERE session_id=? ORDER BY id DESC LIMIT 3",
            (session_id,)
        ).fetchall()
        conn.close()

        crisis_flag = len(recent) == 3 and all(r["mood"] <= 3 for r in recent)
        family_alerted = []

        if crisis_flag:
            _create_alert(session_id, "mood_crisis",
                "3 consecutive low mood check-ins — immediate support needed", "critical")
            family_alerted = notify_relatives(
                session_id,
                reason="Patient mood has been critically low for 3 consecutive days",
                message=(
                    f"Your family member has reported mood scores of "
                    f"{', '.join(str(r['mood']) for r in recent)}/10 over the past 3 check-ins. "
                    "Please reach out to them immediately."
                ),
                alert_type="critical",
                notify_on_event="depression"
            )
        elif checkin.mood <= 3:
            # Single low mood — gentle alert
            notify_relatives(
                session_id,
                reason="Patient reported very low mood today",
                message=f"Your family member reported mood {checkin.mood}/10 today. Please check on them.",
                alert_type="warning",
                notify_on_event="distress"
            )

        if checkin.mood <= 3:
            response = "I can see you're going through a really hard time. You are not alone — I'm here with you."
        elif checkin.mood <= 5:
            response = "Thank you for being honest with me. Tough days happen. I'm here if you need anything."
        elif checkin.mood <= 7:
            response = "Good to hear from you. Every step forward counts!"
        else:
            response = "That's wonderful! I'm really glad you're feeling good today! 🌟"

        return {
            "logged": True, "mood": checkin.mood,
            "response": ai_analysis or response,
            "alert": "critical" if crisis_flag else ("low_mood" if checkin.mood <= 3 else "none"),
            "sentiment": sentiment, "ai_analysis": ai_analysis,
            "crisis_detected": crisis_flag, "family_alerted": family_alerted,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"logged": False, "error": str(e)}


@router.get("/mental/history/{session_id}")
async def mental_history(session_id: str):
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM mental_log WHERE session_id=? ORDER BY id DESC LIMIT 14",
            (session_id,)
        ).fetchall()
        conn.close()
        log = [dict(r) for r in rows]
        for entry in log:
            try:
                entry["activities"] = json.loads(entry.get("activities") or "[]")
            except Exception:
                entry["activities"] = []

        avg   = sum(e["mood"] for e in log) / len(log) if log else 0
        trend = "stable"
        if len(log) >= 6:
            r = [e["mood"] for e in log[:3]]
            o = [e["mood"] for e in log[3:6]]
            ar, ao = sum(r)/len(r), sum(o)/len(o)
            if ar > ao + 0.5:   trend = "improving"
            elif ar < ao - 0.5: trend = "declining"

        weekly_summary = ai_analyze(
            f"Patient {len(log)} check-ins. Avg mood {round(avg,1)}/10. Trend: {trend}. "
            "Give a warm 1-sentence weekly summary."
        ) if log else "No check-ins recorded yet."

        return {
            "session_id": session_id, "total_entries": len(log),
            "average_mood": round(avg, 1), "trend": trend,
            "history": list(reversed(log)), "weekly_summary": weekly_summary,
            "sentiment_breakdown": {
                "positive": sum(1 for e in log if e.get("sentiment") == "positive"),
                "neutral":  sum(1 for e in log if e.get("sentiment") == "neutral"),
                "negative": sum(1 for e in log if e.get("sentiment") == "negative"),
            }
        }
    except Exception as e:
        return {"session_id": session_id, "total_entries": 0, "average_mood": 0,
                "trend": "stable", "history": [], "weekly_summary": "", "error": str(e)}


@router.get("/mental/daily-prompt/{session_id}")
async def daily_prompt(session_id: str):
    prompts = [
        "Good morning! On a scale of 1 to 10, how are you feeling today?",
        "How has your day been so far? I'm here to listen.",
        "Have you had enough water and food today? Taking care of yourself matters.",
        "Is there anything worrying you today? You can tell me anything.",
        "You've been doing great. How are you feeling right now?",
        "Did you take your medicines today? And how are you feeling?",
        "I'm checking in on you. How is your mood today, from 1 to 10?",
    ]
    return {"prompt": prompts[datetime.now().weekday() % len(prompts)],
            "timestamp": datetime.now().isoformat()}


# ═══════════════════════════════════════════════════════
#  VITALS
# ═══════════════════════════════════════════════════════

@router.post("/vitals/log")
async def log_vitals(session_id: str, vitals: VitalsEntry):
    try:
        alerts = []
        if vitals.bp_systolic and vitals.bp_systolic > 140:
            alerts.append("High blood pressure")
        if vitals.bp_systolic and vitals.bp_systolic < 90:
            alerts.append("Low blood pressure")
        if vitals.blood_sugar and vitals.blood_sugar > 200:
            alerts.append("High blood sugar")
        if vitals.blood_sugar and vitals.blood_sugar < 70:
            alerts.append("Low blood sugar — hypoglycemia risk")
        if vitals.pulse and vitals.pulse > 100:
            alerts.append("Elevated heart rate")
        if vitals.oxygen_saturation and vitals.oxygen_saturation < 95:
            alerts.append("Low oxygen saturation")
        if vitals.temperature and vitals.temperature > 38.5:
            alerts.append("Fever detected")

        ai_assessment = ai_analyze(
            f"Vitals: BP {vitals.bp_systolic}/{vitals.bp_diastolic}, "
            f"Pulse {vitals.pulse}, Sugar {vitals.blood_sugar}, "
            f"Temp {vitals.temperature}, SpO2 {vitals.oxygen_saturation}%. "
            f"Alerts: {', '.join(alerts) if alerts else 'none'}. Brief assessment."
        )

        conn = get_db()
        conn.execute(
            """INSERT INTO vitals
               (session_id,bp_systolic,bp_diastolic,pulse,blood_sugar,
                temperature,oxygen_saturation,weight,notes,ai_assessment)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (session_id, vitals.bp_systolic, vitals.bp_diastolic, vitals.pulse,
             vitals.blood_sugar, vitals.temperature, vitals.oxygen_saturation,
             vitals.weight, vitals.notes, ai_assessment)
        )
        conn.commit()
        conn.close()
        for alert in alerts:
            sev = "critical" if "oxygen" in alert.lower() or "hypoglycemia" in alert.lower() else "medium"
            _create_alert(session_id, "vitals_alert", alert, sev)
        return {"logged": True, "alerts": alerts, "ai_assessment": ai_assessment,
                "timestamp": datetime.now().isoformat(),
                "status": "critical" if any("oxygen" in a or "hypoglycemia" in a for a in alerts)
                          else "warning" if alerts else "normal"}
    except Exception as e:
        return {"logged": False, "error": str(e)}


@router.get("/vitals/history/{session_id}")
async def vitals_history(session_id: str):
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM vitals WHERE session_id=? ORDER BY id DESC LIMIT 10",
            (session_id,)
        ).fetchall()
        conn.close()
        vitals = [dict(r) for r in rows]
        bp_trend = "stable"
        if len(vitals) >= 3:
            bps = [v["bp_systolic"] for v in vitals[:3] if v["bp_systolic"]]
            if len(bps) >= 2:
                if bps[0] > bps[-1] + 5:   bp_trend = "rising"
                elif bps[0] < bps[-1] - 5: bp_trend = "falling"
        return {"history": list(reversed(vitals)), "bp_trend": bp_trend,
                "latest": vitals[0] if vitals else None, "total_readings": len(vitals)}
    except Exception as e:
        return {"history": [], "bp_trend": "stable", "latest": None, "total_readings": 0, "error": str(e)}


# ═══════════════════════════════════════════════════════
#  PAIN, SLEEP, HYDRATION, SYMPTOMS, JOURNAL, ALERTS
#  (same as before — wrapped with try/except)
# ═══════════════════════════════════════════════════════

@router.post("/pain/log")
async def log_pain(session_id: str, pain: PainEntry):
    try:
        urgency = "critical" if pain.pain_level >= 8 else "medium" if pain.pain_level >= 6 else "low"
        ai_rec = ai_analyze(
            f"{pain.pain_type} pain {pain.pain_level}/10 at {pain.body_location} "
            f"for {pain.duration_minutes} min. Brief caring recommendation."
        )
        conn = get_db()
        conn.execute(
            """INSERT INTO pain_log
               (session_id,pain_level,body_location,pain_type,duration_minutes,notes,ai_recommendation)
               VALUES (?,?,?,?,?,?,?)""",
            (session_id, pain.pain_level, pain.body_location, pain.pain_type,
             pain.duration_minutes, pain.notes, ai_rec)
        )
        conn.commit()
        conn.close()
        if pain.pain_level >= 8:
            _create_alert(session_id, "severe_pain",
                f"Severe pain {pain.pain_level}/10 at {pain.body_location}", "high")
        return {"logged": True, "pain_level": pain.pain_level, "urgency": urgency,
                "ai_recommendation": ai_rec, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"logged": False, "error": str(e)}


@router.get("/pain/history/{session_id}")
async def pain_history(session_id: str):
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM pain_log WHERE session_id=? ORDER BY id DESC LIMIT 10",
            (session_id,)
        ).fetchall()
        conn.close()
        history = [dict(r) for r in rows]
        avg_pain = sum(h["pain_level"] for h in history) / len(history) if history else 0
        return {"history": history, "average_pain": round(avg_pain, 1), "total_events": len(history)}
    except Exception as e:
        return {"history": [], "average_pain": 0, "total_events": 0, "error": str(e)}


@router.post("/sleep/log")
async def log_sleep(session_id: str, sleep: SleepEntry):
    try:
        ai_tip = ai_analyze(
            f"Slept {sleep.sleep_hours} hrs, quality {sleep.quality}/10, "
            f"{sleep.disturbances} disturbances. Brief sleep tip."
        )
        conn = get_db()
        conn.execute(
            """INSERT INTO sleep_log
               (session_id,sleep_hours,quality,bedtime,wake_time,disturbances,ai_tip)
               VALUES (?,?,?,?,?,?,?)""",
            (session_id, sleep.sleep_hours, sleep.quality, sleep.bedtime,
             sleep.wake_time, sleep.disturbances, ai_tip)
        )
        conn.commit()
        conn.close()
        status = "good" if sleep.sleep_hours >= 7 and sleep.quality >= 7 \
                 else "poor" if sleep.sleep_hours < 5 or sleep.quality <= 3 else "fair"
        return {"logged": True, "sleep_hours": sleep.sleep_hours,
                "quality": sleep.quality, "ai_tip": ai_tip, "status": status}
    except Exception as e:
        return {"logged": False, "error": str(e)}


@router.get("/sleep/history/{session_id}")
async def sleep_history(session_id: str):
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM sleep_log WHERE session_id=? ORDER BY id DESC LIMIT 7",
            (session_id,)
        ).fetchall()
        conn.close()
        history = [dict(r) for r in rows]
        avg_h = sum(h["sleep_hours"] for h in history) / len(history) if history else 0
        avg_q = sum(h["quality"]     for h in history) / len(history) if history else 0
        return {"history": list(reversed(history)), "average_hours": round(avg_h, 1),
                "average_quality": round(avg_q, 1)}
    except Exception as e:
        return {"history": [], "average_hours": 0, "average_quality": 0, "error": str(e)}


@router.post("/hydration/log")
async def log_hydration(session_id: str, entry: HydrationEntry):
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        conn  = get_db()
        existing = conn.execute(
            "SELECT id,glasses FROM hydration_log WHERE session_id=? AND date=?",
            (session_id, today)
        ).fetchone()
        if existing:
            total = existing["glasses"] + entry.glasses
            conn.execute("UPDATE hydration_log SET glasses=? WHERE id=?", (total, existing["id"]))
        else:
            total = entry.glasses
            conn.execute(
                "INSERT INTO hydration_log (session_id,glasses,date) VALUES (?,?,?)",
                (session_id, entry.glasses, today)
            )
        conn.commit()
        conn.close()
        goal = 8
        pct  = min(round(total / goal * 100), 100)
        return {"logged": True, "total_today": total, "goal": goal, "percentage": pct,
                "status": "goal_reached" if total >= goal else "on_track" if total >= 4 else "low",
                "message": "🎉 Daily hydration goal reached!" if total >= goal
                           else f"{total} glasses done. {goal-total} more to go!"}
    except Exception as e:
        return {"logged": False, "error": str(e)}


@router.get("/hydration/today/{session_id}")
async def hydration_today(session_id: str):
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        conn  = get_db()
        row   = conn.execute(
            "SELECT glasses FROM hydration_log WHERE session_id=? AND date=?",
            (session_id, today)
        ).fetchone()
        conn.close()
        glasses = row["glasses"] if row else 0
        return {"glasses_today": glasses, "goal": 8,
                "percentage": min(round(glasses / 8 * 100), 100)}
    except Exception as e:
        return {"glasses_today": 0, "goal": 8, "percentage": 0, "error": str(e)}


SYMPTOM_SEVERITY_MAP = {
    "chest pain":9,"difficulty breathing":9,"shortness of breath":8,
    "unconscious":10,"seizure":10,"stroke":10,"severe headache":7,
    "high fever":7,"vomiting blood":9,"headache":4,"fever":5,"nausea":3,
    "fatigue":3,"cough":3,"cold":2,"sore throat":3,"dizziness":5,
    "back pain":4,"joint pain":4,"stomach pain":5,
}


@router.post("/symptoms/check")
async def check_symptoms(session_id: str, symptoms: SymptomEntry):
    try:
        symptom_str  = ", ".join(symptoms.symptom_list)
        max_known    = max(
            (SYMPTOM_SEVERITY_MAP.get(s.lower(), symptoms.severity) for s in symptoms.symptom_list),
            default=symptoms.severity
        )
        final_sev    = max(symptoms.severity, max_known)
        urgency      = ("emergency" if final_sev >= 9 else "urgent" if final_sev >= 7
                        else "consult_doctor" if final_sev >= 5 else "monitor")
        rec_action   = {
            "emergency":    "🚨 Call 112 immediately!",
            "urgent":       "⚠️ See a doctor today.",
            "consult_doctor":"📞 Book an appointment in 2-3 days.",
            "monitor":      "📋 Rest, monitor, stay hydrated."
        }[urgency]
        ai_assessment = ai_analyze(
            f"Symptoms: {symptom_str}. Severity: {final_sev}/10. "
            f"Duration: {symptoms.duration_hours} hrs. Brief assessment."
        )
        conn = get_db()
        conn.execute(
            """INSERT INTO symptoms
               (session_id,symptom_list,severity,duration_hours,ai_assessment,recommended_action,urgency_level)
               VALUES (?,?,?,?,?,?,?)""",
            (session_id, json.dumps(symptoms.symptom_list), final_sev,
             symptoms.duration_hours, ai_assessment, rec_action, urgency)
        )
        conn.commit()
        conn.close()
        if urgency in ["emergency", "urgent"]:
            _create_alert(session_id, "symptom_alert", f"Urgent: {symptom_str}",
                         "critical" if urgency == "emergency" else "high")
        return {"symptoms": symptoms.symptom_list, "severity_score": final_sev,
                "urgency": urgency, "recommended_action": rec_action,
                "ai_assessment": ai_assessment, "call_emergency": urgency == "emergency",
                "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"symptoms": [], "severity_score": 0, "urgency": "monitor",
                "recommended_action": "", "ai_assessment": "", "call_emergency": False,
                "error": str(e)}


@router.post("/appointments/add")
async def add_appointment(session_id: str, appt: AppointmentEntry):
    try:
        conn = get_db()
        conn.execute(
            """INSERT INTO appointments
               (session_id,doctor_name,specialty,appointment_date,appointment_time,hospital,notes)
               VALUES (?,?,?,?,?,?,?)""",
            (session_id, appt.doctor_name, appt.specialty,
             appt.appointment_date, appt.appointment_time, appt.hospital, appt.notes)
        )
        conn.commit()
        conn.close()
        return {"status": "scheduled", "doctor": appt.doctor_name,
                "date": appt.appointment_date, "time": appt.appointment_time,
                "message": f"Appointment with {appt.doctor_name} on {appt.appointment_date}."}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/appointments/{session_id}")
async def get_appointments(session_id: str):
    try:
        conn  = get_db()
        rows  = conn.execute(
            "SELECT * FROM appointments WHERE session_id=? ORDER BY appointment_date,appointment_time",
            (session_id,)
        ).fetchall()
        conn.close()
        appts   = [dict(r) for r in rows]
        today   = datetime.now().strftime("%Y-%m-%d")
        upcoming = [a for a in appts if a["appointment_date"] >= today]
        past     = [a for a in appts if a["appointment_date"] <  today]
        return {"upcoming": upcoming, "past": past,
                "total": len(appts), "next": upcoming[0] if upcoming else None}
    except Exception as e:
        return {"upcoming": [], "past": [], "total": 0, "next": None, "error": str(e)}


@router.post("/journal/add")
async def add_journal(session_id: str, entry: JournalEntry):
    try:
        pos_w = ["happy","good","great","wonderful","excited","grateful","better","joy","love","peaceful"]
        neg_w = ["sad","bad","terrible","awful","depressed","anxious","scared","alone","pain","hopeless"]
        c     = entry.content.lower()
        ai_sentiment = (
            "positive" if sum(1 for w in pos_w if w in c) > sum(1 for w in neg_w if w in c)
            else "negative" if sum(1 for w in neg_w if w in c) > 0 else "neutral"
        )
        ai_response = ai_analyze(
            f"Journal: '{entry.content}'. Mood: {entry.mood_tag}. Warm 1-2 sentence response."
        )
        conn = get_db()
        conn.execute(
            "INSERT INTO journal_entries (session_id,content,mood_tag,ai_sentiment,ai_response) VALUES (?,?,?,?,?)",
            (session_id, entry.content, entry.mood_tag, ai_sentiment, ai_response)
        )
        conn.commit()
        conn.close()
        return {"logged": True, "sentiment": ai_sentiment, "ai_response": ai_response,
                "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"logged": False, "error": str(e)}


@router.get("/journal/entries/{session_id}")
async def get_journal(session_id: str):
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM journal_entries WHERE session_id=? ORDER BY id DESC LIMIT 10",
            (session_id,)
        ).fetchall()
        conn.close()
        return {"entries": [dict(r) for r in rows], "total": len(rows)}
    except Exception as e:
        return {"entries": [], "total": 0, "error": str(e)}


def _create_alert(session_id: str, alert_type: str, message: str, severity: str = "medium"):
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO health_alerts (session_id,alert_type,message,severity) VALUES (?,?,?,?)",
            (session_id, alert_type, message, severity)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Alert error: {e}")


@router.get("/alerts/{session_id}")
async def get_alerts(session_id: str):
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM health_alerts WHERE session_id=? ORDER BY id DESC LIMIT 20",
            (session_id,)
        ).fetchall()
        conn.close()
        alerts = [dict(r) for r in rows]
        return {"alerts": alerts,
                "unread_count": sum(1 for a in alerts if not a["is_read"]),
                "critical_count": sum(1 for a in alerts if a["severity"] == "critical" and not a["is_read"])}
    except Exception as e:
        return {"alerts": [], "unread_count": 0, "critical_count": 0, "error": str(e)}


@router.post("/alerts/read/{session_id}")
async def mark_alerts_read(session_id: str):
    try:
        conn = get_db()
        conn.execute("UPDATE health_alerts SET is_read=1 WHERE session_id=?", (session_id,))
        conn.commit()
        conn.close()
        return {"status": "marked_read"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/fall/detected")
async def fall_detected(session_id: str, severity: str = "medium", location: str = "home"):
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO fall_events (session_id,severity,location) VALUES (?,?,?)",
            (session_id, severity, location)
        )
        conn.commit()
        conn.close()
        _create_alert(session_id, "fall_detected",
            f"Fall at {location}. Severity: {severity}.", "critical")
        notify_relatives(
            session_id,
            reason=f"Fall detected at {location}",
            message=f"Nova Bridge detected a fall at {location}. Severity: {severity}. Please check on your family member immediately.",
            alert_type="emergency",
            notify_on_event="crisis"
        )
        return {"detected": True, "severity": severity, "location": location,
                "action": "Relatives notified. Emergency services may be required.",
                "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"detected": False, "error": str(e)}


# ═══════════════════════════════════════════════════════
#  MONTHLY CHART — combined all activities, base64 PNG
# ═══════════════════════════════════════════════════════

@router.get("/chart/monthly/{session_id}")
async def monthly_chart(session_id: str, month: Optional[str] = None):
    """
    Generate a monthly combined activity chart.
    Returns base64-encoded PNG + summary stats.
    month format: "2024-01" (defaults to current month)
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
        from matplotlib.patches import FancyBboxPatch

        if not month:
            month = datetime.now().strftime("%Y-%m")

        year, mon = map(int, month.split("-"))
        # Days in month
        if mon == 12:
            days_in_month = 31
        else:
            import calendar
            days_in_month = calendar.monthrange(year, mon)[1]

        day_labels = [f"{d}" for d in range(1, days_in_month + 1)]
        conn = get_db()

        # ── Mood per day ─────────────────────────────
        mood_rows = conn.execute(
            """SELECT date, AVG(mood) as avg_mood
               FROM mental_log WHERE session_id=? AND date LIKE ?
               GROUP BY date ORDER BY date""",
            (session_id, f"{month}%")
        ).fetchall()

        # ── Medicine adherence per day ────────────────
        med_total = conn.execute(
            "SELECT COUNT(*) as cnt FROM medicines WHERE session_id=?",
            (session_id,)
        ).fetchone()["cnt"] or 1

        # ── Sleep per day ─────────────────────────────
        sleep_rows = conn.execute(
            """SELECT DATE(timestamp) as d, AVG(sleep_hours) as avg_sleep
               FROM sleep_log WHERE session_id=? AND DATE(timestamp) LIKE ?
               GROUP BY d ORDER BY d""",
            (session_id, f"{month}%")
        ).fetchall()

        # ── Hydration per day ─────────────────────────
        hydration_rows = conn.execute(
            "SELECT date, glasses FROM hydration_log WHERE session_id=? AND date LIKE ? ORDER BY date",
            (session_id, f"{month}%")
        ).fetchall()

        # ── Pain per day ─────────────────────────────
        pain_rows = conn.execute(
            """SELECT DATE(timestamp) as d, AVG(pain_level) as avg_pain
               FROM pain_log WHERE session_id=? AND DATE(timestamp) LIKE ?
               GROUP BY d ORDER BY d""",
            (session_id, f"{month}%")
        ).fetchall()

        # ── BP per day ────────────────────────────────
        bp_rows = conn.execute(
            """SELECT DATE(timestamp) as d,
               AVG(bp_systolic) as avg_sys, AVG(bp_diastolic) as avg_dia
               FROM vitals WHERE session_id=? AND DATE(timestamp) LIKE ?
               GROUP BY d ORDER BY d""",
            (session_id, f"{month}%")
        ).fetchall()

        conn.close()

        # Map to day number
        def to_day_map(rows, date_col, val_col):
            result = {}
            for r in rows:
                try:
                    day = int(str(r[date_col]).split("-")[2])
                    result[day] = round(float(r[val_col] or 0), 1)
                except Exception:
                    pass
            return result

        mood_map    = to_day_map(mood_rows, "date", "avg_mood")
        sleep_map   = to_day_map(sleep_rows, "d",   "avg_sleep")
        hydra_map   = {int(r["date"].split("-")[2]): r["glasses"] for r in hydration_rows}
        pain_map    = to_day_map(pain_rows, "d",   "avg_pain")
        bp_sys_map  = to_day_map(bp_rows,   "d",   "avg_sys")

        days   = list(range(1, days_in_month + 1))
        moods  = [mood_map.get(d, None) for d in days]
        sleeps = [sleep_map.get(d, None) for d in days]
        hydras = [hydra_map.get(d, None) for d in days]
        pains  = [pain_map.get(d, None)  for d in days]
        bps    = [bp_sys_map.get(d, None) for d in days]

        # Filter Nones for plotting
        def pts(vals):
            xs = [d for d, v in zip(days, vals) if v is not None]
            ys = [v for v in vals if v is not None]
            return xs, ys

        # ── PLOT ─────────────────────────────────────
        plt.rcParams.update({
            "figure.facecolor": "#ffffff",
            "axes.facecolor":   "#f8faff",
            "axes.edgecolor":   "#e2e8f0",
            "axes.grid":        True,
            "grid.color":       "#e2e8f0",
            "grid.linewidth":   0.6,
            "font.family":      "DejaVu Sans",
            "font.size":        9,
            "axes.labelcolor":  "#475569",
            "xtick.color":      "#94a3b8",
            "ytick.color":      "#94a3b8",
            "axes.spines.top":  False,
            "axes.spines.right":False,
        })

        fig = plt.figure(figsize=(16, 14))
        fig.suptitle(
            f"Nova Bridge — Monthly Health Overview\n"
            f"{datetime(year, mon, 1).strftime('%B %Y')}",
            fontsize=16, fontweight="bold", color="#0f172a", y=0.98
        )

        gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.3)

        # 1 — Mood
        ax1 = fig.add_subplot(gs[0, 0])
        mx, my = pts(moods)
        if mx:
            ax1.fill_between(mx, my, alpha=0.15, color="#2563eb")
            ax1.plot(mx, my, "o-", color="#2563eb", linewidth=2,
                     markersize=4, markerfacecolor="white", markeredgewidth=1.5)
        ax1.axhline(y=5, color="#94a3b8", linewidth=0.8, linestyle="--", alpha=0.6)
        ax1.set_ylim(0, 11)
        ax1.set_xlim(1, days_in_month)
        ax1.set_title("😊 Daily Mood (1–10)", fontweight="bold", color="#0f172a", pad=8)
        ax1.set_ylabel("Mood Score")
        avg_mood_val = round(sum(my)/len(my), 1) if my else 0
        ax1.text(0.98, 0.92, f"Avg: {avg_mood_val}/10",
                 transform=ax1.transAxes, ha="right", fontsize=9,
                 color="#2563eb", fontweight="bold")

        # 2 — Sleep
        ax2 = fig.add_subplot(gs[0, 1])
        sx, sy = pts(sleeps)
        if sx:
            ax2.bar(sx, sy, color="#7c3aed", alpha=0.7, width=0.7, edgecolor="white")
        ax2.axhline(y=7, color="#f43f5e", linewidth=1, linestyle="--",
                    alpha=0.7, label="7hr goal")
        ax2.set_ylim(0, 12)
        ax2.set_xlim(1, days_in_month)
        ax2.set_title("😴 Sleep Duration (hours)", fontweight="bold", color="#0f172a", pad=8)
        ax2.set_ylabel("Hours")
        avg_sleep = round(sum(sy)/len(sy), 1) if sy else 0
        ax2.text(0.98, 0.92, f"Avg: {avg_sleep}h",
                 transform=ax2.transAxes, ha="right", fontsize=9,
                 color="#7c3aed", fontweight="bold")

        # 3 — Hydration
        ax3 = fig.add_subplot(gs[1, 0])
        hx, hy = pts(hydras)
        if hx:
            colors_h = ["#10b981" if v >= 8 else "#f59e0b" if v >= 4 else "#f43f5e" for v in hy]
            ax3.bar(hx, hy, color=colors_h, alpha=0.8, width=0.7, edgecolor="white")
        ax3.axhline(y=8, color="#10b981", linewidth=1, linestyle="--", alpha=0.7, label="Goal")
        ax3.set_ylim(0, 12)
        ax3.set_xlim(1, days_in_month)
        ax3.set_title("💧 Hydration (glasses/day)", fontweight="bold", color="#0f172a", pad=8)
        ax3.set_ylabel("Glasses")
        avg_hydra = round(sum(hy)/len(hy), 1) if hy else 0
        ax3.text(0.98, 0.92, f"Avg: {avg_hydra} glasses",
                 transform=ax3.transAxes, ha="right", fontsize=9,
                 color="#10b981", fontweight="bold")

        # 4 — Pain
        ax4 = fig.add_subplot(gs[1, 1])
        px, py = pts(pains)
        if px:
            colors_p = ["#f43f5e" if v >= 7 else "#f59e0b" if v >= 4 else "#10b981" for v in py]
            ax4.bar(px, py, color=colors_p, alpha=0.8, width=0.7, edgecolor="white")
        ax4.set_ylim(0, 11)
        ax4.set_xlim(1, days_in_month)
        ax4.set_title("🩹 Pain Levels (0–10)", fontweight="bold", color="#0f172a", pad=8)
        ax4.set_ylabel("Pain Score")
        avg_pain = round(sum(py)/len(py), 1) if py else 0
        ax4.text(0.98, 0.92, f"Avg: {avg_pain}/10",
                 transform=ax4.transAxes, ha="right", fontsize=9,
                 color="#f43f5e", fontweight="bold")

        # 5 — Blood Pressure
        ax5 = fig.add_subplot(gs[2, 0])
        bx, by = pts(bps)
        if bx:
            ax5.plot(bx, by, "s-", color="#f43f5e", linewidth=2,
                     markersize=5, markerfacecolor="white", markeredgewidth=1.5, label="Systolic")
        ax5.axhline(y=140, color="#f43f5e", linewidth=0.8, linestyle="--", alpha=0.6, label="High")
        ax5.axhline(y=90,  color="#10b981", linewidth=0.8, linestyle="--", alpha=0.6, label="Normal")
        ax5.set_ylim(60, 180)
        ax5.set_xlim(1, days_in_month)
        ax5.legend(fontsize=7, loc="upper right")
        ax5.set_title("❤️ Systolic Blood Pressure (mmHg)", fontweight="bold", color="#0f172a", pad=8)
        ax5.set_ylabel("mmHg")

        # 6 — Combined Health Score donut
        ax6 = fig.add_subplot(gs[2, 1])
        score_items = [
            ("Mood",       min(100, avg_mood_val * 10) if avg_mood_val else 60, "#2563eb"),
            ("Sleep",      min(100, avg_sleep / 8 * 100) if avg_sleep else 60, "#7c3aed"),
            ("Hydration",  min(100, avg_hydra / 8 * 100) if avg_hydra else 50, "#10b981"),
            ("Pain-free",  max(0, 100 - avg_pain * 10) if avg_pain else 80,    "#f59e0b"),
        ]
        names  = [s[0] for s in score_items]
        scores = [s[1] for s in score_items]
        cols   = [s[2] for s in score_items]
        bars   = ax6.barh(names, scores, color=cols, alpha=0.8,
                          height=0.5, edgecolor="white")
        for bar, val in zip(bars, scores):
            ax6.text(val + 1, bar.get_y() + bar.get_height()/2,
                     f"{round(val)}%", va="center", fontsize=9,
                     color="#0f172a", fontweight="bold")
        ax6.set_xlim(0, 115)
        ax6.axvline(x=70, color="#94a3b8", linewidth=0.8, linestyle="--", alpha=0.5)
        overall = round(sum(scores) / len(scores))
        ax6.set_title(f"📊 Monthly Health Scores — Overall: {overall}%",
                      fontweight="bold", color="#0f172a", pad=8)

        # Footer
        fig.text(0.5, 0.01,
                 f"Generated by Nova Bridge AI  •  Session: {session_id}  •  {datetime.now().strftime('%d %b %Y')}",
                 ha="center", fontsize=8, color="#94a3b8")

        # Save to buffer
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                    facecolor="white", edgecolor="none")
        buf.seek(0)
        plt.close(fig)

        img_b64 = base64.b64encode(buf.read()).decode("utf-8")

        # Summary stats
        summary = {
            "month": month,
            "days_with_data": len(mx),
            "average_mood":      avg_mood_val,
            "average_sleep":     avg_sleep,
            "average_hydration": avg_hydra,
            "average_pain":      avg_pain,
            "overall_score":     overall,
            "ai_summary": ai_analyze(
                f"Monthly health: mood {avg_mood_val}/10, sleep {avg_sleep}hrs, "
                f"hydration {avg_hydra} glasses, pain {avg_pain}/10, score {overall}%. "
                "Give a brief encouraging monthly summary."
            )
        }

        return {
            "chart_base64": img_b64,
            "chart_format": "png",
            "summary": summary,
            "generated_at": datetime.now().isoformat()
        }

    except Exception as e:
        print(f"Monthly chart error: {traceback.format_exc()}")
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "chart_base64": None,
            "summary": {}
        })


# ═══════════════════════════════════════════════════════
#  DAILY HEALTH REPORT
# ═══════════════════════════════════════════════════════

@router.get("/report/daily/{session_id}")
async def daily_health_report(session_id: str):
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        conn  = get_db()
        mood_today    = conn.execute(
            "SELECT AVG(mood) as avg, COUNT(*) as cnt FROM mental_log WHERE session_id=? AND date=?",
            (session_id, today)
        ).fetchone()
        meds          = conn.execute(
            "SELECT COUNT(*) as total, SUM(taken_today) as taken FROM medicines WHERE session_id=?",
            (session_id,)
        ).fetchone()
        vitals_latest = conn.execute(
            "SELECT * FROM vitals WHERE session_id=? ORDER BY id DESC LIMIT 1",
            (session_id,)
        ).fetchone()
        pain_latest   = conn.execute(
            "SELECT AVG(pain_level) as avg FROM pain_log WHERE session_id=? AND DATE(timestamp)=?",
            (session_id, today)
        ).fetchone()
        sleep_latest  = conn.execute(
            "SELECT * FROM sleep_log WHERE session_id=? ORDER BY id DESC LIMIT 1",
            (session_id,)
        ).fetchone()
        hydration     = conn.execute(
            "SELECT glasses FROM hydration_log WHERE session_id=? AND date=?",
            (session_id, today)
        ).fetchone()
        alerts_today  = conn.execute(
            "SELECT COUNT(*) as cnt FROM health_alerts WHERE session_id=? AND DATE(created_at)=?",
            (session_id, today)
        ).fetchone()
        conn.close()

        mood_avg    = mood_today["avg"] or 5
        med_adh     = (meds["taken"] or 0) / (meds["total"] or 1) * 100 if meds["total"] else 100
        sleep_hrs   = sleep_latest["sleep_hours"] if sleep_latest else 7
        hydra_g     = hydration["glasses"] if hydration else 0
        pain_avg    = pain_latest["avg"] or 0

        score  = 100
        score -= max(0, (5 - mood_avg)   * 5)
        score -= max(0, (100 - med_adh)  * 0.3)
        score -= max(0, (7 - sleep_hrs)  * 3)
        score -= max(0, (8 - hydra_g)    * 1.5)
        score -= pain_avg * 2
        score  = max(0, min(100, round(score)))

        report_data = {
            "date": today, "mood_average": round(mood_avg, 1),
            "mood_checkins": mood_today["cnt"], "medicine_adherence": round(med_adh, 1),
            "sleep_hours": sleep_hrs, "hydration_glasses": hydra_g,
            "average_pain": round(pain_avg, 1), "alerts_today": alerts_today["cnt"],
            "health_score": score,
            "vitals": dict(vitals_latest) if vitals_latest else None
        }

        ai_summary = ai_analyze(
            f"Daily health: mood {round(mood_avg,1)}/10, meds {round(med_adh,1)}%, "
            f"sleep {sleep_hrs}hrs, hydration {hydra_g}/8, pain {round(pain_avg,1)}/10, "
            f"score {score}/100. 2-sentence encouraging summary."
        )

        conn = get_db()
        conn.execute(
            """INSERT OR REPLACE INTO daily_reports
               (session_id,report_date,report_data,ai_summary,health_score)
               VALUES (?,?,?,?,?)""",
            (session_id, today, json.dumps(report_data), ai_summary, score)
        )
        conn.commit()
        conn.close()

        grade = "A 🌟" if score >= 90 else "B 😊" if score >= 75 else "C 😐" if score >= 55 else "D 💙"
        return {
            **report_data, "grade": grade, "ai_summary": ai_summary,
            "generated_at": datetime.now().isoformat(),
            "breakdown": {
                "mood_score":      round(min(100, mood_avg * 10)),
                "medicine_score":  round(med_adh),
                "sleep_score":     round(min(100, sleep_hrs / 8 * 100)),
                "hydration_score": round(min(100, hydra_g / 8 * 100)),
                "pain_score":      round(max(0, 100 - pain_avg * 10)),
            }
        }
    except Exception as e:
        return {"date": datetime.now().strftime("%Y-%m-%d"), "health_score": 0,
                "grade": "N/A", "ai_summary": "", "error": str(e)}


# ═══════════════════════════════════════════════════════
#  COMMUNICATION PHRASES
# ═══════════════════════════════════════════════════════

DEFAULT_PHRASES = [
    {"label":"I need water",       "phrase":"I need water please",           "icon":"💧","category":"basic"},
    {"label":"I need help",        "phrase":"I need help right now",         "icon":"🆘","category":"urgent"},
    {"label":"I'm in pain",        "phrase":"I am in pain and need help",    "icon":"😢","category":"urgent"},
    {"label":"Call my family",     "phrase":"Please call my family",         "icon":"📞","category":"contact"},
    {"label":"I'm hungry",         "phrase":"I am hungry",                   "icon":"🍽️","category":"basic"},
    {"label":"I'm tired",          "phrase":"I am tired and need to rest",   "icon":"😴","category":"basic"},
    {"label":"Doctor appointment", "phrase":"I need a doctor appointment",   "icon":"🏥","category":"medical"},
    {"label":"My medicine",        "phrase":"I need to take my medicine",    "icon":"💊","category":"medical"},
    {"label":"I'm scared",         "phrase":"I am scared and need support",  "icon":"😨","category":"emotional"},
    {"label":"I'm okay",           "phrase":"I am doing okay today",         "icon":"😊","category":"emotional"},
    {"label":"Thank you",          "phrase":"Thank you very much",           "icon":"🙏","category":"social"},
    {"label":"I don't understand", "phrase":"I don't understand, please explain slowly","icon":"❓","category":"social"},
]


@router.post("/communication/add-phrase")
async def add_phrase(session_id: str, phrase: CommunicationPhrase):
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO comm_phrases (session_id,label,phrase,icon,category) VALUES (?,?,?,?,?)",
            (session_id, phrase.label, phrase.phrase, phrase.icon, phrase.category)
        )
        conn.commit()
        conn.close()
        return {"status": "added", "label": phrase.label}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/communication/phrases/{session_id}")
async def get_phrases(session_id: str):
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM comm_phrases WHERE session_id=? ORDER BY use_count DESC",
            (session_id,)
        ).fetchall()
        conn.close()
        phrases = [dict(r) for r in rows] if rows else DEFAULT_PHRASES
        categories = {}
        for p in phrases:
            cat = p.get("category", "basic")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(p)
        return {"session_id": session_id, "total": len(phrases),
                "phrases": phrases, "by_category": categories}
    except Exception as e:
        return {"session_id": session_id, "total": len(DEFAULT_PHRASES),
                "phrases": DEFAULT_PHRASES, "by_category": {}, "error": str(e)}


@router.post("/communication/speak")
async def speak_phrase(session_id: str, phrase_label: str):
    try:
        conn = get_db()
        row  = conn.execute(
            "SELECT * FROM comm_phrases WHERE session_id=? AND LOWER(label)=LOWER(?)",
            (session_id, phrase_label)
        ).fetchone()
        if row:
            conn.execute("UPDATE comm_phrases SET use_count=use_count+1 WHERE id=?", (row["id"],))
            conn.commit()
            conn.close()
            return {"speak": True, "text": row["phrase"], "label": row["label"],
                    "timestamp": datetime.now().isoformat()}
        conn.close()
        return {"speak": False, "text": None, "label": phrase_label}
    except Exception as e:
        return {"speak": False, "text": None, "error": str(e)}


# ═══════════════════════════════════════════════════════
#  HEALTH SUMMARY — original endpoint kept
# ═══════════════════════════════════════════════════════

@router.get("/summary/{session_id}")
async def health_summary(session_id: str):
    try:
        conn          = get_db()
        medicines     = conn.execute("SELECT * FROM medicines WHERE session_id=?",   (session_id,)).fetchall()
        mental_log    = conn.execute("SELECT * FROM mental_log WHERE session_id=?",  (session_id,)).fetchall()
        relatives     = conn.execute("SELECT * FROM relatives WHERE session_id=?",   (session_id,)).fetchall()
        alerts        = conn.execute(
            "SELECT COUNT(*) as cnt FROM health_alerts WHERE session_id=? AND is_read=0",
            (session_id,)
        ).fetchone()
        vitals_latest = conn.execute(
            "SELECT * FROM vitals WHERE session_id=? ORDER BY id DESC LIMIT 1",
            (session_id,)
        ).fetchone()
        conn.close()

        taken_today  = sum(1 for m in medicines if m["taken_today"])
        total_meds   = len(medicines)
        avg_mood     = sum(e["mood"] for e in mental_log) / len(mental_log) if mental_log else None
        today_str    = datetime.now().strftime("%Y-%m-%d")

        return {
            "session_id": session_id,
            "date": today_str,
            "medicine": {
                "total": total_meds, "taken_today": taken_today,
                "adherence": round(taken_today / total_meds * 100, 1) if total_meds else 100
            },
            "mental_health": {
                "checkins_today": sum(1 for e in mental_log if e["date"] == today_str),
                "average_mood": round(avg_mood, 1) if avg_mood else None,
            },
            "relatives": {
                "registered": len(relatives),
                "names": [r["name"] for r in relatives]
            },
            "unread_alerts": alerts["cnt"] if alerts else 0,
            "latest_vitals": dict(vitals_latest) if vitals_latest else None,
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "session_id": session_id, "date": datetime.now().strftime("%Y-%m-%d"),
            "medicine": {"total": 0, "taken_today": 0, "adherence": 100},
            "mental_health": {"checkins_today": 0, "average_mood": None},
            "relatives": {"registered": 0, "names": []},
            "unread_alerts": 0, "latest_vitals": None, "error": str(e)
        }


# ═══════════════════════════════════════════════════════
#  DEMO DATA LOADER
# ═══════════════════════════════════════════════════════

@router.post("/demo/load/{session_id}")
async def load_demo_data(session_id: str):
    try:
        conn = get_db()

        # Relatives
        for name, phone, rel, notify in [
            ("Rahul Sharma","+91-9876543210","son",     '["distress","crisis","depression","medicine_missed"]'),
            ("Priya Sharma", "+91-9876543211","daughter",'["distress","crisis","depression","medicine_missed"]'),
            ("Dr. Mehta",    "+91-9876543212","doctor",  '["crisis"]'),
        ]:
            conn.execute(
                "INSERT OR IGNORE INTO relatives (session_id,name,phone,relationship,notify_on) VALUES (?,?,?,?,?)",
                (session_id, name, phone, rel, notify)
            )

        # Medicines
        for name, dose, times, cat, color, taken, remaining in [
            ("Metformin",    "500mg",  '["08:00","20:00"]',"diabetes",   "#4361ee",1,28),
            ("Amlodipine",   "5mg",    '["08:00"]',         "cardiology", "#06d6a0",1,15),
            ("Atorvastatin", "10mg",   '["21:00"]',         "cholesterol","#7b2ff7",0,22),
            ("Vitamin D3",   "1000IU", '["08:00"]',         "supplement", "#ffd166",1,60),
        ]:
            conn.execute(
                """INSERT OR IGNORE INTO medicines
                   (session_id,name,dose,times,category,color,taken_today,refill_remaining)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (session_id, name, dose, times, cat, color, taken, remaining)
            )

        # Mood history (last 7 days)
        for i, (mood, note) in enumerate([
            (6,"Feeling okay today"),(7,"Good day overall"),(5,"A bit tired"),
            (8,"Great day!"),(6,"Manageable"),(7,"Feeling better"),(8,"Doing well")
        ]):
            date = (datetime.now() - timedelta(days=6-i)).strftime("%Y-%m-%d")
            ts   = (datetime.now() - timedelta(days=6-i)).isoformat()
            sent = "positive" if mood >= 7 else "neutral"
            conn.execute(
                """INSERT OR IGNORE INTO mental_log
                   (session_id,mood,notes,energy_level,anxiety_level,sleep_hours,date,timestamp,sentiment)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (session_id, mood, note, random.randint(4,8),
                 random.randint(2,5), round(random.uniform(6,8.5),1), date, ts, sent)
            )

        # Demo conversations (shows psychology detection)
        for msg, emo in [
            ("I am feeling quite lonely today, nobody visits me", "loneliness"),
            ("The pain is manageable, took my medicines", "neutral"),
            ("Feeling a bit anxious about my health", "anxiety"),
            ("Had a good day, talked to my son on the phone", "positive"),
            ("I feel hopeless sometimes, nothing seems to work", "depression"),
        ]:
            conn.execute(
                """INSERT OR IGNORE INTO conversations
                   (session_id,speaker,message,emotion_detected,keywords)
                   VALUES (?,?,?,?,?)""",
                (session_id, "patient", msg, emo, "[]")
            )

        # Vitals
        conn.execute(
            """INSERT OR IGNORE INTO vitals
               (session_id,bp_systolic,bp_diastolic,pulse,blood_sugar,temperature,oxygen_saturation,weight)
               VALUES (?,?,?,?,?,?,?,?)""",
            (session_id, 128, 82, 72, 118.0, 37.1, 98, 68.5)
        )

        # Sleep
        conn.execute(
            """INSERT OR IGNORE INTO sleep_log
               (session_id,sleep_hours,quality,bedtime,wake_time,disturbances,ai_tip)
               VALUES (?,?,?,?,?,?,?)""",
            (session_id, 7.5, 8, "22:30", "06:00", 1,
             "Your sleep pattern is healthy. Keep consistent bedtime.")
        )

        # Hydration
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute(
            "INSERT OR REPLACE INTO hydration_log (session_id,glasses,date) VALUES (?,?,?)",
            (session_id, 6, today)
        )

        # Appointment
        future_date = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        conn.execute(
            """INSERT OR IGNORE INTO appointments
               (session_id,doctor_name,specialty,appointment_date,appointment_time,hospital,notes)
               VALUES (?,?,?,?,?,?,?)""",
            (session_id, "Dr. R. Mehta", "Cardiologist", future_date,
             "10:30", "Apollo Hospital", "Routine checkup + ECG")
        )

        conn.commit()
        conn.close()

        return {
            "status": "demo_loaded",
            "message": "✅ Demo data loaded! Dashboard is now populated.",
            "loaded": {
                "relatives": 3, "medicines": 4, "mood_history": 7,
                "conversations": 5, "vitals": 1, "sleep": 1,
                "hydration": 1, "appointments": 1
            },
            "session_id": session_id,
            "next_steps": [
                f"POST /health/psychology/report/{session_id} — generate psychology report",
                f"POST /health/medicine/check-missed/{session_id} — check missed medicines",
                f"GET  /health/chart/monthly/{session_id} — get monthly chart",
                f"GET  /health/report/daily/{session_id} — daily health report",
            ]
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/demo/session")
async def get_demo_session():
    return {
        "demo_session_id": "demo-nova-bridge-2024",
        "instructions":    "Use this session_id to see populated demo data",
        "load_url":        "/health/demo/load/demo-nova-bridge-2024"
    }