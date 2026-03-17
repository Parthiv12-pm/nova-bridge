"""
agents/skills/skill_routes.py
================================
API endpoints for managing patient skills.
Caregivers use these to add custom skills for specific patients.

Endpoints:
  GET  /skills/list              — all skills for a patient
  POST /skills/add               — add a custom skill
  PUT  /skills/{skill_id}/rules  — update skill rules
  PUT  /skills/{skill_id}/notes  — update patient medical notes
  DELETE /skills/{skill_id}      — delete a custom skill
  GET  /skills/summary           — quick summary for dashboard
  GET  /skills/templates         — ready-made templates to start from
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
from agents.skills.skill_registry import (
    get_all_skills,
    get_skill_by_id,
    add_custom_skill,
    update_skill_rules,
    update_patient_notes,
    delete_custom_skill,
    get_skills_summary,
    BUILTIN_SKILLS,
)

router = APIRouter(prefix="/skills", tags=["Skills"])


# ── Request models ────────────────────────────────────────────────────────────

class AddSkillRequest(BaseModel):
    session_id:       str
    name:             str
    intent:           str           # book_appointment | order_medicine | pay_bill | send_message | fill_form | custom
    url:              str
    steps:            List[str]
    description:      Optional[str] = ""
    rules:            Optional[List[str]] = []
    patient_notes:    Optional[str] = ""
    fields:           Optional[Dict[str, str]] = {}
    overrides_builtin: Optional[bool] = False
    caregiver_name:   Optional[str] = ""


class UpdateRulesRequest(BaseModel):
    session_id: str
    rules:      List[str]


class UpdateNotesRequest(BaseModel):
    session_id:    str
    patient_notes: str


# ═══════════════════════════════════════════════════════════════════════════
#  GET — List All Skills
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/list")
async def list_skills(session_id: str):
    """
    Returns all skills for a patient:
    built-in defaults + any custom skills the caregiver has added.

    Custom skills show:
      - What website to open
      - What steps to follow
      - Patient-specific rules
      - Medical notes for the AI
    """
    skills = get_all_skills(session_id)
    return {
        "session_id": session_id,
        "total":      len(skills),
        "skills":     skills,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  POST — Add Custom Skill
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/add")
async def add_skill(request: AddSkillRequest):
    """
    Add a custom skill for a specific patient.
    Caregivers define the website, steps, rules, and patient notes.

    Example — caregiver adds a kidney specialist booking skill:
    {
      "session_id": "patient_001",
      "name": "Book Kidney Specialist",
      "intent": "book_appointment",
      "url": "https://www.apollohospitals.com/nephrology",
      "steps": [
        "Click Book Appointment",
        "Select Nephrology",
        "Choose Dr. Ramesh Patel",
        "Pick morning slot only"
      ],
      "rules": [
        "Always book morning slots (patient needs fasting tests)",
        "Never book on Fridays — dialysis day",
        "Always mention Stage 3 CKD to the receptionist"
      ],
      "patient_notes": "Patient Ramesh Kumar, 68 years, Stage 3 CKD, diabetic.",
      "fields": {
        "patient_name": "Ramesh Kumar",
        "age": "68",
        "condition": "Stage 3 CKD"
      }
    }
    """
    try:
        result = add_custom_skill(request.session_id, request.dict())
        return {
            "success":    True,
            "skill":      result,
            "message":    f"Skill '{request.name}' {result['action']} successfully.",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
#  PUT — Update Skill Rules
# ═══════════════════════════════════════════════════════════════════════════

@router.put("/{skill_id}/rules")
async def update_rules(skill_id: str, request: UpdateRulesRequest):
    """
    Update the rules for a patient's skill.
    Rules are special instructions the AI must follow for THIS patient.

    Examples of rules caregivers set:
      "Always book morning slots only — patient has afternoon dialysis"
      "Never order brand X medicine — patient had reaction"
      "Always confirm with patient before paying — dementia patient"
      "Send confirmation message to daughter (+91-9876543210) after booking"
    """
    success = update_skill_rules(request.session_id, skill_id, request.rules)
    if not success:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return {
        "success":    True,
        "skill_id":   skill_id,
        "rules":      request.rules,
        "message":    f"{len(request.rules)} rules saved for skill.",
    }


# ═══════════════════════════════════════════════════════════════════════════
#  PUT — Update Patient Medical Notes
# ═══════════════════════════════════════════════════════════════════════════

@router.put("/{skill_id}/notes")
async def update_notes(skill_id: str, request: UpdateNotesRequest):
    """
    Update patient medical notes for a skill.
    These notes are injected into every AI prompt for this skill
    so Nova always knows the patient's medical context.

    Examples:
      "Patient has Type 2 diabetes. Avoid medicines with sugar coating."
      "Patient is 78 years old with hearing loss. Speak slowly."
      "Patient has penicillin allergy. Never order penicillin-based medicines."
      "Patient speaks only Gujarati. Use Gujarati language."
    """
    success = update_patient_notes(request.session_id, skill_id, request.patient_notes)
    if not success:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return {
        "success":       True,
        "skill_id":      skill_id,
        "patient_notes": request.patient_notes,
        "message":       "Patient notes updated. AI will use these for every interaction.",
    }


# ═══════════════════════════════════════════════════════════════════════════
#  DELETE — Remove Custom Skill
# ═══════════════════════════════════════════════════════════════════════════

@router.delete("/{skill_id}")
async def delete_skill(skill_id: str, session_id: str):
    """
    Delete a custom skill.
    Note: Built-in skills cannot be deleted, only overridden.
    """
    success = delete_custom_skill(session_id, skill_id)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Custom skill '{skill_id}' not found. Built-in skills cannot be deleted."
        )
    return {
        "success":  True,
        "skill_id": skill_id,
        "message":  "Custom skill deleted. Built-in default will be used instead.",
    }


# ═══════════════════════════════════════════════════════════════════════════
#  GET — Skills Summary (for dashboard)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/summary")
async def skills_summary(session_id: str):
    """
    Lightweight skills summary for the dashboard.
    Shows how many custom skills a patient has and what they cover.
    """
    return get_skills_summary(session_id)


# ═══════════════════════════════════════════════════════════════════════════
#  GET — Skill Templates
#  Ready-made templates caregivers can copy and customize
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/templates")
async def skill_templates():
    """
    Ready-made skill templates for common patient scenarios.
    Caregivers pick a template, fill in patient details, and save.

    Templates cover:
      - Specialist doctor booking (cardiology, nephrology, oncology etc.)
      - Chronic disease medicine refill
      - Government hospital booking
      - Diagnostic lab test booking
      - Ambulance / emergency services
    """
    templates = [
        {
            "template_id":  "specialist_booking",
            "name":         "Book Specialist Doctor",
            "intent":       "book_appointment",
            "url":          "https://www.practo.com",
            "description":  "For patients who see a specialist regularly",
            "steps": [
                "Open specialist booking page",
                "Select [SPECIALTY] department",
                "Choose [DOCTOR_NAME] if available",
                "Select morning slot preferred",
                "Enter patient details",
                "Confirm appointment"
            ],
            "rules": [
                "Always prefer morning appointments",
                "If preferred doctor unavailable, ask patient before booking another"
            ],
            "patient_notes": "Fill in: patient name, age, condition, doctor preference",
            "fields": {
                "patient_name": "[FILL IN]",
                "specialty":    "[FILL IN e.g. Cardiology]",
                "doctor":       "[FILL IN or leave blank]",
            },
        },
        {
            "template_id":  "chronic_medicine",
            "name":         "Refill Chronic Disease Medicine",
            "intent":       "order_medicine",
            "url":          "https://www.1mg.com",
            "description":  "For patients on regular long-term medicines",
            "steps": [
                "Open pharmacy website",
                "Search for [MEDICINE_NAME]",
                "Select exact brand if specified",
                "Add [QUANTITY] units to cart",
                "Apply any saved coupon",
                "Checkout to saved address"
            ],
            "rules": [
                "Always order the exact brand — do not substitute",
                "Order 30-day supply minimum",
                "If out of stock, check Netmeds or PharmEasy"
            ],
            "patient_notes": "Fill in: medicine name, brand, dosage, monthly quantity",
            "fields": {
                "medication_name": "[FILL IN]",
                "brand":           "[FILL IN or generic]",
                "quantity":        "[FILL IN e.g. 30 tablets]",
            },
        },
        {
            "template_id":  "government_hospital",
            "name":         "Book Government Hospital Appointment",
            "intent":       "book_appointment",
            "url":          "https://www.nhp.gov.in",
            "description":  "For patients using government hospitals (cheaper)",
            "steps": [
                "Open government hospital portal",
                "Enter Aadhaar number for verification",
                "Select hospital and department",
                "Choose available OPD slot",
                "Confirm with patient"
            ],
            "rules": [
                "Use Aadhaar for verification",
                "OPD slots available Monday to Saturday only",
                "Arrive 30 minutes before appointment time"
            ],
            "patient_notes": "Fill in: Aadhaar number, hospital preference, department",
            "fields": {
                "aadhaar":    "[FILL IN]",
                "hospital":   "[FILL IN]",
                "department": "[FILL IN]",
            },
        },
        {
            "template_id":  "lab_test",
            "name":         "Book Diagnostic Lab Test",
            "intent":       "book_appointment",
            "url":          "https://www.thyrocare.com",
            "description":  "For patients needing regular blood tests or scans",
            "steps": [
                "Open lab booking website",
                "Search for required test",
                "Select home collection if available",
                "Enter address for home visit",
                "Select morning slot (fasting tests)",
                "Confirm booking"
            ],
            "rules": [
                "Always prefer home collection — patient has mobility issues",
                "Book fasting tests for 7am-8am slot",
                "Send report to caregiver email automatically"
            ],
            "patient_notes": "Fill in: test names, fasting requirements, home address",
            "fields": {
                "test_name":   "[FILL IN e.g. HbA1c, Kidney Function Test]",
                "collection":  "home",
                "address":     "[FILL IN]",
            },
        },
        {
            "template_id":  "mental_health",
            "name":         "Book Mental Health Consultation",
            "intent":       "book_appointment",
            "url":          "https://www.practo.com/counselling-therapy",
            "description":  "For patients needing counselling or psychiatry",
            "steps": [
                "Open mental health booking",
                "Select online consultation preferred",
                "Choose therapist or psychiatrist",
                "Select private evening slot",
                "Confirm and send invite to patient"
            ],
            "rules": [
                "Always book private online sessions — patient prefers privacy",
                "Evening slots preferred (4pm-7pm)",
                "Do not mention appointment to others — confidential"
            ],
            "patient_notes": "Fill in: patient condition, therapist preference, session type",
            "fields": {
                "session_type": "online",
                "specialty":    "Psychiatry or Counselling",
            },
        },
    ]

    return {
        "total":     len(templates),
        "templates": templates,
        "tip":       "Copy any template, fill in the [FILL IN] fields, and POST to /skills/add",
    }