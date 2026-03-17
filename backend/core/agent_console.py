"""
core/agent_console.py — NEW FILE
==================================
The Agent Console — shows judges and users exactly how Nova
plans its actions before executing them.

Frontend panel shows:
  Intent: Book Doctor Appointment
  Engine: Nova Act

  Agent Plan
  ✓ Identify clinic website
  ✓ Find booking section
  ⟳ Select doctor and date    ← currently running
  ○ Enter patient details
  ○ Confirm appointment

Called by:
  - agents/act.py        (creates console per task)
  - api/main.py          (attaches console to pipeline response)
  - api/dashboard_routes (serves console history)
"""

import json
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from models.schemas import (
    AgentConsolePlan, IntentType, ActTask
)

# ── Storage — keeps last N console logs in memory ───────────────────────────
_console_history: Dict[str, List[dict]] = {}   # session_id → list of plans
MAX_HISTORY_PER_SESSION = 20


# ═══════════════════════════════════════════════════════════════════════════
#  AGENT CONSOLE CLASS
#  Used directly inside act.py for live step tracking
# ═══════════════════════════════════════════════════════════════════════════

class AgentConsole:
    """
    Tracks and displays agent planning steps.
    Each task gets its own AgentConsole instance.

    Usage in act.py:
        console = AgentConsole(session_id="u1", intent="book_appointment")
        console.plan(["Open clinic", "Find booking", "Select date", "Confirm"])
        console.log("Opened clinic website")     # marks step 1 done
        console.log("Found booking section")     # marks step 2 done
        result.agent_console = console.to_dict()
    """

    def __init__(self, session_id: str, intent: str):
        self.session_id   = session_id
        self.intent       = intent
        self.planned      = []      # original plan steps (○ pending)
        self.completed    = []      # steps actually done (✓ done)
        self.current      = None    # step currently running (⟳)
        self.started_at   = datetime.now().isoformat()
        self.finished_at  = None
        self.engine       = "Nova Act"
        self.success      = None

    def plan(self, steps: List[str]) -> "AgentConsole":
        """Set the plan before execution starts."""
        self.planned = [str(s) for s in steps]
        return self

    def log(self, step: str):
        """Mark a step as completed. Auto-advances the current step."""
        self.completed.append(step)
        # set current to next pending step
        done_count = len(self.completed)
        if done_count < len(self.planned):
            self.current = self.planned[done_count]
        else:
            self.current = None
        print(f"  [AgentConsole] ✓ {step}")

    def set_engine(self, engine: str):
        self.engine = engine
        return self

    def finish(self, success: bool = True):
        self.finished_at = datetime.now().isoformat()
        self.success     = success
        self.current     = None
        # save to history
        _save_to_history(self.session_id, self.to_dict())

    def to_dict(self) -> dict:
        """
        Returns the full console state as a dict.
        This is what gets sent to the frontend and stored in ActResult.
        """
        # build rich step list with status icons
        steps_with_status = []
        done_count = len(self.completed)

        for i, planned_step in enumerate(self.planned):
            if i < done_count:
                # find matching completed step if available
                label = self.completed[i] if i < len(self.completed) else planned_step
                steps_with_status.append({
                    "index":  i + 1,
                    "label":  label,
                    "status": "done",
                    "icon":   "✓"
                })
            elif planned_step == self.current:
                steps_with_status.append({
                    "index":  i + 1,
                    "label":  planned_step,
                    "status": "running",
                    "icon":   "⟳"
                })
            else:
                steps_with_status.append({
                    "index":  i + 1,
                    "label":  planned_step,
                    "status": "pending",
                    "icon":   "○"
                })

        duration_ms = None
        if self.finished_at:
            try:
                start = datetime.fromisoformat(self.started_at)
                end   = datetime.fromisoformat(self.finished_at)
                duration_ms = int((end - start).total_seconds() * 1000)
            except:
                pass

        return {
            "session_id":    self.session_id,
            "intent":        self.intent,
            "intent_label":  _intent_label(self.intent),
            "engine":        self.engine,
            "steps":         steps_with_status,
            "completed":     self.completed,
            "current_step":  self.current,
            "started_at":    self.started_at,
            "finished_at":   self.finished_at,
            "duration_ms":   duration_ms,
            "success":       self.success,
            "total_steps":   len(self.planned),
            "done_steps":    len(self.completed),
        }


# ═══════════════════════════════════════════════════════════════════════════
#  PLAN GENERATOR
#  Pre-built plans for each skill — shown BEFORE execution starts
#  Judges see the full plan appear instantly, then steps tick off live
# ═══════════════════════════════════════════════════════════════════════════

SKILL_PLANS: Dict[str, List[str]] = {

    "book_appointment": [
        "Identify clinic website",
        "Run safety & trust check",
        "Open booking portal",
        "Search for available doctors",
        "Select preferred date and slot",
        "Enter patient details",
        "Handle consent dialogs",
        "Confirm appointment",
        "Extract confirmation number",
    ],

    "order_medicine": [
        "Identify preferred pharmacy",
        "Run safety & trust check",
        "Open pharmacy website",
        "Search for medication",
        "Select correct product",
        "Set quantity",
        "Add to cart",
        "Proceed to checkout",
        "Confirm order",
    ],

    "pay_bill": [
        "Identify billing portal",
        "Run safety & trust check",
        "Open billing website",
        "Enter bill reference number",
        "Retrieve bill details",
        "Verify amount",
        "Proceed to payment",
        "Confirm payment",
        "Extract receipt number",
    ],

    "send_message": [
        "Identify messaging platform",
        "Open platform",
        "Compose message for caregiver",
        "Send message",
        "Confirm delivery",
    ],

    "fill_form": [
        "Identify government portal",
        "Run safety & trust check",
        "Open form page",
        "Locate all form fields",
        "Fill each field accurately",
        "Review filled form",
        "Submit form",
        "Extract reference number",
    ],

    "taxi_booking": [
        "Open taxi booking app",
        "Enter pickup location",
        "Enter destination",
        "Select vehicle type",
        "Confirm booking",
        "Share ETA with caregiver",
    ],

    "unknown": [
        "Understand user request",
        "Identify best action",
        "Execute task",
        "Confirm completion",
    ],
}


