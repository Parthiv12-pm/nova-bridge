"""
api/dashboard_routes.py — Upgraded
====================================
New endpoints added:
  GET /dashboard/activity-timeline     — hourly activity log for the day
  GET /dashboard/medicine-adherence    — today's medicine taken/missed
  GET /dashboard/weekly-score          — 7-day health score with trend
  GET /dashboard/behavior-report       — full weekly pattern analysis
  GET /dashboard/proactive-suggestion  — what Nova should suggest next

All new endpoints pull data from:
  - nova_bridge.core.session_memory    (emotion + task history)
  - nova_bridge.core.guard             (weekly pattern analysis)
"""

from fastapi import APIRouter, Query
from datetime import datetime, timedelta
from models.schemas import DashboardStats, CaregiverNotification

from core.guard import (
    get_notification_log,
    get_weekly_pattern_analysis,
    register_caregiver,
)
from core.session_memory import (
    get_dashboard_stats,
    get_today_emotional_summary,
    get_weekly_emotional_trend,
    get_emotional_history,
    get_recent_tasks,
    get_missed_medicines,
    get_medicines_due_refill,
    get_proactive_suggestion,
    get_full_memory,
)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# ── Shared stats object (backward compatible) ─────────────────────────────
_stats = DashboardStats()

def get_stats()            -> DashboardStats: return _stats
def increment_task(hours: float = 0.07):
    _stats.tasks_completed      += 1
    _stats.hours_saved          += hours
    _stats.caregiver_costs_saved = round(_stats.hours_saved * 80, 2)
def increment_alert():   _stats.alerts_triggered += 1
def increment_session(): _stats.active_sessions  += 1


# ═══════════════════════════════════════════════════════════════════════════
#  ORIGINAL ENDPOINTS (kept intact — backward compatible)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/stats", response_model=DashboardStats)
async def dashboard_stats(session_id: str = Query(None)):
    """
    Live impact metrics for the caregiver dashboard.
    If session_id provided, pulls from memory for richer data.
    Falls back to module-level _stats for backward compatibility.
    """
    if session_id:
        mem_stats = get_dashboard_stats(session_id)
        # sync module stats with memory stats
        _stats.tasks_completed      = mem_stats.get("tasks_completed", _stats.tasks_completed)
        _stats.hours_saved          = mem_stats.get("hours_saved",     _stats.hours_saved)
        _stats.caregiver_costs_saved = round(_stats.hours_saved * 80, 2)
        _stats.alerts_triggered     = mem_stats.get("alerts_triggered", _stats.alerts_triggered)
    return _stats


@router.get("/notifications")
async def dashboard_notifications(session_id: str = None):
    """All caregiver notifications, optionally filtered by session."""
    notifications = get_notification_log(session_id)
    return {"notifications": [n.dict() for n in notifications]}


@router.post("/register-caregiver")
async def register_caregiver_endpoint(
    session_id: str, name: str, phone: str, email: str
):
    """Register a caregiver for a user session."""
    register_caregiver(session_id, name, phone, email)
    return {"status": "registered", "session_id": session_id}


@router.get("/emotional-timeline")
async def emotional_timeline(session_id: str):
    """
    Emotional state history for the D3.js timeline chart.
    Now pulls from memory system instead of notification log only.
    """
    # rich data from memory
    history = get_emotional_history(session_id, days=1)
    timeline = [
        {
            "timestamp": entry["timestamp"],
            "emotion":   entry["emotion"],
            "score":     entry.get("score", 0.0),
            "trigger":   entry.get("trigger", ""),
        }
        for entry in history
    ]

    # also include notification-based events for backward compat
    notifications = get_notification_log(session_id)
    for n in notifications:
        timeline.append({
            "timestamp": n.timestamp,
            "emotion":   n.alert_type.value,
            "score":     1.0 if n.alert_type.value == "crisis" else 0.75,
            "trigger":   n.message,
        })

    # sort by timestamp, deduplicate
    seen = set()
    unique = []
    for item in sorted(timeline, key=lambda x: x["timestamp"]):
        key = item["timestamp"]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return {"session_id": session_id, "timeline": unique, "total": len(unique)}


