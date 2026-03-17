"""
models/schemas.py — Upgraded
==============================
All data structures for Nova Bridge.
Changes from original:
  - GuardAlert       → added emotion_score, behavior_analysis
  - ActResult        → added agent_console, safety_check, engine_used
  - SessionMemory    → expanded with preferences, medicine, emotions
  - DashboardStats   → expanded with INR cost, weekly score, medicine fields
  - New: MedicineEntry, EmotionEntry, TaskEntry, BehaviorReport,
         TrustCheck, AgentConsolePlan, ProactiveSuggestion,
         WeeklyHealthScore, ActivityEvent, SkillType
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


# ═══════════════════════════════════════════════════════════════════════════
#  ENUMS
# ═══════════════════════════════════════════════════════════════════════════

class IntentType(str, Enum):
    BOOK_APPOINTMENT = "book_appointment"
    FILL_FORM        = "fill_form"
    ORDER_MEDICINE   = "order_medicine"
    SEND_MESSAGE     = "send_message"
    PAY_BILL         = "pay_bill"
    UNKNOWN          = "unknown"


class EmotionState(str, Enum):
    CALM     = "calm"
    ANXIOUS  = "anxious"
    DISTRESS = "distress"
    CRISIS   = "crisis"


class UrgencyLevel(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class RiskLevel(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class EngineType(str, Enum):
    NOVA_ACT        = "Nova Act"
    PLAYWRIGHT_GROQ = "Playwright + Groq (free fallback)"
    DEMO            = "Demo simulation"


class SkillType(str, Enum):
    """All automation skills Nova Bridge can execute."""
    DOCTOR_BOOKING  = "doctor_booking"
    MEDICINE_REFILL = "medicine_refill"
    BILL_PAYMENT    = "bill_payment"
    TAXI_BOOKING    = "taxi_booking"
    MESSAGE_FAMILY  = "message_family"
    FILL_FORM       = "fill_form"


class AdherenceStatus(str, Enum):
    EXCELLENT = "excellent"
    GOOD      = "good"
    POOR      = "poor"


class TrendDirection(str, Enum):
    IMPROVING = "improving"
    STABLE    = "stable"
    DECLINING = "declining"


# ═══════════════════════════════════════════════════════════════════════════
#  AIRE — Intent Reconstruction
# ═══════════════════════════════════════════════════════════════════════════

class FragmentInput(BaseModel):
    raw_text:   str
    session_id: str
    language:   Optional[str] = "en"


class ReconstructedIntent(BaseModel):
    intent_type: IntentType
    confidence:  float
    entities:    dict
    action_plan: List[str]
    urgency:     UrgencyLevel
    raw_input:   str


# ═══════════════════════════════════════════════════════════════════════════
#  VISTA — Vision
# ═══════════════════════════════════════════════════════════════════════════

class VisionInput(BaseModel):
    session_id:    str
    image_base64:  str
    analysis_type: str = "full"   # "pill" | "document" | "face" | "full"


class VisionResult(BaseModel):
    detected_text:            Optional[str] = None
    medication_name:          Optional[str] = None
    drug_interaction_warning: Optional[str] = None
    emotion_detected:         Optional[EmotionState] = None
    confidence:               float = 0.0


# ═══════════════════════════════════════════════════════════════════════════
#  GUARD — Emotion Analysis (upgraded)
# ═══════════════════════════════════════════════════════════════════════════

class EmotionInput(BaseModel):
    session_id:       str
    voice_tone_score: Optional[float] = None    # 0.0 calm → 1.0 distress
    facial_emotion:   Optional[EmotionState] = None
    text_signals:     Optional[str] = None


class GuardAlert(BaseModel):
    session_id:     str
    alert_level:    EmotionState
    trigger_reason: str
    action_taken:   str                          # "none" | "grounding_response" | "caregiver_notified" | "emergency_call"

    # NEW — required by upgraded guard.py
    emotion_score:     float = 0.0              # 0.0 (calm) → 1.0 (crisis)
    behavior_analysis: Optional[Dict[str, Any]] = None  # weekly pattern data


# ═══════════════════════════════════════════════════════════════════════════
#  TRUST & SAFETY LAYER — NEW
# ═══════════════════════════════════════════════════════════════════════════

class TrustCheck(BaseModel):
    """Result of safety verification before any ACT execution."""
    verified_website:   bool
    secure_connection:  bool
    risk_level:         RiskLevel
    approved:           bool
    domain:             str
    action:             str


# ═══════════════════════════════════════════════════════════════════════════
#  AGENT CONSOLE — NEW
#  Step-by-step agent plan shown in the frontend panel
# ═══════════════════════════════════════════════════════════════════════════

class AgentConsolePlan(BaseModel):
    """What the AI is planning to do — shown in the Agent Console panel."""
    intent:     str
    steps:      List[str]
    engine:     str = "Nova Act"
    started_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ═══════════════════════════════════════════════════════════════════════════
#  ACT — Task Execution (upgraded)
# ═══════════════════════════════════════════════════════════════════════════

class ActTask(BaseModel):
    session_id: str
    task_type:  IntentType
    parameters: dict


class ActResult(BaseModel):
    success:           bool
    task_completed:    str
    confirmation_text: Optional[str] = None
    screenshot_base64: Optional[str] = None
    error:             Optional[str] = None

    # NEW — required by upgraded act.py
    agent_console: Optional[Dict[str, Any]] = None   # AgentConsolePlan as dict
    safety_check:  Optional[Dict[str, Any]] = None   # TrustCheck as dict
    engine_used:   Optional[str] = None              # which engine ran this task


# ═══════════════════════════════════════════════════════════════════════════
#  MEDICINE — NEW
# ═══════════════════════════════════════════════════════════════════════════

class MedicineEntry(BaseModel):
    """One medicine in the user's schedule."""
    name:        str
    dose:        str
    time:        str                          # "08:00"
    taken_today: bool = False
    last_taken:  Optional[str] = None        # ISO timestamp
    refill_due:  Optional[str] = None        # "YYYY-MM-DD"
    added_at:    Optional[str] = None

    # computed fields (populated by medicine_adherence endpoint)
    status:      Optional[str] = None        # "taken" | "missed" | "pending"
    status_icon: Optional[str] = None
    needs_refill: bool = False


