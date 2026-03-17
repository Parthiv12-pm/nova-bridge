"""
core/behavior_tracker.py — NEW FILE
=====================================
Daily and weekly behavioral habit tracking for Nova Bridge.
Monitors medicine adherence, activity patterns, inactivity,
routine deviations, and generates caregiver alerts.

What it tracks:
  - Medicine taken / missed by hour
  - User activity (interactions per hour)
  - Inactivity periods (no interaction for N hours)
  - Routine deviations (sleeping late, skipping medicine)
  - Weekly habit score trends

Called by:
  - core/guard.py          (logs emotion + checks inactivity)
  - api/main.py            (logs every pipeline interaction)
  - api/behavior_routes.py (serves data to dashboard)
  - api/dashboard_routes.py (behavior-report endpoint)
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

from core.session_memory import (
    get_full_memory,
    get_missed_medicines,
    get_medicines_due_refill,
    get_emotional_history,
    get_weekly_emotional_trend,
    get_today_emotional_summary,
    log_emotion,
    _get,
    _save,
)


# ═══════════════════════════════════════════════════════════════════════════
#  IN-MEMORY ACTIVITY LOG
#  Tracks interactions per session per hour — lightweight, no disk write
# ═══════════════════════════════════════════════════════════════════════════

# structure: {session_id: [{timestamp, type, detail}]}
_activity_log: Dict[str, List[dict]] = {}

# structure: {session_id: last_interaction_timestamp}
_last_interaction: Dict[str, str] = {}

# thresholds
INACTIVITY_ALERT_HOURS   = 4    # alert caregiver after N hours of silence
MEDICINE_MISSED_ALERT    = 2    # alert after missing N medicines in one day
DISTRESS_PATTERN_DAYS    = 3    # alert if distress on 3+ consecutive days


# ═══════════════════════════════════════════════════════════════════════════
#  ACTIVITY LOGGING
# ═══════════════════════════════════════════════════════════════════════════

def log_interaction(session_id: str, interaction_type: str, detail: str = ""):
    """
    Log every user interaction — voice command, button press, camera use.
    Called by api/main.py after every pipeline request.

    interaction_type: "voice" | "camera" | "demo" | "task" | "emotion"
    """
    now = datetime.now().isoformat()

    if session_id not in _activity_log:
        _activity_log[session_id] = []

    _activity_log[session_id].append({
        "timestamp": now,
        "type":      interaction_type,
        "detail":    detail,
        "hour":      datetime.now().hour,
    })

    # keep only last 200 interactions per session
    _activity_log[session_id] = _activity_log[session_id][-200:]

    # update last interaction time
    _last_interaction[session_id] = now


def get_today_activity(session_id: str) -> List[dict]:
    """Returns all interactions logged today."""
    today = datetime.now().strftime("%Y-%m-%d")
    return [
        a for a in _activity_log.get(session_id, [])
        if a["timestamp"].startswith(today)
    ]


def get_hourly_activity(session_id: str) -> List[dict]:
    """
    Returns interaction count per hour for today.
    Used by the activity heatmap on the dashboard.
    Format: [{hour: 8, count: 3, types: ["voice", "task"]}, ...]
    """
    today_activity = get_today_activity(session_id)
    hourly: Dict[int, dict] = {}

    for entry in today_activity:
        hour = entry.get("hour", 0)
        if hour not in hourly:
            hourly[hour] = {"hour": hour, "count": 0, "types": set()}
        hourly[hour]["count"] += 1
        hourly[hour]["types"].add(entry["type"])

    # fill all 24 hours (0-23) even if no activity
    result = []
    for h in range(24):
        if h in hourly:
            result.append({
                "hour":       h,
                "hour_label": _hour_label(h),
                "count":      hourly[h]["count"],
                "types":      list(hourly[h]["types"]),
                "active":     True,
            })
        else:
            result.append({
                "hour":       h,
                "hour_label": _hour_label(h),
                "count":      0,
                "types":      [],
                "active":     False,
            })

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  INACTIVITY DETECTION
# ═══════════════════════════════════════════════════════════════════════════

def check_inactivity(session_id: str) -> Optional[dict]:
    """
    Returns an inactivity alert if user hasn't interacted in N hours.
    Returns None if user is active.

    Called by api/main.py periodically or by a background scheduler.
    """
    last = _last_interaction.get(session_id)
    if not last:
        return None

    try:
        last_dt      = datetime.fromisoformat(last)
        hours_silent = (datetime.now() - last_dt).total_seconds() / 3600
    except:
        return None

    if hours_silent >= INACTIVITY_ALERT_HOURS:
        m = get_full_memory(session_id)
        return {
            "type":          "inactivity",
            "session_id":    session_id,
            "hours_silent":  round(hours_silent, 1),
            "last_seen":     last,
            "threshold_hrs": INACTIVITY_ALERT_HOURS,
            "severity":      "high" if hours_silent >= 8 else "medium",
            "message": (
                f"User has been inactive for {round(hours_silent, 1)} hours. "
                f"Last interaction at {_friendly_time(last)}. "
                f"Consider checking in."
            ),
            "user_name":     m.get("user_name", "User"),
            "caregiver":     m.get("caregiver_name", "Caregiver"),
        }

    return None


def get_inactivity_status(session_id: str) -> dict:
    """Returns current inactivity status without triggering an alert."""
    last = _last_interaction.get(session_id)
    if not last:
        return {"active": False, "hours_since": None, "last_seen": None}

    try:
        last_dt      = datetime.fromisoformat(last)
        hours_silent = (datetime.now() - last_dt).total_seconds() / 3600
        return {
            "active":       hours_silent < 1,
            "hours_since":  round(hours_silent, 2),
            "last_seen":    last,
            "status":       "active" if hours_silent < 1 else "idle" if hours_silent < INACTIVITY_ALERT_HOURS else "inactive",
        }
    except:
        return {"active": False, "hours_since": None, "last_seen": last}


# ═══════════════════════════════════════════════════════════════════════════
#  MEDICINE BEHAVIOR TRACKING
# ═══════════════════════════════════════════════════════════════════════════

def get_medicine_behavior(session_id: str) -> dict:
    """
    Analyzes medicine-taking behavior patterns.
    Returns adherence stats, missed patterns, refill alerts.
    """
    m            = get_full_memory(session_id)
    schedule     = m.get("medicine_schedule", [])
    missed_today = get_missed_medicines(session_id)
    due_refills  = get_medicines_due_refill(session_id)

    if not schedule:
        return {
            "has_schedule":    False,
            "total_medicines": 0,
            "taken_today":     0,
            "missed_today":    0,
            "adherence_pct":   100.0,
            "due_refills":     [],
            "alerts":          [],
        }

    taken_today  = [med for med in schedule if med.get("taken_today")]
    total        = len(schedule)
    taken_count  = len(taken_today)
    missed_count = len(missed_today)
    adherence    = round((taken_count / total * 100) if total else 100, 1)

    # build alerts
    alerts = []
    if missed_count >= MEDICINE_MISSED_ALERT:
        missed_names = ", ".join([med["name"] for med in missed_today])
        alerts.append({
            "type":     "medicine_missed",
            "severity": "high" if missed_count >= 3 else "medium",
            "message":  f"{missed_count} medicines missed today: {missed_names}",
        })

    for med in due_refills:
        alerts.append({
            "type":     "refill_due",
            "severity": "medium",
            "message":  f"{med['name']} needs refill by {med.get('refill_due', 'soon')}",
        })

    return {
        "has_schedule":    True,
        "total_medicines": total,
        "taken_today":     taken_count,
        "missed_today":    missed_count,
        "adherence_pct":   adherence,
        "taken_list":      [med["name"] for med in taken_today],
        "missed_list":     [med["name"] for med in missed_today],
        "due_refills":     [med["name"] for med in due_refills],
        "alerts":          alerts,
        "adherence_status": (
            "excellent" if adherence >= 90 else
            "good"      if adherence >= 70 else
            "poor"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  ROUTINE DEVIATION DETECTION
#  Detects when user's behavior deviates from their normal pattern
# ═══════════════════════════════════════════════════════════════════════════

def detect_routine_deviations(session_id: str) -> List[dict]:
    """
    Compares today's behavior to the user's established routine.
    Returns list of deviation alerts.

    Checks:
      - Missing morning medicine (usually taken by 10am)
      - Unusual silence during normally active hours
      - Night-time distress (between 10pm–5am)
      - More distress than usual for this day of week
    """
    deviations = []
    m           = get_full_memory(session_id)
    now         = datetime.now()
    hour        = now.hour
    today_summary = get_today_emotional_summary(session_id)

    # ── 1. Morning medicine check (after 10am) ────────────────────────────
    if hour >= 10:
        schedule = m.get("medicine_schedule", [])
        morning_meds = [
            med for med in schedule
            if _parse_hour(med.get("time", "")) <= 9
            and not med.get("taken_today")
        ]
        if morning_meds:
            names = ", ".join([med["name"] for med in morning_meds])
            deviations.append({
                "type":     "missed_morning_medicine",
                "severity": "medium",
                "time":     now.strftime("%H:%M"),
                "message":  f"Morning medicine not taken: {names}",
            })

    # ── 2. Unusual inactivity during active hours (9am–6pm) ──────────────
    if 9 <= hour <= 18:
        inactivity = check_inactivity(session_id)
        if inactivity and inactivity["hours_silent"] >= 3:
            deviations.append({
                "type":     "daytime_inactivity",
                "severity": "medium",
                "time":     now.strftime("%H:%M"),
                "message":  f"No activity for {inactivity['hours_silent']} hours during daytime",
            })

    # ── 3. Night-time distress (10pm–5am) ────────────────────────────────
    if hour >= 22 or hour <= 5:
        if today_summary.get("distress_count", 0) > 0:
            deviations.append({
                "type":     "night_distress",
                "severity": "high",
                "time":     now.strftime("%H:%M"),
                "message":  "Distress detected during night hours. User may need support.",
            })

    # ── 4. High distress day compared to weekly average ──────────────────
    weekly = get_weekly_emotional_trend(session_id)
    if len(weekly) >= 5:
        avg_distress = sum(d["distress_count"] for d in weekly[:-1]) / max(len(weekly) - 1, 1)
        today_distress = today_summary.get("distress_count", 0)
        if today_distress > avg_distress * 2 and today_distress >= 3:
            deviations.append({
                "type":     "high_distress_day",
                "severity": "high",
                "time":     now.strftime("%H:%M"),
                "message":  (
                    f"Today's distress ({today_distress} events) is "
                    f"much higher than weekly average ({avg_distress:.1f}). "
                    f"Urgent caregiver review recommended."
                ),
            })

    return deviations


# ═══════════════════════════════════════════════════════════════════════════
#  CONSECUTIVE DISTRESS PATTERN
# ═══════════════════════════════════════════════════════════════════════════

def check_consecutive_distress_days(session_id: str) -> Optional[dict]:
    """
    Checks if user has had distress on 3+ consecutive days.
    This is a serious pattern that warrants a doctor visit recommendation.
    """
    weekly = get_weekly_emotional_trend(session_id)
    if len(weekly) < DISTRESS_PATTERN_DAYS:
        return None

    # check last N days for consecutive distress
    recent = weekly[-DISTRESS_PATTERN_DAYS:]
    all_distressed = all(day["distress_count"] >= 1 for day in recent)

    if all_distressed:
        total = sum(day["distress_count"] for day in recent)
        return {
            "type":           "consecutive_distress",
            "days":           DISTRESS_PATTERN_DAYS,
            "total_events":   total,
            "severity":       "high",
            "message": (
                f"User has shown distress on {DISTRESS_PATTERN_DAYS} consecutive days "
                f"({total} total events). A doctor consultation is strongly recommended."
            ),
            "recommendation": "Schedule a doctor appointment as soon as possible.",
        }

    return None


# ═══════════════════════════════════════════════════════════════════════════
#  DAILY REPORT
#  Complete daily behavioral summary — used by /behavior/today endpoint
# ═══════════════════════════════════════════════════════════════════════════

def get_daily_report(session_id: str) -> dict:
    """
    Complete daily behavioral report.
    Combines activity, emotion, medicine, deviations, and alerts.
    """
    now           = datetime.now()
    today_summary = get_today_emotional_summary(session_id)
    today_activity = get_today_activity(session_id)
    hourly        = get_hourly_activity(session_id)
    medicine      = get_medicine_behavior(session_id)
    deviations    = detect_routine_deviations(session_id)
    inactivity    = get_inactivity_status(session_id)
    consec        = check_consecutive_distress_days(session_id)

    # all alerts combined
    all_alerts = []
    all_alerts.extend(medicine.get("alerts", []))
    for dev in deviations:
        all_alerts.append({
            "type":     dev["type"],
            "severity": dev["severity"],
            "message":  dev["message"],
        })
    if consec:
        all_alerts.append({
            "type":     consec["type"],
            "severity": consec["severity"],
            "message":  consec["message"],
        })

    # overall day risk
    high_alerts = [a for a in all_alerts if a["severity"] == "high"]
    med_alerts  = [a for a in all_alerts if a["severity"] == "medium"]
    if high_alerts:
        day_risk = "high"
    elif med_alerts:
        day_risk = "medium"
    else:
        day_risk = "low"

    return {
        "session_id":   session_id,
        "date":         now.strftime("%Y-%m-%d"),
        "day_label":    now.strftime("%A, %B %d"),
        "generated_at": now.isoformat(),

        # activity
        "activity": {
            "total_interactions": len(today_activity),
            "hourly_breakdown":   hourly,
            "inactivity":         inactivity,
            "peak_hour":          _peak_hour(hourly),
        },

        # emotion
        "emotion": {
            "dominant":       today_summary.get("dominant", "calm"),
            "distress_count": today_summary.get("distress_count", 0),
            "calm_count":     today_summary.get("emotion_counts", {}).get("calm", 0),
            "anxious_count":  today_summary.get("emotion_counts", {}).get("anxious", 0),
            "timeline":       today_summary.get("timeline", []),
        },

        # medicine
        "medicine": medicine,

        # deviations
        "deviations":    deviations,
        "deviation_count": len(deviations),

        # alerts
        "alerts":       all_alerts,
        "alert_count":  len(all_alerts),
        "day_risk":     day_risk,

        # consecutive pattern
        "consecutive_distress": consec,

        # summary line for caregiver
        "summary": _build_day_summary(today_summary, medicine, deviations, day_risk),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  WEEKLY REPORT
#  Complete weekly behavioral report — used by /behavior/weekly endpoint
# ═══════════════════════════════════════════════════════════════════════════

def get_weekly_report(session_id: str) -> dict:
    """
    Full 7-day behavioral report.
    Aggregates daily data into weekly patterns and trends.
    """
    now    = datetime.now()
    weekly = get_weekly_emotional_trend(session_id)
    m      = get_full_memory(session_id)
    consec = check_consecutive_distress_days(session_id)

    # aggregate weekly stats
    total_distress  = sum(d["distress_count"] for d in weekly)
    total_calm      = sum(d["calm_count"] for d in weekly)
    total_anxious   = sum(d["anxious_count"] for d in weekly)
    high_risk_days  = [d for d in weekly if d["distress_count"] >= 2]
    best_day        = min(weekly, key=lambda d: d["distress_count"]) if weekly else None
    worst_day       = max(weekly, key=lambda d: d["distress_count"]) if weekly else None

    # trend
    if len(weekly) >= 4:
        first_half   = sum(d["distress_count"] for d in weekly[:3])
        second_half  = sum(d["distress_count"] for d in weekly[4:])
        trend = "improving" if second_half < first_half else "declining" if second_half > first_half else "stable"
    else:
        trend = "stable"

    # weekly medicine stats
    schedule          = m.get("medicine_schedule", [])
    missed_this_week  = m.get("missed_medicines", 0)
    expected_doses    = len(schedule) * 7
    taken_doses       = max(0, expected_doses - missed_this_week)
    med_adherence_pct = round((taken_doses / expected_doses * 100) if expected_doses else 100, 1)

    # weekly task stats
    week_cutoff = (now - timedelta(days=7)).isoformat()
    tasks_this_week = [
        t for t in m.get("task_history", [])
        if t.get("timestamp", "") >= week_cutoff
    ]

    return {
        "session_id":  session_id,
        "week_of":     (now - timedelta(days=6)).strftime("%Y-%m-%d"),
        "to":          now.strftime("%Y-%m-%d"),
        "generated_at": now.isoformat(),

        # emotion summary
        "emotion": {
            "total_distress":   total_distress,
            "total_calm":       total_calm,
            "total_anxious":    total_anxious,
            "high_risk_days":   len(high_risk_days),
            "best_day":         best_day,
            "worst_day":        worst_day,
            "trend":            trend,
            "daily_breakdown":  weekly,
        },

        # medicine
        "medicine": {
            "total_medicines":    len(schedule),
            "expected_doses":     expected_doses,
            "taken_doses":        taken_doses,
            "missed_doses":       missed_this_week,
            "adherence_pct":      med_adherence_pct,
            "due_refills":        get_medicines_due_refill(session_id),
        },

        # tasks
        "tasks": {
            "total_this_week":  len(tasks_this_week),
            "successful":       len([t for t in tasks_this_week if t.get("success")]),
            "types":            _count_task_types(tasks_this_week),
        },

        # patterns
        "patterns": {
            "consecutive_distress": consec,
            "improving":            trend == "improving",
            "high_risk_week":       total_distress >= 8 or len(high_risk_days) >= 3,
        },

        # recommendation
        "risk_level":    _weekly_risk(total_distress, len(high_risk_days), med_adherence_pct),
        "recommendation": _weekly_recommendation(total_distress, len(high_risk_days), trend, med_adherence_pct),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _parse_hour(time_str: str) -> int:
    """Parse '08:00' → 8"""
    try:
        return int(time_str.split(":")[0])
    except:
        return 8


def _hour_label(hour: int) -> str:
    """Convert 14 → '2 PM'"""
    if hour == 0:   return "12 AM"
    if hour < 12:   return f"{hour} AM"
    if hour == 12:  return "12 PM"
    return f"{hour - 12} PM"


def _friendly_time(iso_ts: str) -> str:
    """Convert ISO timestamp to friendly time string."""
    try:
        return datetime.fromisoformat(iso_ts).strftime("%I:%M %p")
    except:
        return iso_ts


def _peak_hour(hourly: List[dict]) -> Optional[dict]:
    """Returns the hour with most activity."""
    active = [h for h in hourly if h["count"] > 0]
    if not active:
        return None
    return max(active, key=lambda h: h["count"])


def _count_task_types(tasks: List[dict]) -> dict:
    """Count tasks by intent type."""
    counts = {}
    for t in tasks:
        intent = t.get("intent", "unknown")
        counts[intent] = counts.get(intent, 0) + 1
    return counts


def _build_day_summary(emotion: dict, medicine: dict, deviations: List, risk: str) -> str:
    """Build a one-line summary for the daily report."""
    emotion_word = emotion.get("dominant", "calm")
    distress     = emotion.get("distress_count", 0)
    missed_meds  = medicine.get("missed_today", 0)

    if risk == "high":
        return (
            f"High-risk day — {distress} distress events, "
            f"{missed_meds} medicines missed, {len(deviations)} routine deviations. "
            f"Immediate caregiver attention recommended."
        )
    if risk == "medium":
        parts = []
        if distress > 0:
            parts.append(f"{distress} distress events")
        if missed_meds > 0:
            parts.append(f"{missed_meds} medicines missed")
        return f"Moderate day — {', '.join(parts)}. Monitor closely." if parts else "Moderate day. Some deviations noted."
    return f"Good day — mostly {emotion_word}. Routine on track."


def _weekly_risk(total_distress: int, high_risk_days: int, med_adherence: float) -> str:
    if total_distress >= 10 or high_risk_days >= 4 or med_adherence < 50:
        return "high"
    if total_distress >= 5 or high_risk_days >= 2 or med_adherence < 75:
        return "medium"
    return "low"


def _weekly_recommendation(distress: int, high_days: int, trend: str, adherence: float) -> str:
    if distress >= 10 or high_days >= 4:
        return "Urgent: Schedule a doctor appointment. Daily caregiver check-ins recommended."
    if distress >= 5 and trend == "declining":
        return "Situation worsening. Schedule a wellness call and review medicine routine."
    if distress >= 5 and trend == "improving":
        return "Improving but still elevated. Continue monitoring. Keep current support plan."
    if adherence < 75:
        return "Medicine adherence needs attention. Set reminders and check for side effects."
    return "User is doing well this week. Maintain current routine and check-in schedule."