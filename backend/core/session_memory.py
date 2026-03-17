"""
Nova Memory System — session_memory.py
=======================================
Full persistent memory for every user.
Saves to JSON file so memory survives server restarts.

What's stored:
  - Preferred hospital, pharmacy, caregiver, language
  - Medicine schedule (name, time, dose, taken today?)
  - Last 7 days of emotional states (hourly)
  - Full task history
  - Proactive suggestion engine
  - Smart context hints
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from models.schemas import SessionMemory, IntentType

# ── Storage path ────────────────────────────────────────────────────────────
MEMORY_DIR  = os.path.join(os.path.dirname(__file__), "..", "memory_store")
os.makedirs(MEMORY_DIR, exist_ok=True)

# ── In-memory cache (loaded from disk on first access) ──────────────────────
_memory_cache: Dict[str, dict] = {}


# ═══════════════════════════════════════════════════════════════════════════
#  DEFAULT MEMORY STRUCTURE
#  This is the full schema for a user's memory.
#  All fields are optional — Nova fills them in as user interacts.
# ═══════════════════════════════════════════════════════════════════════════

def _default_memory(session_id: str) -> dict:
    return {
        # ── Identity ──────────────────────────────────────────
        "session_id":         session_id,
        "user_name":          None,
        "created_at":         datetime.now().isoformat(),
        "last_active":        datetime.now().isoformat(),

        # ── Preferences ───────────────────────────────────────
        "preferred_hospital":  None,   # e.g. "Apollo Hospital Ahmedabad"
        "preferred_pharmacy":  None,   # e.g. "MedPlus"
        "preferred_doctor":    None,   # e.g. "Dr. Sharma"
        "preferred_language":  "en",   # en, hi, gu, ta, te, bn, mr
        "caregiver_name":      None,   # e.g. "Rahul"
        "caregiver_phone":     None,   # e.g. "+919876543210"
        "caregiver_email":     None,

        # ── Last task context ─────────────────────────────────
        "last_intent":        None,
        "last_clinic":        None,
        "last_doctor":        None,
        "last_medication":    None,
        "last_pharmacy":      None,
        "last_bill_type":     None,

        # ── Medicine schedule ─────────────────────────────────
        # List of: {name, dose, time, taken_today, last_taken, refill_due}
        "medicine_schedule":  [],

        # ── Emotional history — last 7 days ───────────────────
        # List of: {timestamp, emotion, score, trigger}
        # Kept max 7 days (168 hourly entries max)
        "emotional_history":  [],

        # ── Task history ──────────────────────────────────────
        # List of: {timestamp, intent, summary, success}
        "task_history":       [],

        # ── Behavior patterns ─────────────────────────────────
        "wake_time":          None,    # "08:00"
        "sleep_time":         None,    # "22:00"
        "missed_medicines":   0,       # count this week
        "distress_count_today": 0,
        "last_distress_alert":  None,

        # ── Stats ─────────────────────────────────────────────
        "total_tasks_completed": 0,
        "total_hours_saved":     0.0,
        "total_cost_saved_inr":  0.0,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  DISK PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════

def _memory_path(session_id: str) -> str:
    safe_id = session_id.replace("/", "_").replace("\\", "_")
    return os.path.join(MEMORY_DIR, f"{safe_id}.json")


def _load_from_disk(session_id: str) -> dict:
    path = _memory_path(session_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # merge with default to fill any new fields added after creation
            default = _default_memory(session_id)
            default.update(data)
            return default
        except Exception as e:
            print(f"  [Memory] Failed to load {path}: {e} — starting fresh")
    return _default_memory(session_id)


def _save_to_disk(session_id: str, memory: dict):
    path = _memory_path(session_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        print(f"  [Memory] Failed to save {path}: {e}")


# ═══════════════════════════════════════════════════════════════════════════
#  CORE MEMORY ACCESS
# ═══════════════════════════════════════════════════════════════════════════

def _get(session_id: str) -> dict:
    """Load memory from cache or disk."""
    if session_id not in _memory_cache:
        _memory_cache[session_id] = _load_from_disk(session_id)
    return _memory_cache[session_id]


def _save(session_id: str):
    """Flush in-memory cache to disk."""
    if session_id in _memory_cache:
        _memory_cache[session_id]["last_active"] = datetime.now().isoformat()
        _save_to_disk(session_id, _memory_cache[session_id])


# ═══════════════════════════════════════════════════════════════════════════
#  PUBLIC API — get / save (backward compatible with old code)
# ═══════════════════════════════════════════════════════════════════════════

def get_memory(session_id: str) -> Optional[SessionMemory]:
    """Returns a SessionMemory schema object (backward compatible)."""
    m = _get(session_id)
    return SessionMemory(
        session_id    = session_id,
        last_clinic   = m.get("last_clinic"),
        last_doctor   = m.get("last_doctor"),
        last_medication = m.get("last_medication"),
        last_intent   = IntentType(m["last_intent"]) if m.get("last_intent") else None,
    )


def get_full_memory(session_id: str) -> dict:
    """Returns the complete raw memory dict — use this for new features."""
    return _get(session_id)


def save_memory(session_id: str, memory: SessionMemory):
    """Backward-compatible save for SessionMemory schema objects."""
    m = _get(session_id)
    if memory.last_clinic:
        m["last_clinic"] = memory.last_clinic
    if memory.last_doctor:
        m["last_doctor"] = memory.last_doctor
    if memory.last_medication:
        m["last_medication"] = memory.last_medication
    if memory.last_intent:
        m["last_intent"] = memory.last_intent.value
    _memory_cache[session_id] = m
    _save(session_id)


def clear_memory(session_id: str):
    """Wipe memory for a session (both cache and disk)."""
    if session_id in _memory_cache:
        del _memory_cache[session_id]
    path = _memory_path(session_id)
    if os.path.exists(path):
        os.remove(path)
    print(f"  [Memory] Cleared memory for session: {session_id}")


# ═══════════════════════════════════════════════════════════════════════════
#  PREFERENCES — set user preferences
# ═══════════════════════════════════════════════════════════════════════════

def set_preference(session_id: str, key: str, value: Any):
    """
    Set any user preference.
    Keys: preferred_hospital, preferred_pharmacy, preferred_doctor,
          preferred_language, caregiver_name, caregiver_phone,
          caregiver_email, user_name, wake_time, sleep_time
    """
    allowed = {
        "preferred_hospital", "preferred_pharmacy", "preferred_doctor",
        "preferred_language", "caregiver_name", "caregiver_phone",
        "caregiver_email", "user_name", "wake_time", "sleep_time"
    }
    if key not in allowed:
        print(f"  [Memory] Unknown preference key: {key}")
        return
    m = _get(session_id)
    m[key] = value
    _save(session_id)
    print(f"  [Memory] Saved preference: {key} = {value}")


def get_preferences(session_id: str) -> dict:
    """Returns all stored user preferences."""
    m = _get(session_id)
    return {
        "preferred_hospital":  m.get("preferred_hospital"),
        "preferred_pharmacy":  m.get("preferred_pharmacy"),
        "preferred_doctor":    m.get("preferred_doctor"),
        "preferred_language":  m.get("preferred_language", "en"),
        "caregiver_name":      m.get("caregiver_name"),
        "caregiver_phone":     m.get("caregiver_phone"),
        "caregiver_email":     m.get("caregiver_email"),
        "user_name":           m.get("user_name"),
        "wake_time":           m.get("wake_time"),
        "sleep_time":          m.get("sleep_time"),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  MEDICINE SCHEDULE
# ═══════════════════════════════════════════════════════════════════════════

def add_medicine(session_id: str, name: str, dose: str, time: str, refill_days: int = 30):
    """
    Add a medicine to user's schedule.
    Example: add_medicine("u1", "Metformin", "500mg", "08:00", refill_days=28)
    """
    m = _get(session_id)
    # remove if already exists (update)
    m["medicine_schedule"] = [med for med in m["medicine_schedule"] if med["name"].lower() != name.lower()]
    m["medicine_schedule"].append({
        "name":        name,
        "dose":        dose,
        "time":        time,
        "taken_today": False,
        "last_taken":  None,
        "refill_due":  (datetime.now() + timedelta(days=refill_days)).strftime("%Y-%m-%d"),
        "added_at":    datetime.now().isoformat(),
    })
    _save(session_id)
    print(f"  [Memory] Medicine added: {name} {dose} at {time}")


def mark_medicine_taken(session_id: str, medicine_name: str):
    """Mark a medicine as taken today."""
    m = _get(session_id)
    for med in m["medicine_schedule"]:
        if med["name"].lower() == medicine_name.lower():
            med["taken_today"] = True
            med["last_taken"]  = datetime.now().isoformat()
            break
    _save(session_id)


def get_missed_medicines(session_id: str) -> List[dict]:
    """Returns list of medicines not yet taken today."""
    m = _get(session_id)
    now_hour = datetime.now().hour
    missed = []
    for med in m["medicine_schedule"]:
        scheduled_hour = int(med["time"].split(":")[0]) if ":" in med["time"] else 8
        if scheduled_hour <= now_hour and not med["taken_today"]:
            missed.append(med)
    return missed


def get_medicines_due_refill(session_id: str) -> List[dict]:
    """Returns medicines whose refill is due within 5 days."""
    m = _get(session_id)
    today = datetime.now().date()
    due = []
    for med in m["medicine_schedule"]:
        if med.get("refill_due"):
            try:
                refill_date = datetime.strptime(med["refill_due"], "%Y-%m-%d").date()
                if (refill_date - today).days <= 5:
                    due.append(med)
            except:
                pass
    return due


def reset_daily_medicine_status(session_id: str):
    """Call this once per day (midnight) to reset taken_today flags."""
    m = _get(session_id)
    for med in m["medicine_schedule"]:
        med["taken_today"] = False
    m["distress_count_today"] = 0
    _save(session_id)


# ═══════════════════════════════════════════════════════════════════════════
#  EMOTIONAL HISTORY — last 7 days
# ═══════════════════════════════════════════════════════════════════════════

def log_emotion(session_id: str, emotion: str, score: float = 0.0, trigger: str = ""):
    """
    Log an emotional state with timestamp.
    emotion: calm | anxious | distress | crisis
    score: 0.0 to 1.0 intensity
    trigger: what caused it (optional)
    Keeps only last 7 days of data.
    """
    m = _get(session_id)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "emotion":   emotion,
        "score":     round(score, 2),
        "trigger":   trigger,
    }
    m["emotional_history"].append(entry)

    # track distress count today
    if emotion in ("distress", "crisis"):
        m["distress_count_today"] = m.get("distress_count_today", 0) + 1
        m["last_distress_alert"]  = datetime.now().isoformat()

    # prune entries older than 7 days
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    m["emotional_history"] = [e for e in m["emotional_history"] if e["timestamp"] >= cutoff]

    _save(session_id)


def get_emotional_history(session_id: str, days: int = 7) -> List[dict]:
    """Returns emotional history for the last N days."""
    m = _get(session_id)
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    return [e for e in m["emotional_history"] if e["timestamp"] >= cutoff]


def get_today_emotional_summary(session_id: str) -> dict:
    """Returns today's emotional summary — dominant emotion, distress count, timeline."""
    m = _get(session_id)
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_entries = [e for e in m["emotional_history"] if e["timestamp"].startswith(today_str)]

    if not today_entries:
        return {"dominant": "calm", "distress_count": 0, "timeline": [], "entries": 0}

    emotion_counts = {}
    for e in today_entries:
        emotion_counts[e["emotion"]] = emotion_counts.get(e["emotion"], 0) + 1

    dominant = max(emotion_counts, key=emotion_counts.get)
    return {
        "dominant":      dominant,
        "distress_count": m.get("distress_count_today", 0),
        "timeline":      today_entries,
        "entries":       len(today_entries),
        "emotion_counts": emotion_counts,
    }


