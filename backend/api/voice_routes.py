from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from models.schemas import EmotionState
from agents.sonic import (
    generate_voice_response,
    get_grounding_message,
    get_action_confirmation,
    get_sonic_voice_config
)

router = APIRouter(prefix="/voice", tags=["Voice"])


# ── Request models ───────────────────────────────────────

class VoiceRequest(BaseModel):
    session_id:  str
    user_text:   str
    emotion:     Optional[EmotionState] = EmotionState.CALM
    context:     Optional[str] = ""

class ConfirmationRequest(BaseModel):
    intent_type: str
    entities:    dict


# ── Routes ──────────────────────────────────────────────

@router.post("/respond")
async def voice_respond(req: VoiceRequest):
    """
    Generate an emotion-aware Nova 2 Sonic voice response.
    Returns spoken_text + the Sonic config (speaking rate, voice style, etc.)
    The frontend passes spoken_text to Nova 2 Sonic's TTS stream.
    """
    result = await generate_voice_response(
        user_text=req.user_text,
        emotion=req.emotion,
        context=req.context
    )
    return result


@router.get("/grounding/{emotion}")
async def grounding_message(emotion: EmotionState):
    """
    Get the immediate grounding message for a given emotion state.
    Spoken instantly when distress or crisis is detected —
    before any other processing happens.
    """
    message = get_grounding_message(emotion)
    return {
        "emotion": emotion.value,
        "grounding_message": message,
        "sonic_config": get_sonic_voice_config(emotion)
    }


@router.post("/confirm-action")
async def confirm_action(req: ConfirmationRequest):
    """
    Generate a spoken confirmation before Nova Act executes a task.
    e.g. "I'll book an appointment at Apollo for tomorrow. Shall I go ahead?"
    Always called before ACT so user can cancel if needed.
    """
    confirmation = get_action_confirmation(req.intent_type, req.entities)
    return {
        "intent_type":   req.intent_type,
        "confirmation":  confirmation,
        "sonic_config":  get_sonic_voice_config(EmotionState.CALM)
    }


@router.get("/config/{emotion}")
async def sonic_config(emotion: EmotionState):
    """
    Get the full Nova 2 Sonic config for a given emotion state.
    Includes speaking rate, voice style, turn-taking sensitivity.
    """
    return get_sonic_voice_config(emotion)