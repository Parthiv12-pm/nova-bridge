"""
core/trust_layer.py
================================
Trust & Safety Layer for Nova Bridge.
Verifies every website and action BEFORE Nova Act executes anything.

Frontend shows this panel before every action:
  Safety Check
  ✓ Verified website (practo.com)
  ✓ Secure connection (HTTPS)
  ✓ Low risk action
  → Approved. Proceeding...

Called by:
  - agents/act.py         (before every skill execution)
  - api/main.py           (pipeline safety gate)
  - agents/skills/*.py    (each skill checks before acting)
"""

from urllib.parse import urlparse
from datetime import datetime
from typing import Optional, List, Dict
from models.schemas import TrustCheck, RiskLevel, IntentType


# ═══════════════════════════════════════════════════════════════════════════
#  TRUSTED DOMAIN REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

TRUSTED_DOMAINS: Dict[str, dict] = {
    # ── Demo sites (localhost) — added for hackathon demo ──────────────────
    "localhost":              {"category": "demo",        "name": "Nova Bridge Demo Site"},

    # ── Healthcare ─────────────────────────────────────────────────────────
    "practo.com":             {"category": "healthcare",  "name": "Practo"},
    "apollo247.com":          {"category": "healthcare",  "name": "Apollo 247"},
    "narayanhealth.com":      {"category": "healthcare",  "name": "Narayana Health"},
    "fortishealthcare.com":   {"category": "healthcare",  "name": "Fortis Healthcare"},
    "manipalhospitals.com":   {"category": "healthcare",  "name": "Manipal Hospitals"},
    "maxhealthcare.in":       {"category": "healthcare",  "name": "Max Healthcare"},
    "aiims.edu":              {"category": "healthcare",  "name": "AIIMS"},
    "medanta.org":            {"category": "healthcare",  "name": "Medanta"},

    # ── Pharmacy ───────────────────────────────────────────────────────────
    "1mg.com":                {"category": "pharmacy",    "name": "1mg"},
    "netmeds.com":            {"category": "pharmacy",    "name": "Netmeds"},
    "medplus.in":             {"category": "pharmacy",    "name": "MedPlus"},
    "pharmeasy.in":           {"category": "pharmacy",    "name": "PharmEasy"},
    "apollopharmacy.in":      {"category": "pharmacy",    "name": "Apollo Pharmacy"},
    "reliancesmartmedical.com":{"category": "pharmacy",   "name": "Reliance Smart Medical"},

    # ── Utilities & Bills ──────────────────────────────────────────────────
    "bescom.co.in":           {"category": "utility",     "name": "BESCOM"},
    "mahadiscom.in":          {"category": "utility",     "name": "MSEDCL"},
    "bsnl.co.in":             {"category": "utility",     "name": "BSNL"},
    "airtel.in":              {"category": "utility",     "name": "Airtel"},
    "jio.com":                {"category": "utility",     "name": "Jio"},
    "paytm.com":              {"category": "utility",     "name": "Paytm"},
    "phonepe.com":            {"category": "utility",     "name": "PhonePe"},
    "billdesk.com":           {"category": "utility",     "name": "BillDesk"},
    "torrentpower.com":       {"category": "utility",     "name": "Torrent Power"},

    # ── Messaging ──────────────────────────────────────────────────────────
    "web.whatsapp.com":       {"category": "messaging",   "name": "WhatsApp Web"},
    "mail.google.com":        {"category": "messaging",   "name": "Gmail"},
    "outlook.live.com":       {"category": "messaging",   "name": "Outlook"},

    # ── Transport ──────────────────────────────────────────────────────────
    "olacabs.com":            {"category": "transport",   "name": "Ola"},
    "uber.com":               {"category": "transport",   "name": "Uber"},
    "rapido.bike":            {"category": "transport",   "name": "Rapido"},

    # ── Government ─────────────────────────────────────────────────────────
    "cowin.gov.in":           {"category": "government",  "name": "CoWIN"},
    "umang.gov.in":           {"category": "government",  "name": "UMANG"},
    "uidai.gov.in":           {"category": "government",  "name": "UIDAI / Aadhaar"},
    "india.gov.in":           {"category": "government",  "name": "India.gov.in"},
    "epfindia.gov.in":        {"category": "government",  "name": "EPFO"},
    "incometax.gov.in":       {"category": "government",  "name": "Income Tax"},
}

HIGH_RISK_INTENTS = {}

BLOCKED_KEYWORDS = [
    "bank transfer", "wire money", "send money", "crypto",
    "password", "pin number", "otp", "credit card number",
    "delete account", "unsubscribe all",
]


# ═══════════════════════════════════════════════════════════════════════════
#  CORE TRUST CHECK
# ═══════════════════════════════════════════════════════════════════════════