def get_weekly_emotional_trend(session_id: str) -> List[dict]:
    """
    Returns per-day emotional summary for last 7 days.
    Used by caregiver dashboard chart.
    """
    result = []
    for i in range(6, -1, -1):
        day = datetime.now() - timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        m = _get(session_id)
        day_entries = [e for e in m["emotional_history"] if e["timestamp"].startswith(day_str)]
        counts = {}
        for e in day_entries:
            counts[e["emotion"]] = counts.get(e["emotion"], 0) + 1
        dominant = max(counts, key=counts.get) if counts else "calm"
        result.append({
            "date":          day_str,
            "day_label":     day.strftime("%a"),
            "dominant":      dominant,
            "total_entries": len(day_entries),
            "distress_count": counts.get("distress", 0) + counts.get("crisis", 0),
            "calm_count":    counts.get("calm", 0),
            "anxious_count": counts.get("anxious", 0),
        })
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  TASK HISTORY
# ═══════════════════════════════════════════════════════════════════════════

def log_task(session_id: str, intent: str, summary: str, success: bool = True):
    """Log a completed task to history."""
    m = _get(session_id)
    m["task_history"].append({
        "timestamp": datetime.now().isoformat(),
        "intent":    intent,
        "summary":   summary,
        "success":   success,
    })
    # keep last 100 tasks only
    m["task_history"] = m["task_history"][-100:]

    if success:
        m["total_tasks_completed"] = m.get("total_tasks_completed", 0) + 1
        # 0.07 hours saved per task (caregiver time)
        hours = m.get("total_hours_saved", 0.0) + 0.07
        m["total_hours_saved"] = round(hours, 2)
        # ₹6,640 per hour (80 USD equivalent)
        cost = m.get("total_cost_saved_inr", 0.0) + (0.07 * 6640)
        m["total_cost_saved_inr"] = round(cost, 2)

    _save(session_id)