class MedicineAdherenceReport(BaseModel):
    """Today's medicine adherence summary."""
    session_id:       str
    date:             str
    schedule:         List[MedicineEntry] = []
    total:            int = 0
    taken:            int = 0
    missed:           int = 0
    pending:          int = 0
    adherence_pct:    float = 100.0
    due_refills:      List[MedicineEntry] = []
    refill_count:     int = 0
    adherence_status: AdherenceStatus = AdherenceStatus.EXCELLENT


# ═══════════════════════════════════════════════════════════════════════════
#  EMOTION HISTORY — NEW
# ═══════════════════════════════════════════════════════════════════════════

class EmotionEntry(BaseModel):
    """One logged emotional state."""
    timestamp: str
    emotion:   EmotionState
    score:     float = 0.0
    trigger:   Optional[str] = None


class DayEmotionalSummary(BaseModel):
    """Emotional summary for one day — used by weekly trend chart."""
    date:            str
    day_label:       str             # "Mon", "Tue" etc.
    dominant:        EmotionState
    total_entries:   int = 0
    distress_count:  int = 0
    calm_count:      int = 0
    anxious_count:   int = 0


# ═══════════════════════════════════════════════════════════════════════════
#  TASK HISTORY — NEW
# ═══════════════════════════════════════════════════════════════════════════

class TaskEntry(BaseModel):
    """One completed task in history."""
    timestamp: str
    intent:    str
    summary:   str
    success:   bool = True


# ═══════════════════════════════════════════════════════════════════════════
#  ACTIVITY TIMELINE EVENT — NEW
# ═══════════════════════════════════════════════════════════════════════════

