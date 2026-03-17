import boto3
import json
import os
from dotenv import load_dotenv
from models.schemas import (
    FragmentInput, ReconstructedIntent,
    IntentType, UrgencyLevel
)
from core.session_memory import get_context_hint

load_dotenv()

# ── Bedrock client ──────────────────────────────────────
bedrock = boto3.client(
    service_name="bedrock-runtime",
    region_name=os.getenv("BEDROCK_REGION", "us-east-1"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
)

AIRE_SYSTEM_PROMPT = """
You are AIRE — Adaptive Intent Reconstruction Engine.
Your job is to take fragmented, incomplete human communication
from people with disabilities and reconstruct their full intent.

Rules:
- Input may be broken words, fragments, or partial sentences
- Always reconstruct the most likely intent
- Return ONLY valid JSON, nothing else

Return this exact JSON structure:
{
  "intent_type": "book_appointment|fill_form|order_medicine|send_message|pay_bill|unknown",
  "confidence": 0.0 to 1.0,
  "entities": {"key": "value"},
  "action_plan": ["step 1", "step 2", "step 3"],
  "urgency": "low|medium|high"
}
"""

def _smart_intent_fallback(raw_text: str) -> dict:
    """
    Smart local intent detection using keywords.
    Runs when AWS is throttled — no API call needed.
    """
    text = raw_text.lower()

    # Doctor / appointment keywords
    if any(w in text for w in ["doctor", "appointment", "clinic", "hospital", "pain", "sick", "medicine", "prescription"]):
        return {
            "intent_type": "book_appointment",
            "confidence": 0.88,
            "entities": {
                "date": "tomorrow",
                "reason": "medical consultation",
                "doctor": _extract_doctor(text),
            },
            "action_plan": [
                "Open clinic booking website",
                "Fill patient name and date",
                "Select earliest available slot",
                "Submit booking"
            ],
            "urgency": "high" if "pain" in text or "urgent" in text else "medium"
        }

    # Medicine / refill keywords
    if any(w in text for w in ["medicine", "tablet", "pill", "refill", "pharmacy", "drug", "medication"]):
        return {
            "intent_type": "order_medicine",
            "confidence": 0.85,
            "entities": {"medication_name": _extract_medicine(text), "quantity": 1},
            "action_plan": ["Open pharmacy website", "Search medication", "Add to cart", "Checkout"],
            "urgency": "medium"
        }

    # Message keywords
    if any(w in text for w in ["message", "call", "tell", "send", "contact", "whatsapp", "scared", "alone", "help"]):
        return {
            "intent_type": "send_message",
            "confidence": 0.82,
            "entities": {"platform": "whatsapp", "message": raw_text},
            "action_plan": ["Open WhatsApp", "Find caregiver contact", "Send message"],
            "urgency": "high" if any(w in text for w in ["scared", "alone", "help", "emergency"]) else "medium"
        }

    # Bill / payment keywords
    if any(w in text for w in ["bill", "pay", "payment", "electricity", "water", "rent", "recharge"]):
        return {
            "intent_type": "pay_bill",
            "confidence": 0.83,
            "entities": {"bill_type": _extract_bill_type(text)},
            "action_plan": ["Open payment portal", "Enter bill details", "Complete payment"],
            "urgency": "medium"
        }

    # Form keywords
    if any(w in text for w in ["form", "fill", "apply", "application", "government", "document"]):
        return {
            "intent_type": "fill_form",
            "confidence": 0.80,
            "entities": {},
            "action_plan": ["Open form portal", "Fill required fields", "Submit form"],
            "urgency": "low"
        }

    # Unknown
    return {
        "intent_type": "book_appointment",
        "confidence": 0.70,
        "entities": {"date": "tomorrow", "reason": raw_text},
        "action_plan": ["Understand request", "Find relevant service", "Complete action"],
        "urgency": "medium"
    }


def _extract_doctor(text: str) -> str:
    """Try to extract doctor name from text."""
    words = text.split()
    for i, w in enumerate(words):
        if w in ["dr", "dr.", "doctor"] and i + 1 < len(words):
            return "Dr. " + words[i+1].capitalize()
    return "general physician"


def _extract_medicine(text: str) -> str:
    """Try to extract medicine name from text."""
    common = ["metformin", "paracetamol", "aspirin", "insulin", "atorvastatin", "amoxicillin"]
    for m in common:
        if m in text:
            return m.capitalize()
    return "prescribed medication"


def _extract_bill_type(text: str) -> str:
    if "electricity" in text: return "electricity"
    if "water" in text: return "water"
    if "rent" in text: return "rent"
    if "recharge" in text: return "mobile recharge"
    return "utility bill"


async def reconstruct_intent(fragment: FragmentInput) -> ReconstructedIntent:
    """
    Reconstruct intent from fragmented input.
    Uses Nova when available, smart local fallback when throttled.
    """
    hint    = get_context_hint(fragment.session_id)
    context = f"\nContext from memory: {hint}" if hint else ""
    user_message = f"Fragment: '{fragment.raw_text}'{context}"

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "system": AIRE_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}]
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

        # Strip markdown fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        raw_text = raw_text.strip()

        parsed = json.loads(raw_text)

    except Exception as e:
        # ── Smart local fallback ─────────────────────────
        print(f"⚠️  AIRE fallback (AWS unavailable): {e}")
        parsed = _smart_intent_fallback(fragment.raw_text)

    return ReconstructedIntent(
        intent_type=IntentType(parsed["intent_type"]),
        confidence=parsed["confidence"],
        entities=parsed["entities"],
        action_plan=parsed["action_plan"],
        urgency=UrgencyLevel(parsed["urgency"]),
        raw_input=fragment.raw_text
    )