def get_recent_tasks(session_id: str, limit: int = 10) -> List[dict]:
    """Returns the most recent N tasks."""
    m = _get(session_id)
    return list(reversed(m["task_history"][-limit:]))


# ═══════════════════════════════════════════════════════════════════════════
#  UPDATE AFTER TASK (backward compatible + enhanced)
# ═══════════════════════════════════════════════════════════════════════════

def update_after_task(session_id: str, intent_type: IntentType, parameters: dict):
    """
    Called by api/main.py after every successful task.
    Updates last-used clinic/doctor/medicine AND logs to history.
    """
    m = _get(session_id)
    m["last_intent"] = intent_type.value

    if intent_type.value == "book_appointment":
        clinic = parameters.get("clinic_url", parameters.get("clinic", m.get("last_clinic")))
        doctor = parameters.get("doctor", m.get("last_doctor"))
        if clinic:
            m["last_clinic"] = clinic
            # auto-save as preferred hospital if user hasn't set one
            if not m.get("preferred_hospital"):
                m["preferred_hospital"] = clinic
        if doctor:
            m["last_doctor"] = doctor
            if not m.get("preferred_doctor"):
                m["preferred_doctor"] = doctor

    elif intent_type.value == "order_medicine":
        med = parameters.get("medication_name", parameters.get("medication", m.get("last_medication")))
        pharmacy = parameters.get("pharmacy_url", parameters.get("pharmacy", m.get("last_pharmacy")))
        if med:
            m["last_medication"] = med
        if pharmacy:
            m["last_pharmacy"] = pharmacy
            if not m.get("preferred_pharmacy"):
                m["preferred_pharmacy"] = pharmacy

    elif intent_type.value == "pay_bill":
        m["last_bill_type"] = parameters.get("bill_type", m.get("last_bill_type"))

    # log to task history
    summary = _build_task_summary(intent_type.value, parameters)
    log_task(session_id, intent_type.value, summary, success=True)

    _memory_cache[session_id] = m
    _save(session_id)


