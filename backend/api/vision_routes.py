from fastapi import APIRouter
from models.schemas import VisionInput, VisionResult
from core.vista import (
    analyze_image,
    analyze_webcam_frame,
    analyze_pill_bottle,
    analyze_medical_document
)

router = APIRouter(prefix="/vision", tags=["Vision"])


# ── Routes ──────────────────────────────────────────────

@router.post("/analyze", response_model=VisionResult)
async def analyze(vision_input: VisionInput):
    """
    Full image analysis — auto-detects pills, documents, or facial emotion.
    Pass analysis_type as: "full" | "pill" | "document" | "face"
    """
    return await analyze_image(vision_input)


@router.post("/webcam", response_model=VisionResult)
async def webcam_frame(session_id: str, frame_base64: str):
    """
    Analyze a single webcam frame for facial emotion.
    Called every few seconds by the frontend for real-time detection.
    Returns emotion_detected: calm | anxious | distress | crisis
    """
    return await analyze_webcam_frame(frame_base64, session_id)


@router.post("/pill-bottle", response_model=VisionResult)
async def pill_bottle(session_id: str, image_base64: str):
    """
    Analyze a pill bottle photo.
    Extracts medication name, dosage, and prescribing doctor.
    This context is automatically passed to AIRE for appointment booking.
    """
    return await analyze_pill_bottle(image_base64, session_id)


@router.post("/document", response_model=VisionResult)
async def medical_document(session_id: str, image_base64: str):
    """
    Read a scanned prescription, referral letter, or insurance form.
    Extracts all text, doctor name, clinic name, and patient name.
    """
    return await analyze_medical_document(image_base64, session_id)