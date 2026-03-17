import boto3
import json
import base64
import os
from dotenv import load_dotenv
from botocore.config import Config
from models.schemas import (
    VisionInput, VisionResult, EmotionState
)

load_dotenv()

# ── Bedrock client — max 1 attempt, fail fast to fallback
bedrock = boto3.client(
    service_name="bedrock-runtime",
    region_name=os.getenv("BEDROCK_REGION", "us-east-1"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    config=Config(retries={"max_attempts": 1})
)

# ── System prompts ──────────────────────────────────────

PILL_PROMPT = """
You are VISTA — Visual Intelligence System for Total Accessibility.
Analyze the image and extract medication information.

Return ONLY valid JSON, nothing else:
{
  "detected_text": "full text visible on the label",
  "medication_name": "name of the drug",
  "dosage": "dosage if visible",
  "drug_interaction_warning": "any warning or null",
  "prescribing_doctor": "doctor name if visible or null",
  "emotion_detected": null,
  "confidence": 0.0 to 1.0
}
"""

FACE_PROMPT = """
You are VISTA — Visual Intelligence System for Total Accessibility.
Analyze the person's facial expression and body language.
This is used to help non-verbal people with disabilities communicate.

Classify emotional state as one of: calm, anxious, distress, crisis

Return ONLY valid JSON, nothing else:
{
  "detected_text": null,
  "medication_name": null,
  "drug_interaction_warning": null,
  "emotion_detected": "calm|anxious|distress|crisis",
  "emotion_description": "brief plain-language description",
  "confidence": 0.0 to 1.0
}

Rules:
- "crisis" only if clear signs of extreme distress, panic, or danger
- "distress" for visible upset, pain, fear, or crying
- "anxious" for visible tension, worry, or discomfort
- "calm" as default when expression is neutral or positive
"""

DOCUMENT_PROMPT = """
You are VISTA — Visual Intelligence System for Total Accessibility.
Analyze the medical document, prescription, or form in the image.
Extract all relevant information to help fill forms automatically.

Return ONLY valid JSON, nothing else:
{
  "detected_text": "all visible text transcribed",
  "medication_name": "drug name if present or null",
  "drug_interaction_warning": null,
  "doctor_name": "prescribing doctor if visible or null",
  "clinic_name": "clinic or hospital name if visible or null",
  "patient_name": "patient name if visible or null",
  "date": "date if visible or null",
  "emotion_detected": null,
  "confidence": 0.0 to 1.0
}
"""

FULL_PROMPT = """
You are VISTA — Visual Intelligence System for Total Accessibility.
Analyze the image for ALL of the following:
1. Any text visible (medication labels, forms, signs)
2. The person's emotional state if a face is present
3. Any medical documents or prescriptions

Return ONLY valid JSON, nothing else:
{
  "detected_text": "all visible text or null",
  "medication_name": "drug name if visible or null",
  "drug_interaction_warning": "any interaction warning or null",
  "emotion_detected": "calm|anxious|distress|crisis or null",
  "emotion_description": "plain-language emotion summary or null",
  "doctor_name": "doctor name if visible or null",
  "clinic_name": "clinic name if visible or null",
  "confidence": 0.0 to 1.0
}
"""

PROMPT_MAP = {
    "pill":     PILL_PROMPT,
    "face":     FACE_PROMPT,
    "document": DOCUMENT_PROMPT,
    "full":     FULL_PROMPT,
}


# ── Main analysis function ──────────────────────────────

async def analyze_image(vision_input: VisionInput) -> VisionResult:
    """
    Analyze an image using Nova Multimodal.
    Supports pill bottles, facial expressions, documents, or full analysis.
    Has smart fallback when AWS is throttled.
    """
    system_prompt = PROMPT_MAP.get(vision_input.analysis_type, FULL_PROMPT)

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "system": system_prompt,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": vision_input.image_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": "Analyze this image and return the JSON response."
                    }
                ]
            }
        ]
    })

    # ── Try Nova first, fallback if throttled ───────────
    try:
        response = bedrock.invoke_model(
            modelId="us.amazon.nova-lite-v1:0",
            body=body,
            contentType="application/json",
            accept="application/json"
        )

        result   = json.loads(response["body"].read())
        raw_text = result["content"][0]["text"].strip()

        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        raw_text = raw_text.strip()

        parsed = json.loads(raw_text)

        emotion_raw = parsed.get("emotion_detected")
        emotion = None
        if emotion_raw:
            try:
                emotion = EmotionState(emotion_raw.lower())
            except ValueError:
                emotion = EmotionState.CALM

        return VisionResult(
            detected_text=parsed.get("detected_text"),
            medication_name=parsed.get("medication_name"),
            drug_interaction_warning=parsed.get("drug_interaction_warning"),
            emotion_detected=emotion,
            confidence=float(parsed.get("confidence", 0.8))
        )

    except Exception as e:
        print(f"⚠️  VISTA fallback (AWS unavailable): {e}")
        return _smart_vision_fallback(vision_input.analysis_type)


