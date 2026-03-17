"""
agents/skills/skill_registry.py
=================================
Central registry for ALL Nova Bridge skills.
Manages both built-in skills and custom user-defined skills.

What caregivers/users can define:
  - Custom skill name and description
  - Which website to open
  - What steps to follow
  - What fields to fill
  - Any special rules for THIS patient

Example custom skill a caregiver might add:
  {
    "name": "Book Kidney Specialist",
    "intent": "book_appointment",
    "url": "https://www.apollohospitals.com/nephrology",
    "steps": [
        "Click on Book Appointment",
        "Select Nephrology department",
        "Choose Dr. Ramesh Patel",
        "Pick earliest morning slot",
        "Enter patient name: Ramesh Kumar"
    ],
    "rules": [
        "Always book morning slots only (patient needs fasting)",
        "Never book on Fridays (dialysis day)",
        "Always select vegetarian meal option if asked"
    ],
    "patient_notes": "Patient has stage 3 CKD. Always mention this to doctor."
  }

Skills are saved per session — each patient has their own skill set.
Built-in skills are available to everyone as defaults.

Demo URLs point to localhost:3000 (run demo_sites/server.py first).
For real deployment, change URLs back to live sites.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any

# ── Storage path for custom skills ───────────────────────────────────────────
SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "skill_store")
os.makedirs(SKILLS_DIR, exist_ok=True)

# ── In-memory cache ───────────────────────────────────────────────────────────
_skill_cache: Dict[str, List[dict]] = {}   # session_id → [skills]

# ── Demo mode flag ────────────────────────────────────────────────────────────
# Set to True  → uses localhost:3000 demo sites (no login needed)
# Set to False → uses real live websites (login required)
DEMO_MODE = True

DEMO_BASE = "http://localhost:3000"

LIVE_URLS = {
    "doctor_booking":  "https://www.practo.com",
    "medicine_refill": "https://www.1mg.com",
    "bill_payment":    "https://www.paytm.com",
    "message_family":  "https://web.whatsapp.com",
    "taxi_booking":    "https://www.olacabs.com",
}

DEMO_URLS = {
    "doctor_booking":  f"{DEMO_BASE}/book",
    "medicine_refill": f"{DEMO_BASE}/pharmacy",
    "bill_payment":    f"{DEMO_BASE}/bill",
    "message_family":  "https://web.whatsapp.com",   # WhatsApp always real
    "taxi_booking":    f"{DEMO_BASE}/book",           # reuse booking demo
}

def _url(skill_id: str) -> str:
    """Returns correct URL based on DEMO_MODE flag."""
    if DEMO_MODE:
        return DEMO_URLS.get(skill_id, f"{DEMO_BASE}/book")
    return LIVE_URLS.get(skill_id, "https://www.practo.com")


# ═══════════════════════════════════════════════════════════════════════════
#  BUILT-IN SKILLS
#  Available to every patient by default.
#  Caregivers can override any of these with custom versions.
# ═══════════════════════════════════════════════════════════════════════════

BUILTIN_SKILLS: List[dict] = [
    {
        "id":          "doctor_booking",
        "name":        "Book Doctor Appointment",
        "intent":      "book_appointment",
        "is_builtin":  True,
        "url":         _url("doctor_booking"),   # localhost:3000/book in demo
        "description": "Books a doctor appointment — Apollo Hospital demo",
        "steps": [
            "Open booking website",
            "Select specialty from the grid",
            "Click on preferred doctor card",
            "Select date from date pills",
            "Select available time slot",
            "Enter patient name in the form",
            "Enter age and phone number",
            "Enter reason for visit",
            "Click Confirm Appointment button",
            "Extract confirmation ID from confirmation screen",
        ],
        "rules":           [],
        "patient_notes":   "",
        "fields":          {},
        "created_at":      "builtin",
    },
    {
        "id":          "medicine_refill",
        "name":        "Order Medicine Refill",
        "intent":      "order_medicine",
        "is_builtin":  True,
        "url":         _url("medicine_refill"),  # localhost:3000/pharmacy in demo
        "description": "Orders medicine — 1mg demo pharmacy",
        "steps": [
            "Open pharmacy website",
            "Type medicine name in the search bar",
            "Click Search button",
            "Click Add to Cart on the first matching product",
            "Verify cart shows the medicine",
            "Click Place Order button",
            "Extract order ID from confirmation screen",
        ],
        "rules":           [],
        "patient_notes":   "",
        "fields":          {},
        "created_at":      "builtin",
    },
    {
        "id":          "bill_payment",
        "name":        "Pay Utility Bill",
        "intent":      "pay_bill",
        "is_builtin":  True,
        "url":         _url("bill_payment"),     # localhost:3000/bill in demo
        "description": "Pays electricity bill — BESCOM demo portal",
        "steps": [
            "Open billing portal",
            "Enter RR number or consumer number in the input field",
            "Enter captcha value shown on screen",
            "Click Fetch Bill Details button",
            "Verify bill amount shown",
            "Select UPI as payment method",
            "Click Pay Securely Now button",
            "Extract transaction ID from receipt",
        ],
        "rules":           [],
        "patient_notes":   "",
        "fields":          {},
        "created_at":      "builtin",
    },
    {
        "id":          "message_family",
        "name":        "Send Message to Family",
        "intent":      "send_message",
        "is_builtin":  True,
        "url":         _url("message_family"),   # always WhatsApp Web
        "description": "Sends a WhatsApp message to caregiver or family",
        "steps": [
            "Open WhatsApp Web",
            "Wait for WhatsApp to load completely",
            "Find the contact in the chat list",
            "Click on the contact",
            "Type the message in the message box",
            "Click the send button",
        ],
        "rules":           [],
        "patient_notes":   "",
        "fields":          {},
        "created_at":      "builtin",
    },
    {
        "id":          "taxi_booking",
        "name":        "Book a Taxi",
        "intent":      "send_message",
        "is_builtin":  True,
        "url":         _url("taxi_booking"),
        "description": "Books an Ola or Uber taxi",
        "steps": [
            "Open taxi app",
            "Enter pickup location",
            "Enter destination",
            "Select cab type",
            "Confirm booking",
        ],
        "rules":           [],
        "patient_notes":   "",
        "fields":          {},
        "created_at":      "builtin",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
#  DISK PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════

def _skills_path(session_id: str) -> str:
    safe = session_id.replace("/", "_").replace("\\", "_")
    return os.path.join(SKILLS_DIR, f"{safe}_skills.json")


def _load_custom_skills(session_id: str) -> List[dict]:
    path = _skills_path(session_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"  [Skills] Failed to load {path}: {e}")
    return []


def _save_custom_skills(session_id: str, skills: List[dict]):
    path = _skills_path(session_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(skills, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"  [Skills] Failed to save {path}: {e}")


# ═══════════════════════════════════════════════════════════════════════════
#  SKILL REGISTRY — CORE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def get_all_skills(session_id: str) -> List[dict]:
    """
    Returns ALL skills for a session:
    built-in defaults + patient's custom skills.
    Custom skills with same intent override built-in ones.
    """
    custom = _get_custom_skills(session_id)
    custom_intents = {s["intent"] for s in custom if s.get("overrides_builtin")}

    result = []
    for skill in BUILTIN_SKILLS:
        if skill["intent"] not in custom_intents:
            result.append({**skill, "source": "builtin"})

    for skill in custom:
        result.append({**skill, "source": "custom"})

    return result


def _get_custom_skills(session_id: str) -> List[dict]:
    """Load custom skills from cache or disk."""
    if session_id not in _skill_cache:
        _skill_cache[session_id] = _load_custom_skills(session_id)
    return _skill_cache[session_id]


def get_skill_by_intent(session_id: str, intent: str) -> Optional[dict]:
    """
    Returns the best skill for a given intent.
    Custom skills take priority over built-ins.
    """
    all_skills = get_all_skills(session_id)
    custom_match = next(
        (s for s in all_skills if s["intent"] == intent and s.get("source") == "custom"),
        None
    )
    if custom_match:
        return custom_match
    return next(
        (s for s in all_skills if s["intent"] == intent and s.get("source") == "builtin"),
        None
    )


def get_skill_by_id(session_id: str, skill_id: str) -> Optional[dict]:
    """Returns a specific skill by its ID."""
    all_skills = get_all_skills(session_id)
    return next((s for s in all_skills if s.get("id") == skill_id), None)


# ═══════════════════════════════════════════════════════════════════════════
#  ADD / UPDATE / DELETE CUSTOM SKILLS
# ═══════════════════════════════════════════════════════════════════════════

def add_custom_skill(session_id: str, skill_data: dict) -> dict:
    """
    Add or update a custom skill for a patient.

    Required fields in skill_data:
      name        : "Book Kidney Specialist"
      intent      : "book_appointment" | "order_medicine" | "pay_bill" |
                    "send_message" | "fill_form" | "custom"
      url         : "https://..." or "http://localhost:3000/..."
      steps       : ["Step 1", "Step 2", ...]
    """
    custom = _get_custom_skills(session_id)

    required = ["name", "intent", "url", "steps"]
    missing  = [f for f in required if not skill_data.get(f)]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    skill_id = _generate_skill_id(skill_data["name"])

    existing_idx = next(
        (i for i, s in enumerate(custom) if s.get("id") == skill_id),
        None
    )

    new_skill = {
        "id":                skill_id,
        "name":              skill_data["name"],
        "intent":            skill_data["intent"],
        "is_builtin":        False,
        "url":               skill_data["url"],
        "description":       skill_data.get("description", skill_data["name"]),
        "steps":             skill_data["steps"],
        "rules":             skill_data.get("rules", []),
        "patient_notes":     skill_data.get("patient_notes", ""),
        "fields":            skill_data.get("fields", {}),
        "overrides_builtin": skill_data.get("overrides_builtin", False),
        "caregiver_name":    skill_data.get("caregiver_name", ""),
        "created_at":        datetime.now().isoformat(),
        "updated_at":        datetime.now().isoformat(),
    }

    if existing_idx is not None:
        new_skill["created_at"] = custom[existing_idx].get("created_at", new_skill["created_at"])
        custom[existing_idx] = new_skill
        action = "updated"
    else:
        custom.append(new_skill)
        action = "created"

    _skill_cache[session_id] = custom
    _save_custom_skills(session_id, custom)

    print(f"  [Skills] {action.title()}: '{new_skill['name']}' for session {session_id}")
    return {**new_skill, "action": action}


def update_skill_rules(session_id: str, skill_id: str, rules: List[str]) -> bool:
    """Update the rules for an existing skill."""
    custom = _get_custom_skills(session_id)
    for skill in custom:
        if skill.get("id") == skill_id:
            skill["rules"]      = rules
            skill["updated_at"] = datetime.now().isoformat()
            _skill_cache[session_id] = custom
            _save_custom_skills(session_id, custom)
            print(f"  [Skills] Rules updated for: {skill['name']}")
            return True
    return False


def update_patient_notes(session_id: str, skill_id: str, notes: str) -> bool:
    """Update patient medical notes for a skill."""
    custom = _get_custom_skills(session_id)
    for skill in custom:
        if skill.get("id") == skill_id:
            skill["patient_notes"] = notes
            skill["updated_at"]    = datetime.now().isoformat()
            _skill_cache[session_id] = custom
            _save_custom_skills(session_id, custom)
            return True
    return False


def delete_custom_skill(session_id: str, skill_id: str) -> bool:
    """Delete a custom skill. Built-in skills cannot be deleted."""
    custom = _get_custom_skills(session_id)
    before = len(custom)
    custom = [s for s in custom if s.get("id") != skill_id]
    if len(custom) < before:
        _skill_cache[session_id] = custom
        _save_custom_skills(session_id, custom)
        print(f"  [Skills] Deleted skill: {skill_id}")
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
#  SKILL EXECUTION HELPER
# ═══════════════════════════════════════════════════════════════════════════

def build_execution_instructions(skill: dict, parameters: dict = {}) -> dict:
    """
    Builds the full instruction set for ACT to execute.
    Merges skill steps + rules + patient notes + runtime parameters.
    """
    merged_fields = {**skill.get("fields", {}), **parameters}
    instructions  = []

    if skill.get("patient_notes"):
        instructions.append(f"[PATIENT CONTEXT] {skill['patient_notes']}")

    for rule in skill.get("rules", []):
        instructions.append(f"[RULE] {rule}")

    for field, value in merged_fields.items():
        if value and field not in ("clinic_url", "pharmacy_url", "portal_url", "url"):
            instructions.append(f"[AUTO-FILL] Set '{field}' to '{value}'")

    for i, step in enumerate(skill.get("steps", []), 1):
        instructions.append(f"Step {i}: {step}")

    return {
        "skill_id":      skill.get("id"),
        "skill_name":    skill.get("name"),
        "url":           skill.get("url", parameters.get("url", _url("doctor_booking"))),
        "instructions":  instructions,
        "steps":         skill.get("steps", []),
        "rules":         skill.get("rules", []),
        "patient_notes": skill.get("patient_notes", ""),
        "fields":        merged_fields,
        "is_custom":     not skill.get("is_builtin", False),
        "demo_mode":     DEMO_MODE,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _generate_skill_id(name: str) -> str:
    return name.lower().strip().replace(" ", "_").replace("/", "_")[:40]


def get_skills_summary(session_id: str) -> dict:
    """Returns a lightweight summary of all skills for the dashboard."""
    all_skills = get_all_skills(session_id)
    custom     = [s for s in all_skills if s.get("source") == "custom"]
    builtin    = [s for s in all_skills if s.get("source") == "builtin"]

    return {
        "total":          len(all_skills),
        "builtin_count":  len(builtin),
        "custom_count":   len(custom),
        "demo_mode":      DEMO_MODE,
        "demo_base_url":  DEMO_BASE if DEMO_MODE else "live websites",
        "custom_skills":  [
            {
                "id":         s["id"],
                "name":       s["name"],
                "intent":     s["intent"],
                "url":        s["url"],
                "has_rules":  len(s.get("rules", [])) > 0,
                "has_notes":  bool(s.get("patient_notes")),
                "created_at": s.get("created_at"),
            }
            for s in custom
        ],
        "available_intents": list({s["intent"] for s in all_skills}),
    }