def _build_task_summary(intent: str, params: dict) -> str:
    if intent == "book_appointment":
        doctor = params.get("doctor", "doctor")
        date   = params.get("date", "tomorrow")
        return f"Appointment with {doctor} on {date}"
    elif intent == "order_medicine":
        med = params.get("medication_name", params.get("medication", "medicine"))
        return f"Ordered {med}"
    elif intent == "pay_bill":
        bill = params.get("bill_type", "bill")
        return f"Paid {bill} bill"
    elif intent == "send_message":
        recipient = params.get("recipient", "caregiver")
        return f"Message sent to {recipient}"
    elif intent == "fill_form":
        return f"Form submitted at {params.get('portal_url', 'portal')}"
    return f"Task: {intent}"


# ═══════════════════════════════════════════════════════════════════════════
#  SMART CONTEXT HINTS (upgraded from original)
# ═══════════════════════════════════════════════════════════════════════════

def get_context_hint(session_id: str) -> Optional[str]:
    """
    Returns the one-line intelligent hint shown to user before they speak.
    Now uses preferred settings and full history.
    """
    m = _get(session_id)

    last_intent = m.get("last_intent")
    pref_hosp   = m.get("preferred_hospital")
    pref_pharm  = m.get("preferred_pharmacy")
    pref_doc    = m.get("preferred_doctor")

    if last_intent == "book_appointment" and pref_hosp:
        return f"Last time you visited {pref_hosp}. Same clinic?"
    if last_intent == "book_appointment" and pref_doc:
        return f"Shall I book with Dr. {pref_doc} again?"
    if last_intent == "order_medicine" and m.get("last_medication"):
        pharm_hint = f" from {pref_pharm}" if pref_pharm else ""
        return f"Last time you ordered {m['last_medication']}{pharm_hint}. Refill again?"
    if last_intent == "pay_bill" and m.get("last_bill_type"):
        return f"Want to pay your {m['last_bill_type']} bill again?"

    return None


