import os
import re
import json
from datetime import datetime, timezone

# ---------------- PRIORITY DEFINITIONS & WEIGHTS ----------------

CRITICAL_SAFETY_KEYWORDS = [
    r"\blive\s*wire\b", r"\bexposed\s*wire\b", r"\belectrocution\b", r"\belectric\s*shock\b",
    r"\bsparking\b", r"\bopen\s*manhole\b", r"\bmanhole\b", r"\bsinkhole\b", r"\bcave\s*in\b",
    r"\broad\s*collapse\b", r"\bdeep\s*crater\b", r"\bdeadly\b", r"\bfatal\b",
    r"\blife[-\s]*threatening\b", r"\btoxic\b", r"\bpoisonous\b", r"\bcontaminat\w*\b",
    r"\bgas\s*leak\b", r"\bexplosion\b", r"\bfire\s*hazard\b", r"\bdrowning\b",
    r"\bsevere\s*accident\b", r"\bopen\s*drain\b"
]

HIGH_SEVERITY_KEYWORDS = [
    r"\boverflowing\b", r"\bsewage\b", r"\bflooding\b", r"\bwaterlogging\b", r"\bsubmerged\b",
    r"\bburst\s*pipe\b", r"\bmain\s*pipe\b", r"\bpipeline\s*burst\b", r"\bgushing\b",
    r"\bblackspot\b", r"\bmassive\s*dump\b", r"\bstench\b", r"\bfoul\s*smell\b", r"\bunhygienic\b",
    r"\bdisease\b", r"\bdengue\b", r"\bblocked\s*road\b", r"\btraffic\s*halted\b",
    r"\bcomplete\s*outage\b", r"\bblackout\b", r"\bdangerous\b", r"\bhuge\s*crater\b"
]

INFRASTRUCTURE_KEYWORDS = {
    "Hospital / Medical Corridor": [r"\bhospital\b", r"\bclinic\b", r"\bambulance\b", r"\bemergency\b", r"\bmedical\b", r"\bramaiah\b"],
    "School / Academic Zone": [r"\bschool\b", r"\bcollege\b", r"\bcampus\b", r"\bchildren\b", r"\bstudent\b", r"\bvidyalaya\b", r"\binstitute\b"],
    "Transit / Arterial Roadway": [r"\b100\s*ft\b", r"\bmetro\b", r"\bbus\s*stand\b", r"\brailway\b", r"\bjunction\b", r"\bring\s*road\b", r"\bmain\s*road\b", r"\bflyover\b"],
    "Utility Lifeline (Water/Power)": [r"\bbwssb\b", r"\bbescom\b", r"\btransformer\b", r"\bsubstation\b", r"\bmain\s*pipe\b"]
}

CATEGORY_BASE_SCORES = {
    "Drainage & flooding": 45,
    "Water supply": 42,
    "Roads & potholes": 40,
    "Garbage & waste": 35,
    "Streetlights": 30,
    "Other": 25
}


def parse_iso_datetime(dt_str):
    """Safely parse ISO datetime string."""
    if not dt_str:
        return datetime.now(timezone.utc)
    try:
        # Strip trailing Z
        s = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.now(timezone.utc)


def calculate_days_unresolved(first_reported_at, status="Submitted"):
    """Calculate integer days an issue has stayed unresolved."""
    if status in ("Resolved", "Rejected"):
        return 0
    start = parse_iso_datetime(first_reported_at)
    now = datetime.now(timezone.utc)
    delta = now - start
    return max(0, delta.days)