@router.get("/impact-summary")
async def impact_summary(session_id: str = Query(None)):
    """Human-readable impact summary for the demo."""
    if session_id:
        mem = get_dashboard_stats(session_id)
        hours   = round(mem.get("hours_saved", _stats.hours_saved), 1)
        tasks   = mem.get("tasks_completed", _stats.tasks_completed)
        alerts  = mem.get("alerts_triggered", _stats.alerts_triggered)
        savings = round(hours * 6640, 0)   # INR equivalent
    else:
        hours   = round(_stats.hours_saved, 1)
        tasks   = _stats.tasks_completed
        alerts  = _stats.alerts_triggered
        savings = round(_stats.caregiver_costs_saved * 83, 0)  # USD → INR

    return {
        "summary": (
            f"Nova Bridge saved {hours} hours this week "
            f"— ₹{int(savings):,} in caregiver costs."
        ),
        "tasks_completed":  tasks,
        "alerts_triggered": alerts,
        "active_sessions":  _stats.active_sessions,
        "hours_saved":      hours,
        "cost_saved_inr":   int(savings),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  NEW ENDPOINT 1 — Activity Timeline
#  Shows every interaction in the day with time + type + outcome
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/activity-timeline")
async def activity_timeline(
    session_id: str,
    days: int = Query(1, ge=1, le=7)
):
    """
    Full daily activity timeline — every task + every emotion event.
    Used by the caregiver dashboard to show what happened hour by hour.

    Example output entry:
      {timestamp, hour_label, type: "task|emotion|medicine|alert",
       icon, label, detail, severity}
    """
    events = []

    # ── 1. Task events ────────────────────────────────────────────────────
    recent_tasks = get_recent_tasks(session_id, limit=50)
    icon_map = {
        "book_appointment": "🏥",
        "order_medicine":   "💊",
        "pay_bill":         "💳",
        "send_message":     "💬",
        "fill_form":        "📋",
    }
    for task in recent_tasks:
        ts = task.get("timestamp", "")
        if not _within_days(ts, days):
            continue
        events.append({
            "timestamp":   ts,
            "hour_label":  _hour_label(ts),
            "type":        "task",
            "icon":        icon_map.get(task.get("intent", ""), "✅"),
            "label":       task.get("summary", task.get("intent", "Task")),
            "detail":      "Completed successfully" if task.get("success") else "Failed",
            "severity":    "success" if task.get("success") else "warning",
        })

    # ── 2. Emotion events ─────────────────────────────────────────────────
    emotion_history = get_emotional_history(session_id, days=days)
    emotion_icon = {"calm": "😌", "anxious": "😰", "distress": "😢", "crisis": "🚨"}
    emotion_severity = {"calm": "success", "anxious": "warning", "distress": "danger", "crisis": "danger"}
    for entry in emotion_history:
        events.append({
            "timestamp":  entry["timestamp"],
            "hour_label": _hour_label(entry["timestamp"]),
            "type":       "emotion",
            "icon":       emotion_icon.get(entry["emotion"], "❓"),
            "label":      f"{entry['emotion'].title()} detected",
            "detail":     entry.get("trigger", ""),
            "severity":   emotion_severity.get(entry["emotion"], "info"),
            "score":      entry.get("score", 0.0),
        })

    # ── 3. Medicine events ────────────────────────────────────────────────
    m = get_full_memory(session_id)
    for med in m.get("medicine_schedule", []):
        if med.get("last_taken") and _within_days(med["last_taken"], days):
            events.append({
                "timestamp":  med["last_taken"],
                "hour_label": _hour_label(med["last_taken"]),
                "type":       "medicine",
                "icon":       "💊",
                "label":      f"{med['name']} taken",
                "detail":     f"{med['dose']} at {med['time']}",
                "severity":   "success",
            })
        elif not med.get("taken_today"):
            scheduled_ts = _today_at(med.get("time", "08:00"))
            events.append({
                "timestamp":  scheduled_ts,
                "hour_label": med.get("time", "08:00"),
                "type":       "medicine_missed",
                "icon":       "⚠️",
                "label":      f"{med['name']} missed",
                "detail":     f"Scheduled at {med['time']} — not taken",
                "severity":   "warning",
            })

    # ── 4. Caregiver alert events ─────────────────────────────────────────
    for notif in get_notification_log(session_id):
        if not _within_days(notif.timestamp, days):
            continue
        events.append({
            "timestamp":  notif.timestamp,
            "hour_label": _hour_label(notif.timestamp),
            "type":       "alert",
            "icon":       "🚨",
            "label":      f"Caregiver alerted — {notif.alert_type.value}",
            "detail":     notif.message,
            "severity":   "danger",
        })

    # sort all events by time
    events.sort(key=lambda x: x.get("timestamp", ""))

    return {
        "session_id":   session_id,
        "days":         days,
        "total_events": len(events),
        "timeline":     events,
        "generated_at": datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  NEW ENDPOINT 2 — Medicine Adherence
#  Shows today's medicine schedule with taken/missed status
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/medicine-adherence")
async def medicine_adherence(session_id: str):
    """
    Today's medicine adherence report.
    Shows every medicine: taken ✓ or missed ⚠, plus refills due.

    Used by caregiver dashboard medicine chart.
    """
    m              = get_full_memory(session_id)
    schedule       = m.get("medicine_schedule", [])
    missed         = get_missed_medicines(session_id)
    due_refills    = get_medicines_due_refill(session_id)

    missed_names   = {med["name"].lower() for med in missed}
    refill_names   = {med["name"].lower() for med in due_refills}

    enriched = []
    for med in schedule:
        name_lower = med["name"].lower()
        enriched.append({
            "name":        med["name"],
            "dose":        med.get("dose", ""),
            "time":        med.get("time", ""),
            "taken_today": med.get("taken_today", False),
            "last_taken":  med.get("last_taken"),
            "refill_due":  med.get("refill_due"),
            "needs_refill": name_lower in refill_names,
            "status":      "taken" if med.get("taken_today") else "missed" if name_lower in missed_names else "pending",
            "status_icon": "✓" if med.get("taken_today") else "⚠" if name_lower in missed_names else "🕐",
        })

    taken_count  = sum(1 for med in enriched if med["status"] == "taken")
    total_count  = len(enriched)
    adherence_pct = round((taken_count / total_count * 100) if total_count else 100, 1)

    return {
        "session_id":     session_id,
        "date":           datetime.now().strftime("%Y-%m-%d"),
        "schedule":       enriched,
        "total":          total_count,
        "taken":          taken_count,
        "missed":         len(missed),
        "pending":        total_count - taken_count - len(missed),
        "adherence_pct":  adherence_pct,
        "due_refills":    due_refills,
        "refill_count":   len(due_refills),
        "adherence_status": (
            "excellent" if adherence_pct >= 90 else
            "good"      if adherence_pct >= 70 else
            "poor"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  NEW ENDPOINT 3 — Weekly Health Score
#  Composite score combining emotion stability + medicine adherence + tasks
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/weekly-score")
async def weekly_health_score(session_id: str):
    """
    Composite weekly health score (0–100).
    Combines:
      - Emotional stability (40 pts)
      - Medicine adherence (35 pts)
      - Task self-sufficiency (25 pts)

    Used by caregiver dashboard weekly score chart.
    """
    weekly_trend = get_weekly_emotional_trend(session_id)
    m            = get_full_memory(session_id)

    # ── Emotional stability score (40 pts) ────────────────────────────────
    total_distress = sum(d["distress_count"] for d in weekly_trend)
    total_calm     = sum(d["calm_count"] for d in weekly_trend)
    total_entries  = sum(d["total_entries"] for d in weekly_trend)

    if total_entries == 0:
        emotion_score = 35  # neutral default
    else:
        calm_ratio    = total_calm / total_entries
        emotion_score = round(calm_ratio * 40)
        # penalty for distress events
        emotion_score = max(0, emotion_score - (total_distress * 2))
        emotion_score = min(40, emotion_score)

    # ── Medicine adherence score (35 pts) ─────────────────────────────────
    schedule       = m.get("medicine_schedule", [])
    missed_this_week = m.get("missed_medicines", 0)
    if not schedule:
        medicine_score = 30  # no medicines = neutral
    else:
        expected_doses = len(schedule) * 7
        taken_doses    = max(0, expected_doses - missed_this_week)
        medicine_score = round((taken_doses / expected_doses) * 35) if expected_doses else 30
        medicine_score = min(35, medicine_score)

    # ── Task self-sufficiency score (25 pts) ──────────────────────────────
    tasks_this_week = len([
        t for t in m.get("task_history", [])
        if _within_days(t.get("timestamp", ""), 7) and t.get("success")
    ])
    task_score = min(25, tasks_this_week * 4)  # 4 pts per successful task, max 25

    total_score = emotion_score + medicine_score + task_score

    # per-day score for chart
    daily_scores = []
    for day in weekly_trend:
        d_entries  = day["total_entries"] or 1
        d_calm     = day["calm_count"]
        d_distress = day["distress_count"]
        d_score    = round((d_calm / d_entries) * 100) - (d_distress * 5)
        d_score    = max(0, min(100, d_score))
        daily_scores.append({
            "date":       day["date"],
            "day_label":  day["day_label"],
            "score":      d_score,
            "dominant":   day["dominant"],
        })

    # trend direction
    if len(daily_scores) >= 4:
        first_avg = sum(d["score"] for d in daily_scores[:3]) / 3
        last_avg  = sum(d["score"] for d in daily_scores[-3:]) / 3
        trend = "improving" if last_avg > first_avg + 5 else "declining" if last_avg < first_avg - 5 else "stable"
    else:
        trend = "stable"

    return {
        "session_id":      session_id,
        "week_of":         (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d"),
        "total_score":     total_score,
        "max_score":       100,
        "grade":           _score_grade(total_score),
        "trend":           trend,
        "breakdown": {
            "emotional_stability": {"score": emotion_score, "max": 40},
            "medicine_adherence":  {"score": medicine_score, "max": 35},
            "task_sufficiency":    {"score": task_score,    "max": 25},
        },
        "daily_scores":    daily_scores,
        "generated_at":    datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  NEW ENDPOINT 4 — Behavior Report
#  Full weekly behavioral analysis for caregiver review
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/behavior-report")
async def behavior_report(session_id: str):
    """
    Full behavioral analysis report for the week.
    Combines emotional patterns, medicine adherence, anomalies, and recommendations.
    This is the most comprehensive endpoint — used by caregiver's weekly review.
    """
    # pull all data sources
    pattern_analysis  = get_weekly_pattern_analysis(session_id)
    today_summary     = get_today_emotional_summary(session_id)
    weekly_trend      = get_weekly_emotional_trend(session_id)
    m                 = get_full_memory(session_id)
    missed_meds       = get_missed_medicines(session_id)
    due_refills       = get_medicines_due_refill(session_id)
    recent_tasks      = get_recent_tasks(session_id, limit=20)
    notifications     = get_notification_log(session_id)

    # alerts this week
    alerts_this_week = [
        n for n in notifications
        if _within_days(n.timestamp, 7)
    ]

    # tasks this week
    tasks_this_week = [
        t for t in recent_tasks
        if _within_days(t.get("timestamp", ""), 7)
    ]

    # build daily breakdown
    daily_breakdown = []
    for day in weekly_trend:
        day_tasks = [
            t for t in m.get("task_history", [])
            if t.get("timestamp", "").startswith(day["date"])
        ]
        daily_breakdown.append({
            "date":          day["date"],
            "day_label":     day["day_label"],
            "dominant_emotion": day["dominant"],
            "distress_count":   day["distress_count"],
            "calm_count":       day["calm_count"],
            "anxious_count":    day["anxious_count"],
            "tasks_completed":  len([t for t in day_tasks if t.get("success")]),
            "total_interactions": day["total_entries"],
        })

    # compute summary flags
    high_distress_week = pattern_analysis.get("total_distress", 0) >= 5
    medicine_concern   = len(missed_meds) > 0 or len(due_refills) > 0
    needs_attention    = high_distress_week or medicine_concern

    return {
        "session_id":       session_id,
        "report_period":    {
            "from": (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d"),
            "to":   datetime.now().strftime("%Y-%m-%d"),
        },

        # today's snapshot
        "today": {
            "dominant_emotion":  today_summary.get("dominant", "calm"),
            "distress_events":   today_summary.get("distress_count", 0),
            "total_interactions": today_summary.get("entries", 0),
            "missed_medicines":  [med["name"] for med in missed_meds],
        },

        # weekly pattern
        "weekly_pattern": {
            "risk_level":       pattern_analysis.get("risk_level", "low"),
            "risk_message":     pattern_analysis.get("risk_message", ""),
            "total_distress":   pattern_analysis.get("total_distress", 0),
            "high_risk_days":   pattern_analysis.get("high_risk_days", 0),
            "improving":        pattern_analysis.get("improving", False),
            "worst_day":        pattern_analysis.get("worst_day"),
        },

        # daily breakdown for chart
        "daily_breakdown": daily_breakdown,

        # medicine
        "medicine": {
            "total_medicines":  len(m.get("medicine_schedule", [])),
            "missed_today":     [med["name"] for med in missed_meds],
            "due_refill":       [med["name"] for med in due_refills],
            "missed_this_week": m.get("missed_medicines", 0),
        },

        # task activity
        "tasks": {
            "this_week":      len(tasks_this_week),
            "successful":     len([t for t in tasks_this_week if t.get("success")]),
            "recent":         tasks_this_week[:5],
        },

        # alerts
        "alerts": {
            "this_week":      len(alerts_this_week),
            "today":          today_summary.get("distress_count", 0),
            "log":            [
                {"timestamp": n.timestamp, "level": n.alert_type.value, "message": n.message}
                for n in alerts_this_week[-5:]
            ],
        },

        # summary flags and recommendation
        "flags": {
            "needs_attention":    needs_attention,
            "high_distress_week": high_distress_week,
            "medicine_concern":   medicine_concern,
        },
        "recommendation": pattern_analysis.get("recommendation", "Continue monitoring."),
        "generated_at":   datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  NEW ENDPOINT 5 — Proactive Suggestion
#  What should Nova say next, without user asking?
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/proactive-suggestion")
async def proactive_suggestion(
    session_id: str,
    current_emotion: str = Query("calm")
):
    """
    Returns Nova's next proactive suggestion for the user.
    Called by frontend every 30 seconds to check if Nova should speak up.
    """
    suggestion = get_proactive_suggestion(session_id, current_emotion)
    return {
        "session_id":  session_id,
        "suggestion":  suggestion,
        "has_suggestion": suggestion is not None,
        "emotion":     current_emotion,
        "checked_at":  datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _within_days(ts: str, days: int) -> bool:
    """True if timestamp string is within last N days."""
    if not ts:
        return False
    try:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return ts >= cutoff
    except:
        return False


def _hour_label(ts: str) -> str:
    """Converts ISO timestamp to readable time like '10:30 AM'."""
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%I:%M %p")
    except:
        return ts[:16] if len(ts) >= 16 else ts


def _today_at(time_str: str) -> str:
    """Returns today's date + given time as ISO string. e.g. '08:00' → '2025-01-15T08:00:00'"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        return f"{today}T{time_str}:00"
    except:
        return datetime.now().isoformat()


def _score_grade(score: int) -> str:
    if score >= 85: return "A — Excellent"
    if score >= 70: return "B — Good"
    if score >= 55: return "C — Fair"
    if score >= 40: return "D — Needs attention"
    return "F — Urgent review needed"