def run_trust_check(
    url: str,
    action: str,
    intent: Optional[str] = None,
    user_confirmation: bool = False
) -> TrustCheck:
    domain      = _extract_domain(url)
    # localhost is treated as secure even without https
    is_https    = url.startswith("https://") or "localhost" in url
    domain_info = _lookup_domain(domain)
    is_trusted  = domain_info is not None

    risk = _calculate_risk(is_trusted=is_trusted, is_https=is_https,
                           intent=intent, action=action)
    blocked, block_reason = _is_blocked(action, url)

    if blocked:
        approved = False
    elif risk == RiskLevel.HIGH:
        approved = False
    else:
        approved = True

    result = TrustCheck(
        verified_website=is_trusted,
        secure_connection=is_https,
        risk_level=risk,
        approved=approved and not blocked,
        domain=domain,
        action=action,
    )
    _log_check(result, domain_info, block_reason)
    return result


def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        return parsed.netloc.replace("www.", "").lower()
    except:
        return url.lower()


def _lookup_domain(domain: str) -> Optional[dict]:
    """
    Checks if domain is in trusted registry.
    Strips port first: localhost:3000 → localhost
    """
    clean = domain.split(":")[0]           # strips :3000 from localhost:3000
    if clean in TRUSTED_DOMAINS:
        return TRUSTED_DOMAINS[clean]
    if domain in TRUSTED_DOMAINS:
        return TRUSTED_DOMAINS[domain]
    for trusted, info in TRUSTED_DOMAINS.items():
        if domain.endswith(f".{trusted}") or domain == trusted:
            return info
    return None


def _calculate_risk(is_trusted, is_https, intent, action) -> RiskLevel:
    score = 0
    if not is_https:    score += 40
    if not is_trusted:  score += 30
    if intent in HIGH_RISK_INTENTS: score += 20
    risky_words = ["payment", "pay", "transfer", "confirm purchase", "checkout"]
    if any(w in action.lower() for w in risky_words): score += 10
    if score >= 50: return RiskLevel.HIGH
    if score >= 20: return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _is_blocked(action: str, url: str) -> tuple:
    for keyword in BLOCKED_KEYWORDS:
        if keyword in action.lower():
            return True, f"Blocked keyword detected: '{keyword}'"
    return False, None


def _log_check(result, domain_info, block_reason):
    status      = "✅ APPROVED" if result.approved else "🚫 BLOCKED"
    domain_name = domain_info["name"] if domain_info else result.domain
    print(f"\n  ┌─ Safety Check ─────────────────────────────")
    print(f"  │  Domain     : {domain_name} ({result.domain})")
    print(f"  │  Verified   : {'✓' if result.verified_website else '✗'}")
    print(f"  │  HTTPS      : {'✓' if result.secure_connection else '✗'}")
    print(f"  │  Risk level : {result.risk_level.value.upper()}")
    print(f"  │  Decision   : {status}")
    if block_reason:
        print(f"  │  Reason     : {block_reason}")
    print(f"  └────────────────────────────────────────────\n")


# ═══════════════════════════════════════════════════════════════════════════
#  CONVENIENCE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def is_approved(url: str, action: str, intent: str = None) -> bool:
    return run_trust_check(url, action, intent).approved

def get_domain_info(url: str) -> Optional[dict]:
    return _lookup_domain(_extract_domain(url))

def add_trusted_domain(domain: str, category: str, name: str):
    TRUSTED_DOMAINS[domain.replace("www.", "").lower()] = {"category": category, "name": name}
    print(f"  [TrustLayer] Added trusted domain: {name} ({domain})")

def get_trusted_domains_by_category(category: str) -> Dict[str, dict]:
    return {d: i for d, i in TRUSTED_DOMAINS.items() if i["category"] == category}


# ═══════════════════════════════════════════════════════════════════════════
#  FRONTEND FORMATTER
# ═══════════════════════════════════════════════════════════════════════════

def format_for_frontend(check: TrustCheck) -> dict:
    domain_info = _lookup_domain(check.domain)
    domain_name = domain_info["name"] if domain_info else check.domain
    category    = domain_info["category"] if domain_info else "unknown"
    rows = [
        {"icon": "✓" if check.verified_website else "✗",
         "label": f"Verified website ({domain_name})", "ok": check.verified_website},
        {"icon": "✓" if check.secure_connection else "✗",
         "label": "Secure connection (HTTPS)", "ok": check.secure_connection},
        {"icon": "✓" if check.risk_level == RiskLevel.LOW else "⚠" if check.risk_level == RiskLevel.MEDIUM else "✗",
         "label": f"{check.risk_level.value.title()} risk action", "ok": check.risk_level != RiskLevel.HIGH},
    ]
    return {
        "visible":     True,
        "approved":    check.approved,
        "domain":      check.domain,
        "domain_name": domain_name,
        "category":    category,
        "risk_level":  check.risk_level.value,
        "risk_color":  {"low": "success", "medium": "warning", "high": "danger"}.get(check.risk_level.value, "info"),
        "rows":        rows,
        "status_text": "Approved. Proceeding..." if check.approved else "Blocked. Action not allowed.",
        "status_icon": "✓" if check.approved else "✗",
        "action":      check.action,
    }