# ═══════════════════════════════════════════════════════════════════════════
#  PROACTIVE SUGGESTION ENGINE
#  Nova suggests help automatically — no command needed from user
# ═══════════════════════════════════════════════════════════════════════════

def get_proactive_suggestion(session_id: str, current_emotion: str = "calm") -> Optional[str]:
    """
    Returns a proactive suggestion based on:
      - current emotional state
      - missed medicines
      - medicines due for refill
      - time of day
      - recent task history

    Called by api/main.py after every pipeline run.
    """
    m = _get(session_id)

    # ── 1. Crisis / Distress: offer immediate help ────────────────────────
    if current_emotion in ("crisis", "distress"):
        caregiver = m.get("caregiver_name", "your caregiver")
        if m.get("preferred_doctor"):
            return (f"You seem distressed. I can call {caregiver} right now, "
                    f"or book an urgent appointment with Dr. {m['preferred_doctor']}. What do you need?")
        return f"You seem distressed. Shall I alert {caregiver} and book a doctor immediately?"

    # ── 2. Anxious: suggest calming + preventive action ──────────────────
    if current_emotion == "anxious":
        missed = get_missed_medicines(session_id)
        if missed:
            names = ", ".join([med["name"] for med in missed[:2]])
            return f"You seem anxious. Did you take your {names}? I can help you track it."
        if m.get("preferred_doctor"):
            return (f"You seem a little anxious today. "
                    f"Want me to schedule a check-up with Dr. {m['preferred_doctor']}?")

    # ── 3. Missed medicines ────────────────────────────────────────────────
    missed = get_missed_medicines(session_id)
    if missed:
        names = ", ".join([med["name"] for med in missed[:2]])
        extra = f" and {len(missed) - 2} more" if len(missed) > 2 else ""
        return f"Reminder: you haven't taken {names}{extra} today. Shall I set a reminder?"

    # ── 4. Medicines due for refill ────────────────────────────────────────
    due_refill = get_medicines_due_refill(session_id)
    if due_refill:
        name  = due_refill[0]["name"]
        pharm = m.get("preferred_pharmacy", "your pharmacy")
        return f"{name} needs a refill soon. Shall I order it from {pharm}?"

    # ── 5. Time-based suggestions ─────────────────────────────────────────
    hour = datetime.now().hour
    if 8 <= hour <= 10 and m.get("preferred_doctor"):
        # morning — suggest routine check if no recent appointment
        recent = [t for t in m["task_history"][-10:] if t["intent"] == "book_appointment"]
        if not recent:
            return f"Good morning! Want me to schedule your routine check-up with Dr. {m['preferred_doctor']}?"
    if 19 <= hour <= 21:
        # evening — remind about medicines or caregiver check-in
        if m.get("caregiver_name"):
            return f"Evening check-in: want me to send a quick update to {m['caregiver_name']}?"

    # ── 6. No suggestion needed ────────────────────────────────────────────
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  DASHBOARD STATS
# ═══════════════════════════════════════════════════════════════════════════

def get_dashboard_stats(session_id: str) -> dict:
    """
    Returns all stats for the caregiver dashboard.
    Called by /dashboard/stats every 5 seconds.
    """
    m = _get(session_id)
    emotional_summary = get_today_emotional_summary(session_id)
    weekly_trend      = get_weekly_emotional_trend(session_id)
    recent_tasks      = get_recent_tasks(session_id, limit=10)
    missed_meds       = get_missed_medicines(session_id)
    due_refills       = get_medicines_due_refill(session_id)

    return {
        # impact metrics
        "tasks_completed":     m.get("total_tasks_completed", 0),
        "hours_saved":         m.get("total_hours_saved", 0.0),
        "cost_saved_inr":      m.get("total_cost_saved_inr", 0.0),
        "alerts_triggered":    m.get("distress_count_today", 0),

        # emotional data
        "current_emotion":     emotional_summary.get("dominant", "calm"),
        "emotional_summary":   emotional_summary,
        "weekly_trend":        weekly_trend,

        # tasks
        "recent_tasks":        recent_tasks,

        # medicine
        "missed_medicines":    missed_meds,
        "due_refills":         due_refills,
        "medicine_schedule":   m.get("medicine_schedule", []),

        # preferences (for display)
        "preferred_hospital":  m.get("preferred_hospital"),
        "preferred_pharmacy":  m.get("preferred_pharmacy"),
        "preferred_doctor":    m.get("preferred_doctor"),
        "caregiver_name":      m.get("caregiver_name"),
        "user_name":           m.get("user_name"),
        "preferred_language":  m.get("preferred_language", "en"),
    }