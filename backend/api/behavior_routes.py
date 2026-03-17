"""
api/behavior_routes.py — NEW FILE
===================================
Dedicated API endpoints for behavioral data.
All endpoints pull from behavior_tracker.py and session_memory.py.

Endpoints:
  GET /behavior/today              — full daily behavioral report
  GET /behavior/weekly             — full 7-day behavioral report
  GET /behavior/medicine-log       — medicine taken/missed log
  GET /behavior/alert-history      — all alerts triggered this session
  GET /behavior/activity-heatmap   — hourly interaction heatmap
  GET /behavior/inactivity-check   — is user currently inactive?
  GET /behavior/deviations         — today's routine deviations
  POST /behavior/log-interaction   — manually log an interaction
  POST /behavior/mark-medicine     — mark a medicine as taken

Called by:
  - frontend/js/app.js             (caregiver dashboard charts)
  - api/main.py                    (registers this router)
"""

from fastapi import APIRouter, Query
from datetime import datetime
from typing import Optional

from core.behavior_tracker import (
    get_daily_report,
    get_weekly_report,
    get_medicine_behavior,
    get_hourly_activity,
    get_today_activity,
    check_inactivity,
    get_inactivity_status,
    detect_routine_deviations,
    check_consecutive_distress_days,
    log_interaction,
)
from core.session_memory import (
    get_full_memory,
    get_recent_tasks,
    get_emotional_history,
    get_weekly_emotional_trend,
    get_missed_medicines,
    get_medicines_due_refill,
    mark_medicine_taken,
    get_preferences,
)
from core.guard import (
    get_notification_log,
    get_weekly_pattern_analysis,
)

router = APIRouter(prefix="/behavior", tags=["Behavior"])


# ═══════════════════════════════════════════════════════════════════════════
#  ENDPOINT 1 — Full Daily Report
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/today")
async def behavior_today(session_id: str):
    """
    Complete daily behavioral report.
    Combines activity, emotion, medicine, deviations, and all alerts.
    Used by caregiver dashboard 'Today' panel.

    Returns:
      - total interactions today
      - hourly activity breakdown
      - emotion timeline
      - medicine taken/missed
      - routine deviations detected
      - all alerts with severity
      - overall day risk: low | medium | high
      - one-line summary for caregiver
    """
    report = get_daily_report(session_id)
    return report


# ═══════════════════════════════════════════════════════════════════════════
#  ENDPOINT 2 — Full Weekly Report
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/weekly")
async def behavior_weekly(session_id: str):
    """
    Complete 7-day behavioral report.
    Used by caregiver dashboard 'Weekly Review' panel.

    Returns:
      - per-day emotional breakdown
      - weekly medicine adherence %
      - consecutive distress pattern check
      - weekly task activity
      - trend: improving | stable | declining
      - risk level + recommendation
    """
    report = get_weekly_report(session_id)
    return report