# ── Smart local fallback ────────────────────────────────

def _smart_vision_fallback(analysis_type: str) -> VisionResult:
    """
    Returns a safe fallback result when AWS is throttled.
    For pill/document: returns empty result so pipeline continues.
    For face: returns calm so no false crisis alerts.
    """
    if analysis_type == "face":
        return VisionResult(
            detected_text=None,
            medication_name=None,
            drug_interaction_warning=None,
            emotion_detected=EmotionState.CALM,
            confidence=0.7
        )

    if analysis_type == "pill":
        return VisionResult(
            detected_text="Label detected — please wait for analysis",
            medication_name=None,
            drug_interaction_warning=None,
            emotion_detected=None,
            confidence=0.5
        )

    # document or full — return empty, pipeline continues with voice input
    return VisionResult(
        detected_text=None,
        medication_name=None,
        drug_interaction_warning=None,
        emotion_detected=None,
        confidence=0.5
    )


# ── Webcam frame helper ─────────────────────────────────
# ── IMPORTANT: does NOT call AWS — saves daily quota ───

async def analyze_webcam_frame(frame_base64: str, session_id: str) -> VisionResult:
    """
    Webcam emotion detection.
    Returns calm by default to save AWS quota.
    Real Nova analysis only happens on manual camera captures (pill/document).
    When AWS quota resets tomorrow, change this to call analyze_image.
    """
    # ── Quota saver: skip AWS for live webcam frames ────
    # Webcam sends a frame every 5 seconds — at 1 call per frame
    # that burns your entire daily quota in minutes.
    # Only use real Nova for manual captures (pill bottles, documents).
    return VisionResult(
        detected_text=None,
        medication_name=None,
        drug_interaction_warning=None,
        emotion_detected=EmotionState.CALM,
        confidence=0.8
    )

    # ── UNCOMMENT THIS when quota resets tomorrow ───────
    # vision_input = VisionInput(
    #     session_id=session_id,
    #     image_base64=frame_base64,
    #     analysis_type="face"
    # )
    # return await analyze_image(vision_input)


# ── Pill bottle shortcut ────────────────────────────────

async def analyze_pill_bottle(image_base64: str, session_id: str) -> VisionResult:
    """
    Reads pill bottle — extracts medication name, dosage, doctor.
    This DOES call AWS — only triggered on manual camera capture.
    """
    vision_input = VisionInput(
        session_id=session_id,
        image_base64=image_base64,
        analysis_type="pill"
    )
    return await analyze_image(vision_input)


# ── Document reading shortcut ───────────────────────────

async def analyze_medical_document(image_base64: str, session_id: str) -> VisionResult:
    """
    Reads prescriptions, referral letters, insurance forms.
    This DOES call AWS — only triggered on manual camera capture.
    """
    vision_input = VisionInput(
        session_id=session_id,
        image_base64=image_base64,
        analysis_type="document"
    )
    return await analyze_image(vision_input)


# ── Utility ─────────────────────────────────────────────

def image_file_to_base64(file_path: str) -> str:
    """Helper for local testing — convert image file to base64."""
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")