# agents/skills/__init__.py
from agents.skills.skill_registry import (
    get_all_skills,
    get_skill_by_intent,
    get_skill_by_id,
    add_custom_skill,
    update_skill_rules,
    update_patient_notes,
    delete_custom_skill,
    build_execution_instructions,
    get_skills_summary,
)
from agents.skills.skill_routes import router as skills_router