# ═══════════════════════════════════════════════════════════════════════════
#  ENDPOINT 3 — Medicine Log
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/medicine-log")
async def medicine_log(session_id: str):
    """
    Full medicine log — today's schedule + history.
    Used by the medicine adherence chart on the dashboard.

    Returns:
      - full schedule with taken/missed status
      - medicines due for refill
      - adherence percentage
      - alerts for missed or overdue medicines
      - last taken timestamps per medicine
    """
    m            = get_full_memory(session_id)
    schedule     = m.get("medicine_schedule", [])
    missed       = get_missed_medicines(session_id)
    due_refills  = get_medicines_due_refill(session_id)
    behavior     = get_medicine_behavior(session_id)

    missed_names  = {med["name"].lower() for med in missed}
    refill_names  = {med["name"].lower() for med in due_refills}

    enriched = []
    for med in schedule:
        name_lower = med["name"].lower()
        enriched.append({
            "name":          med["name"],
            "dose":          med.get("dose", ""),
            "scheduled_time": med.get("time", ""),
            "taken_today":   med.get("taken_today", False),
            "last_taken":    med.get("last_taken"),
            "refill_due":    med.get("refill_due"),
            "needs_refill":  name_lower in refill_names,
            "missed_today":  name_lower in missed_names,
            "status":        (
                "taken"   if med.get("taken_today") else
                "missed"  if name_lower in missed_names else
                "pending"
            ),
            "status_color":  (
                "success" if med.get("taken_today") else
                "danger"  if name_lower in missed_names else
                "warning"
            ),
        })

    taken_count   = sum(1 for m in enriched if m["status"] == "taken")
    missed_count  = sum(1 for m in enriched if m["status"] == "missed")
    pending_count = sum(1 for m in enriched if m["status"] == "pending")
    total         = len(enriched)
    adherence_pct = round((taken_count / total * 100) if total else 100, 1)

    return {
        "session_id":     session_id,
        "date":           datetime.now().strftime("%Y-%m-%d"),
        "schedule":       enriched,
        "summary": {
            "total":          total,
            "taken":          taken_count,
            "missed":         missed_count,
            "pending":        pending_count,
            "adherence_pct":  adherence_pct,
            "adherence_status": (
                "excellent" if adherence_pct >= 90 else
                "good"      if adherence_pct >= 70 else
                "poor"
            ),
        },
        "due_refills":    [med["name"] for med in due_refills],
        "alerts":         behavior.get("alerts", []),
        "generated_at":   datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  ENDPOINT 4 — Alert History
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/alert-history")
async def alert_history(
    session_id: str,
    days: int = Query(7, ge=1, le=30),
    severity: Optional[str] = Query(None)
):
    """
    All alerts triggered for this session.
    Combines caregiver notifications + behavior alerts + medicine alerts.
    Used by the alert timeline on the caregiver dashboard.

    Args:
      days:     how many days back to look (default 7)
      severity: filter by 'high' | 'medium' | 'low' (optional)
    """
    cutoff = (datetime.now().isoformat()[:10])  # today's date string
    notifications = get_notification_log(session_id)

    # caregiver alerts
    alerts = []
    for n in notifications:
        alert_severity = "high" if n.alert_type.value in ("crisis", "distress") else "medium"
        if severity and alert_severity != severity:
            continue
        alerts.append({
            "timestamp":  n.timestamp,
            "type":       "emotion_alert",
            "level":      n.alert_type.value,
            "severity":   alert_severity,
            "message":    n.message,
            "source":     "GUARD",
            "icon":       "🚨" if n.alert_type.value == "crisis" else "😢",
        })

    # medicine alerts from behavior tracker
    medicine_behavior = get_medicine_behavior(session_id)
    for med_alert in medicine_behavior.get("alerts", []):
        if severity and med_alert.get("severity") != severity:
            continue
        alerts.append({
            "timestamp":  datetime.now().isoformat(),
            "type":       med_alert["type"],
            "level":      med_alert["type"],
            "severity":   med_alert.get("severity", "medium"),
            "message":    med_alert["message"],
            "source":     "MedicineTracker",
            "icon":       "💊",
        })

    # routine deviations
    deviations = detect_routine_deviations(session_id)
    for dev in deviations:
        if severity and dev.get("severity") != severity:
            continue
        alerts.append({
            "timestamp":  datetime.now().isoformat(),
            "type":       dev["type"],
            "level":      dev["type"],
            "severity":   dev.get("severity", "medium"),
            "message":    dev["message"],
            "source":     "BehaviorTracker",
            "icon":       "⚠️",
        })

    # sort newest first
    alerts.sort(key=lambda x: x["timestamp"], reverse=True)

    high_count   = sum(1 for a in alerts if a["severity"] == "high")
    medium_count = sum(1 for a in alerts if a["severity"] == "medium")

    return {
        "session_id":   session_id,
        "total_alerts": len(alerts),
        "high_alerts":  high_count,
        "medium_alerts": medium_count,
        "alerts":       alerts,
        "generated_at": datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  ENDPOINT 5 — Activity Heatmap
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/activity-heatmap")
async def activity_heatmap(session_id: str):
    """
    Hourly interaction heatmap for today.
    Used by the D3.js activity chart on the caregiver dashboard.

    Returns 24 hourly buckets with interaction counts.
    Frontend renders as a colored heatmap (dark = active, light = quiet).
    """
    hourly        = get_hourly_activity(session_id)
    today_total   = sum(h["count"] for h in hourly)
    peak          = max(hourly, key=lambda h: h["count"]) if hourly else None
    active_hours  = [h for h in hourly if h["count"] > 0]

    # normalize counts for heatmap intensity (0.0 to 1.0)
    max_count = max((h["count"] for h in hourly), default=1)
    for h in hourly:
        h["intensity"] = round(h["count"] / max_count, 2) if max_count > 0 else 0.0
        h["color_class"] = (
            "high"   if h["intensity"] >= 0.7 else
            "medium" if h["intensity"] >= 0.3 else
            "low"    if h["intensity"] > 0    else
            "none"
        )

    return {
        "session_id":    session_id,
        "date":          datetime.now().strftime("%Y-%m-%d"),
        "hourly":        hourly,
        "total_today":   today_total,
        "active_hours":  len(active_hours),
        "peak_hour":     peak,
        "quiet_hours":   24 - len(active_hours),
        "generated_at":  datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  ENDPOINT 6 — Inactivity Check
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/inactivity-check")
async def inactivity_check(session_id: str):
    """
    Current inactivity status.
    Called by frontend every 5 minutes to check if user has gone quiet.
    If inactive → show warning on caregiver dashboard.
    """
    status = get_inactivity_status(session_id)
    alert  = check_inactivity(session_id)

    return {
        "session_id":         session_id,
        "status":             status,
        "inactivity_alert":   alert,
        "needs_attention":    alert is not None,
        "threshold_hours":    4,
        "checked_at":         datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  ENDPOINT 7 — Routine Deviations
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/deviations")
async def routine_deviations(session_id: str):
    """
    Today's routine deviation alerts.
    Returns list of detected deviations with severity and message.
    Used by the caregiver dashboard alert panel.
    """
    deviations = detect_routine_deviations(session_id)
    consec     = check_consecutive_distress_days(session_id)

    all_issues = list(deviations)
    if consec:
        all_issues.append(consec)

    high_count = sum(1 for d in all_issues if d.get("severity") == "high")

    return {
        "session_id":     session_id,
        "date":           datetime.now().strftime("%Y-%m-%d"),
        "deviations":     deviations,
        "consecutive_distress": consec,
        "total_issues":   len(all_issues),
        "high_severity":  high_count,
        "needs_attention": high_count > 0 or len(all_issues) >= 2,
        "generated_at":   datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  ENDPOINT 8 — Log Interaction (POST)
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/log-interaction")
async def log_interaction_endpoint(
    session_id:       str,
    interaction_type: str = "voice",
    detail:           str = ""
):
    """
    Manually log an interaction from the frontend.
    Called by app.js after every voice command, button press, or demo run.

    interaction_type: voice | camera | demo | task | button
    """
    log_interaction(session_id, interaction_type, detail)
    return {
        "logged":           True,
        "session_id":       session_id,
        "interaction_type": interaction_type,
        "timestamp":        datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  ENDPOINT 9 — Mark Medicine Taken (POST)
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/mark-medicine")
async def mark_medicine_endpoint(
    session_id:    str,
    medicine_name: str
):
    """
    Mark a medicine as taken.
    Called when user says 'I took my medicine' or taps the medicine button.
    Updates the medicine schedule in session memory.
    """
    mark_medicine_taken(session_id, medicine_name)

    # log as interaction
    log_interaction(session_id, "medicine", detail=f"Took {medicine_name}")

    return {
        "marked":        True,
        "medicine":      medicine_name,
        "session_id":    session_id,
        "timestamp":     datetime.now().isoformat(),
        "message":       f"{medicine_name} marked as taken.",
    }


# ═══════════════════════════════════════════════════════════════════════════
#  ENDPOINT 10 — Emotion History
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/emotion-history")
async def emotion_history(
    session_id: str,
    days: int = Query(7, ge=1, le=30)
):
    """
    Raw emotion history for the last N days.
    Used by D3.js emotional timeline chart on the dashboard.
    """
    history = get_emotional_history(session_id, days=days)
    weekly  = get_weekly_emotional_trend(session_id)
    pattern = get_weekly_pattern_analysis(session_id)

    return {
        "session_id":    session_id,
        "days":          days,
        "history":       history,
        "total_entries": len(history),
        "weekly_trend":  weekly,
        "pattern": {
            "risk_level":    pattern.get("risk_level", "low"),
            "risk_message":  pattern.get("risk_message", ""),
            "total_distress": pattern.get("total_distress", 0),
            "improving":     pattern.get("improving", False),
            "recommendation": pattern.get("recommendation", ""),
        },
        "generated_at":  datetime.now().isoformat(),
    }