def get_plan_for_intent(intent: str, custom_steps: List[str] = None) -> List[str]:
    """
    Returns the step plan for a given intent.
    Falls back to custom_steps if provided, else uses SKILL_PLANS default.
    """
    if custom_steps:
        return custom_steps
    return SKILL_PLANS.get(intent, SKILL_PLANS["unknown"])


def create_console(session_id: str, intent: str, engine: str = "Nova Act") -> AgentConsole:
    """
    Factory function — creates a ready-to-use AgentConsole
    with the pre-built plan for the given intent.

    Usage:
        console = create_console("u1", "book_appointment", engine="Nova Act")
        # console already has the full plan loaded
        console.log("Opened clinic website")
    """
    console = AgentConsole(session_id=session_id, intent=intent)
    console.set_engine(engine)
    console.plan(get_plan_for_intent(intent))
    print(f"\n  [AgentConsole] Started: {_intent_label(intent)} via {engine}")
    print(f"  [AgentConsole] Plan: {len(console.planned)} steps")
    return console


# ═══════════════════════════════════════════════════════════════════════════
#  CONSOLE HISTORY — for dashboard and replay
# ═══════════════════════════════════════════════════════════════════════════

def _save_to_history(session_id: str, plan_dict: dict):
    """Save completed console to in-memory history."""
    if session_id not in _console_history:
        _console_history[session_id] = []
    _console_history[session_id].append(plan_dict)
    # keep only last N
    _console_history[session_id] = _console_history[session_id][-MAX_HISTORY_PER_SESSION:]


def get_console_history(session_id: str, limit: int = 10) -> List[dict]:
    """
    Returns last N agent console logs for a session.
    Used by dashboard to show recent AI actions.
    """
    history = _console_history.get(session_id, [])
    return list(reversed(history[-limit:]))


def get_last_console(session_id: str) -> Optional[dict]:
    """Returns the most recent agent console for a session."""
    history = _console_history.get(session_id, [])
    return history[-1] if history else None


# ═══════════════════════════════════════════════════════════════════════════
#  FRONTEND FORMATTER
#  Converts console dict to the exact format app.js expects
# ═══════════════════════════════════════════════════════════════════════════

def format_for_frontend(console_dict: dict) -> dict:
    """
    Formats the console dict for the frontend Agent Console panel.
    Returns a clean structure app.js can render directly.

    Frontend renders:
      <div class="agent-console">
        <div class="intent-label">Book Doctor Appointment</div>
        <div class="engine-badge">Nova Act</div>
        <div class="steps">
          <div class="step done">✓ Opened clinic website</div>
          <div class="step running">⟳ Selecting date</div>
          <div class="step pending">○ Entering patient details</div>
        </div>
        <div class="progress">3 / 9 steps</div>
      </div>
    """
    if not console_dict:
        return {"visible": False}

    steps = console_dict.get("steps", [])
    total = console_dict.get("total_steps", len(steps))
    done  = console_dict.get("done_steps", 0)

    return {
        "visible":       True,
        "intent_label":  console_dict.get("intent_label", console_dict.get("intent", "")),
        "engine":        console_dict.get("engine", "Nova Act"),
        "engine_color":  _engine_color(console_dict.get("engine", "")),
        "steps":         steps,
        "progress_text": f"{done} / {total} steps",
        "progress_pct":  round((done / total * 100) if total else 0),
        "is_running":    console_dict.get("finished_at") is None,
        "is_done":       console_dict.get("finished_at") is not None,
        "success":       console_dict.get("success"),
        "duration_ms":   console_dict.get("duration_ms"),
        "duration_text": _format_duration(console_dict.get("duration_ms")),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _intent_label(intent: str) -> str:
    """Converts intent key to readable label."""
    labels = {
        "book_appointment": "Book Doctor Appointment",
        "order_medicine":   "Order Medicine",
        "pay_bill":         "Pay Bill",
        "send_message":     "Send Message to Caregiver",
        "fill_form":        "Fill Government Form",
        "taxi_booking":     "Book Taxi",
        "unknown":          "Process Request",
    }
    return labels.get(intent, intent.replace("_", " ").title())


def _engine_color(engine: str) -> str:
    """Returns CSS color class for the engine badge."""
    if "Nova Act" in engine:
        return "info"       # blue — primary engine
    if "Playwright" in engine or "Groq" in engine:
        return "warning"    # amber — free fallback
    if "Demo" in engine:
        return "secondary"  # gray — demo mode
    return "info"


def _format_duration(ms: Optional[int]) -> str:
    """Converts milliseconds to readable string."""
    if ms is None:
        return ""
    if ms < 1000:
        return f"{ms}ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs    = int(seconds % 60)
    return f"{minutes}m {secs}s"