class ActivityEvent(BaseModel):
    """One event in the daily activity timeline."""
    timestamp:  str
    hour_label: str
    type:       str       # "task" | "emotion" | "medicine" | "medicine_missed" | "alert"
    icon:       str
    label:      str
    detail:     Optional[str] = None
    severity:   str = "info"   # "success" | "warning" | "danger" | "info"
    score:      Optional[float] = None


# ═══════════════════════════════════════════════════════════════════════════
#  WEEKLY HEALTH SCORE — NEW
# ═══════════════════════════════════════════════════════════════════════════

class ScoreBreakdown(BaseModel):
    score: int
    max:   int


class WeeklyHealthScore(BaseModel):
    session_id:   str
    week_of:      str
    total_score:  int
    max_score:    int = 100
    grade:        str
    trend:        TrendDirection
    breakdown: Dict[str, ScoreBreakdown] = {}
    daily_scores: List[Dict[str, Any]] = []
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ═══════════════════════════════════════════════════════════════════════════
#  BEHAVIOR REPORT — NEW
# ═══════════════════════════════════════════════════════════════════════════

class BehaviorReport(BaseModel):
    """Full weekly behavioral analysis for caregiver review."""
    session_id:    str
    report_period: Dict[str, str] = {}
    today:         Dict[str, Any] = {}
    weekly_pattern: Dict[str, Any] = {}
    daily_breakdown: List[Dict[str, Any]] = []
    medicine:      Dict[str, Any] = {}
    tasks:         Dict[str, Any] = {}
    alerts:        Dict[str, Any] = {}
    flags:         Dict[str, bool] = {}
    recommendation: str = ""
    generated_at:  str = Field(default_factory=lambda: datetime.now().isoformat())


# ═══════════════════════════════════════════════════════════════════════════
#  PROACTIVE SUGGESTION — NEW
# ═══════════════════════════════════════════════════════════════════════════

class ProactiveSuggestion(BaseModel):
    """Nova's unprompted suggestion to the user."""
    session_id:     str
    suggestion:     Optional[str] = None
    has_suggestion: bool = False
    emotion:        str = "calm"
    checked_at:     str = Field(default_factory=lambda: datetime.now().isoformat())


# ═══════════════════════════════════════════════════════════════════════════
#  SESSION MEMORY (upgraded)
# ═══════════════════════════════════════════════════════════════════════════

class SessionMemory(BaseModel):
    """
    Backward-compatible session memory schema.
    The full memory dict lives in session_memory.py (_get / _save).
    This schema is used for the simplified API surface.
    """
    session_id:      str
    last_clinic:     Optional[str] = None
    last_doctor:     Optional[str] = None
    last_medication: Optional[str] = None
    last_intent:     Optional[IntentType] = None
    user_name:       Optional[str] = None

    # NEW preference fields (populated from full memory)
    preferred_hospital: Optional[str] = None
    preferred_pharmacy: Optional[str] = None
    preferred_doctor:   Optional[str] = None
    preferred_language: str = "en"
    caregiver_name:     Optional[str] = None
    caregiver_phone:    Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
#  DASHBOARD STATS (upgraded)
# ═══════════════════════════════════════════════════════════════════════════

class DashboardStats(BaseModel):
    # original fields — kept exactly the same for backward compat
    users_helped_today:    int   = 0
    tasks_completed:       int   = 0
    hours_saved:           float = 0.0
    caregiver_costs_saved: float = 0.0
    active_sessions:       int   = 0
    alerts_triggered:      int   = 0

    # NEW fields
    cost_saved_inr:        float = 0.0    # Indian rupees (hours × 6640)
    weekly_score:          int   = 0      # composite health score 0-100
    missed_medicines_today: int  = 0
    distress_count_today:  int   = 0


# ═══════════════════════════════════════════════════════════════════════════
#  CAREGIVER NOTIFICATION
# ═══════════════════════════════════════════════════════════════════════════

class CaregiverNotification(BaseModel):
    session_id:  str
    user_name:   Optional[str] = None
    alert_type:  EmotionState
    message:     str
    timestamp:   str

    # NEW
    is_pattern_alert: bool = False      # True = triggered by 3+ distress threshold
    distress_count:   int  = 0          # how many today when this fired