def evaluate_issue_priority(title, description, category, complaints_count=1, first_reported_at=None, address="", ward_name="", status="Submitted"):
    """
    Evaluates multi-factor civic priority for an individual complaint or consolidated group.
    
    Returns:
        dict: {
            "priority": "Critical" | "High" | "Medium" | "Low",
            "priority_score": int (0 - 100),
            "priority_reason": str,
            "priority_factors": dict
        }
    """
    text = f"{title or ''} {description or ''} {address or ''} {ward_name or ''}".lower()
    cat = (category or "").strip()
    base_score = CATEGORY_BASE_SCORES.get(cat, 35)

    factors = {}
    score = base_score
    is_critical_hazard = False
    critical_triggers = []
    high_triggers = []

    # 1. Life Safety & Acute Hazard Check (Critical)
    for pat in CRITICAL_SAFETY_KEYWORDS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            is_critical_hazard = True
            critical_triggers.append(m.group(0))

    if is_critical_hazard:
        score += 45
        factors["safety_impact"] = f"Critical safety threat detected ({', '.join(set(critical_triggers[:3]))})"
    else:
        # 2. High Severity Check
        for pat in HIGH_SEVERITY_KEYWORDS:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                high_triggers.append(m.group(0))

        if high_triggers:
            score += 25
            factors["safety_impact"] = f"High severity civic disruption ({', '.join(set(high_triggers[:3]))})"
        else:
            factors["safety_impact"] = "Standard civic maintenance required"

    # 3. Affected Citizens Multiplier
    count = max(1, int(complaints_count or 1))
    if count == 1:
        citizen_pts = 0
        factors["citizen_impact"] = "1 citizen reporting"
    elif count == 2:
        citizen_pts = 10
        factors["citizen_impact"] = "2 citizens reporting (+10 pts)"
    elif count <= 5:
        citizen_pts = 20
        factors["citizen_impact"] = f"{count} citizens reporting cluster (+20 pts)"
    elif count <= 10:
        citizen_pts = 30
        factors["citizen_impact"] = f"{count} citizens reporting widespread issue (+30 pts)"
    else:
        citizen_pts = 40
        factors["citizen_impact"] = f"{count} citizens reporting acute civic crisis (+40 pts)"
    score += citizen_pts

    # 4. Aging / Days Unresolved Escalation
    days = calculate_days_unresolved(first_reported_at, status=status)
    factors["days_unresolved"] = days

    if days == 0:
        age_pts = 0
        factors["aging_escalation"] = "Reported today"
    elif days <= 2:
        age_pts = 5
        factors["aging_escalation"] = f"{days} days unresolved (+5 pts)"
    elif days <= 6:
        age_pts = 12
        factors["aging_escalation"] = f"{days} days unresolved (+12 pts)"
    elif days <= 14:
        age_pts = 20
        factors["aging_escalation"] = f"{days} days unresolved — overdue (+20 pts)"
    else:
        age_pts = 28
        factors["aging_escalation"] = f"{days} days unresolved — severely overdue (+28 pts)"
    score += age_pts

    # 5. Sensitive Zones & Essential Infrastructure Context
    infra_matches = []
    for zone_type, patterns in INFRASTRUCTURE_KEYWORDS.items():
        for p in patterns:
            if re.search(p, text, re.IGNORECASE):
                infra_matches.append(zone_type)
                break

    if infra_matches:
        infra_pts = min(25, 12 * len(infra_matches))
        score += infra_pts
        factors["infrastructure_context"] = f"Adjacent to {', '.join(infra_matches)} (+{infra_pts} pts)"
    else:
        factors["infrastructure_context"] = "Standard residential / commercial corridor"

    # 6. Hard safety override: single acute hazard is unconditionally Critical
    if is_critical_hazard:
        score = max(score, 85)

    score = min(100, max(15, score))

    # 7. Map score to tier
    if score >= 80 or is_critical_hazard:
        priority = "Critical"
    elif score >= 60:
        priority = "High"
    elif score >= 40:
        priority = "Medium"
    else:
        priority = "Low"

    # 8. Synthesize explanation reason
    reason_parts = [f"{priority} priority ({score}/100) assigned for {cat}."]
    if is_critical_hazard:
        reason_parts.append(f"Immediate safety threat: {factors['safety_impact']}.")
    elif high_triggers:
        reason_parts.append(f"Severe disruption: {factors['safety_impact']}.")

    if count > 1:
        reason_parts.append(f"{count} citizens actively affected.")

    if days >= 2:
        reason_parts.append(f"Unresolved for {days} days.")

    if infra_matches:
        reason_parts.append(f"Sensitive location near {', '.join(infra_matches)}.")

    priority_reason = " ".join(reason_parts)

    return {
        "priority": priority,
        "priority_score": score,
        "priority_reason": priority_reason,
        "priority_factors": factors
    }
