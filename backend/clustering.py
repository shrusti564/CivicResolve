import os
import math
import re
import uuid
import difflib
import threading
from datetime import datetime, timezone

try:
    from .database import (
        connect,
        get_complaint_by_id,
        list_complaint_groups,
        get_complaint_group,
        create_complaint_group,
        link_complaint_to_group,
        update_group_info
    )
    from .priority import evaluate_issue_priority
except (ImportError, ValueError):
    from database import (
        connect,
        get_complaint_by_id,
        list_complaint_groups,
        get_complaint_group,
        create_complaint_group,
        link_complaint_to_group,
        update_group_info
    )
    from priority import evaluate_issue_priority

_clustering_lock = threading.RLock()

# Configurable similarity threshold (defaults to 0.55 for robust clustering)
SIMILARITY_THRESHOLD = float(os.getenv("DUPLICATE_SIMILARITY_THRESHOLD", "0.55"))

# Civic topic keywords to enhance semantic matching
CIVIC_KEYWORDS = {
    "Roads & potholes": ["pothole", "crater", "road", "tar", "asphalt", "ditch", "surface", "bump", "pavement"],
    "Garbage & waste": ["garbage", "waste", "trash", "bin", "dump", "debris", "refuse", "litter", "smell", "collection", "black spot"],
    "Streetlights": ["streetlight", "street light", "light", "lamp", "pole", "dark", "bulb", "flicker", "wire"],
    "Drainage & flooding": ["drain", "drainage", "flood", "waterlogging", "sewage", "gutter", "clog", "overflow", "stagnant"],
    "Water supply": ["water", "leak", "pipe", "pipeline", "burst", "drinking", "supply", "pressure", "contamination"]
}


def haversine_distance_meters(lat1, lon1, lat2, lon2):
    """Calculate distance in meters between two coordinates."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (ValueError, TypeError):
        return None

    r = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def calculate_geographic_proximity(lat1, lon1, ward1, addr1, lat2, lon2, ward2, addr2):
    """
    Returns a score between 0.0 and 1.0 representing geographic proximity.
    Supports exact GPS, neighborhood/ward proximity, and address token matching.
    """
    both_gps = None not in (lat1, lon1, lat2, lon2)
    w1 = (ward1 or "").strip().lower()
    w2 = (ward2 or "").strip().lower()
    same_ward = bool(w1 and w2 and w1 == w2)

    if both_gps:
        dist_m = haversine_distance_meters(lat1, lon1, lat2, lon2)
        if dist_m is None:
            return 0.2
        if dist_m <= 150:
            return 1.0  # Immediate spot / doorstep
        elif dist_m <= 400:
            return 0.95
        elif dist_m <= 800:
            return 0.90 if same_ward else 0.80
        elif dist_m <= 1500:
            return 0.75 if same_ward else 0.55
        elif dist_m <= 2500:
            return 0.45 if same_ward else 0.20
        else:
            return 0.0  # More than 2.5km apart is definitely not the same civic issue

    # When GPS is missing on one or both:
    if same_ward:
        base_score = 0.70
    elif w1 and w2 and w1 != w2:
        return 0.10
    else:
        base_score = 0.40

    # Check address token overlap
    a1 = set(re.findall(r"[a-z0-9]+", (addr1 or "").lower()))
    a2 = set(re.findall(r"[a-z0-9]+", (addr2 or "").lower()))
    # Remove common stop tokens
    stop = {"road", "cross", "main", "street", "near", "opposite", "bengaluru", "bangalore", "karnataka"}
    a1_sig = a1 - stop
    a2_sig = a2 - stop

    if a1_sig and a2_sig:
        overlap = len(a1_sig & a2_sig) / max(len(a1_sig | a2_sig), 1)
        base_score = min(1.0, base_score + 0.35 * overlap)

    return base_score


# Civic synonyms and concept mapping with extensive typo tolerance
CIVIC_SYNONYMS = {
    # Road / Pothole terms and common citizen typos
    "pothole": "concept:pothole", "potholes": "concept:pothole", "pothol": "concept:pothole", "pothle": "concept:pothole",
    "potgole": "concept:pothole", "potfole": "concept:pothole", "pot hole": "concept:pothole", "pathole": "concept:pothole",
    "puthole": "concept:pothole", "crater": "concept:pothole", "craters": "concept:pothole", "crator": "concept:pothole",
    "ditch": "concept:pothole", "cavity": "concept:pothole", "rut": "concept:pothole", "pavement": "concept:road",
    "asphalt": "concept:road", "tar": "concept:road", "road": "concept:road", "street": "concept:road",
    "surface": "concept:road", "bump": "concept:road", "skid": "concept:road", "slip": "concept:road",
    "large": "concept:severity_high", "big": "concept:severity_high", "huge": "concept:severity_high",
    "deep": "concept:severity_high", "massive": "concept:severity_high", "dangerous": "concept:severity_high",

    # Waste / Garbage terms and typos
    "garbage": "concept:waste", "garbge": "concept:waste", "garbag": "concept:waste", "garbeg": "concept:waste",
    "trash": "concept:waste", "waste": "concept:waste", "debris": "concept:waste", "refuse": "concept:waste",
    "litter": "concept:waste", "rubbish": "concept:waste", "kachra": "concept:waste", "dump": "concept:dump",
    "dumped": "concept:dump", "dumping": "concept:dump", "bin": "concept:dump", "bins": "concept:dump",
    "blackspot": "concept:dump", "pile": "concept:dump", "piles": "concept:dump", "accumulation": "concept:dump",
    "smell": "concept:odor", "stench": "concept:odor", "stink": "concept:odor", "foul": "concept:odor", "unhygienic": "concept:odor",

    # Streetlight terms and typos
    "streetlight": "concept:light", "streetlights": "concept:light", "stretlight": "concept:light", "streatlight": "concept:light",
    "light": "concept:light", "lights": "concept:light", "lamp": "concept:light", "lamps": "concept:light",
    "pole": "concept:light", "poles": "concept:light", "dark": "concept:darkness", "darkness": "concept:darkness",
    "dim": "concept:darkness", "night": "concept:darkness", "flicker": "concept:electrical", "flickering": "concept:electrical",
    "bulb": "concept:electrical", "wire": "concept:electrical",

    # Drainage / Flooding terms and typos
    "drain": "concept:drainage", "drains": "concept:drainage", "drainage": "concept:drainage", "drainge": "concept:drainage",
    "drinage": "concept:drainage", "dranage": "concept:drainage", "gutter": "concept:drainage", "gutters": "concept:drainage",
    "sewer": "concept:drainage", "sewage": "concept:drainage", "stormwater": "concept:drainage",
    "clog": "concept:clog", "clogged": "concept:clog", "blocked": "concept:clog", "blockage": "concept:clog",
    "overflow": "concept:flooding", "overflowing": "concept:flooding", "flood": "concept:flooding", "flooding": "concept:flooding",
    "waterlogging": "concept:flooding", "waterlogged": "concept:flooding", "stagnant": "concept:flooding",

    # Water Supply terms and typos
    "pipe": "concept:pipe", "pipes": "concept:pipe", "pipeline": "concept:pipe", "pipline": "concept:pipe", "valve": "concept:pipe",
    "leak": "concept:leakage", "leaks": "concept:leakage", "leakage": "concept:leakage", "leaking": "concept:leakage",
    "leek": "concept:leakage", "leeking": "concept:leakage", "burst": "concept:leakage", "gushing": "concept:leakage",
    "supply": "concept:water_supply", "pressure": "concept:water_supply", "drinking": "concept:clean_water",
    "potable": "concept:clean_water", "contamination": "concept:dirty_water"
}

_KNOWN_SYNONYM_KEYS = list(CIVIC_SYNONYMS.keys())


def normalize_token(t):
    """Clean duplicate characters and phonetic citizen typos."""
    t = re.sub(r"([a-z])\1{2,}", r"\1", t)
    t = re.sub(r"([aeiou])\1+$", r"\1", t)
    return t


def extract_semantic_features(text, category=None):
    """Extract canonical concepts, civic keywords and significant terms."""
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    features = set()

    if category:
        clean_cat = re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_")
        features.add(f"domain:{clean_cat}")

    for t in tokens:
        t_clean = normalize_token(t)
        if t in CIVIC_SYNONYMS:
            features.add(CIVIC_SYNONYMS[t])
        elif t_clean in CIVIC_SYNONYMS:
            features.add(CIVIC_SYNONYMS[t_clean])
        else:
            # Fuzzy match against known civic terms using difflib
            matches = difflib.get_close_matches(t_clean, _KNOWN_SYNONYM_KEYS, n=1, cutoff=0.72)
            if matches:
                features.add(CIVIC_SYNONYMS[matches[0]])
            elif len(t_clean) > 3:
                features.add(t_clean)

    return features


def calculate_semantic_similarity(title1, desc1, title2, desc2, category=None):
    """
    Returns a score between 0.0 and 1.0 for textual and semantic similarity.
    Captures semantic similarity across different phrasing using concept mapping.
    """
    text1 = f"{title1 or ''}. {desc1 or ''}".strip().lower()
    text2 = f"{title2 or ''}. {desc2 or ''}".strip().lower()

    if not text1 or not text2:
        return 0.0

    f1 = extract_semantic_features(text1, category)
    f2 = extract_semantic_features(text2, category)

    if not f1 or not f2:
        return 0.0

    common = f1 & f2
    total = f1 | f2
    jaccard = len(common) / max(len(total), 1)

    shared_concepts = [c for c in common if c.startswith("concept:")]
    concept_bonus = min(0.40, 0.15 * len(shared_concepts))
    term_bonus = 0.05 * min(len(common), 4)

    score = min(1.0, (0.50 * jaccard) + concept_bonus + term_bonus)
    return round(score, 4)


def calculate_composite_similarity(complaint, candidate):
    """
    Calculates overall composite similarity between a complaint and a candidate (group or complaint).
    Prioritizes same category and geographic location/ward.
    Returns (score, details_dict).
    """
    # 1. Category must match
    cat1 = (complaint.get("category") or "").strip().lower()
    cat2 = (candidate.get("category") or "").strip().lower()

    if cat1 != cat2:
        return 0.0, {"category_match": False}

    # 2. Geographic proximity
    geo_score = calculate_geographic_proximity(
        complaint.get("latitude"), complaint.get("longitude"), complaint.get("ward_name"), complaint.get("address"),
        candidate.get("latitude"), candidate.get("longitude"), candidate.get("ward_name"), candidate.get("address")
    )

    both_gps = (complaint.get("latitude") is not None and candidate.get("latitude") is not None)

    # If both have GPS and are over 2.5km apart, hard reject as duplicate
    if both_gps and geo_score == 0.0:
        return 0.0, {"category_match": True, "geo_score": 0.0, "reason": "Too far apart"}

    # 3. Semantic similarity
    text_score = calculate_semantic_similarity(
        complaint.get("title", ""), complaint.get("description", ""),
        candidate.get("title", ""), candidate.get("description", "") or candidate.get("summary", ""),
        category=complaint.get("category")
    )

    # 4. Composite blend:
    # When two complaints share the exact category and are in the same immediate location / ward (geo_score >= 0.80),
    # the location signal strongly confirms duplicate reporting.
    if geo_score >= 0.80:
        score = (0.30 * text_score) + (0.70 * geo_score)
    elif both_gps:
        score = (0.45 * text_score) + (0.55 * geo_score)
    else:
        score = (0.55 * text_score) + (0.45 * geo_score)

    return round(score, 4), {
        "category_match": True,
        "text_score": round(text_score, 4),
        "geo_score": round(geo_score, 4),
        "both_gps": both_gps,
        "composite_score": round(score, 4)
    }


def generate_group_title_and_summary(category, ward_name, address, complaints):
    """
    Synthesize a clean title and summary for the consolidated issue.
    Uses Gemini LLM if GEMINI_API_KEY is available, or high-quality template synthesis.
    """
    count = len(complaints)
    loc_part = ward_name or address or "Bengaluru"
    
    # Try Gemini if configured
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key and count > 0:
        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            complaint_texts = "\n".join([f"- Title: {c['title']} | Details: {c['description']}" for c in complaints[:8]])
            prompt = (
                f"You are a civic operations intelligence system in Bengaluru.\n"
                f"Consolidate {count} citizen complaints regarding {category} at {loc_part}.\n"
                f"Reports:\n{complaint_texts}\n\n"
                f"Provide:\n"
                f"1. A concise, formal Issue Title (max 8 words, e.g. '{category} – {loc_part}').\n"
                f"2. A 2-3 sentence AI Summary synthesizing the core problem, affected area, and urgency.\n"
                f"Respond in format:\nTITLE: <title>\nSUMMARY: <summary>"
            )
            response = client.models.generate_content(
                model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=prompt
            )
            text = response.text or ""
            title_match = re.search(r"TITLE:\s*(.+)", text, re.IGNORECASE)
            summary_match = re.search(r"SUMMARY:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
            if title_match and summary_match:
                return title_match.group(1).strip(), summary_match.group(1).strip()
        except Exception:
            pass

    # Intelligent deterministic synthesis
    primary_title = complaints[0]["title"] if complaints else f"{category} Issue"
    title = f"{primary_title}"
    if ward_name and ward_name not in title:
        title = f"{primary_title} – {ward_name}"

    if count == 1:
        summary = complaints[0]["description"]
    else:
        snippets = []
        for i, c in enumerate(complaints[:4], 1):
            desc_snip = c.get("description", "").strip()
            if len(desc_snip) > 110:
                desc_snip = desc_snip[:107] + "..."
            snippets.append(f"Report {i}: \"{desc_snip}\"")

        summary = (
            f"Consolidated issue from {count} citizen reports regarding {category.lower()} in {loc_part}. "
            f"Citizens highlighted:\n" + "\n".join(snippets)
        )

    return title, summary


def find_matching_group_for_complaint(complaint, threshold=None):
    """
    Search existing active groups to find the best matching consolidated issue.
    Returns (matching_group, score) or (None, 0.0).
    """
    if threshold is None:
        threshold = SIMILARITY_THRESHOLD

    # Get active groups of matching category
    with connect() as conn:
        groups = [dict(r) for r in conn.execute(
            "SELECT * FROM complaint_groups WHERE category=? AND status != 'Rejected' ORDER BY last_reported_at DESC",
            (complaint.get("category"),)
        ).fetchall()]

    if not groups:
        return None, 0.0

    best_group = None
    best_score = 0.0

    for grp in groups:
        score, details = calculate_composite_similarity(complaint, grp)
        if score >= threshold and score > best_score:
            best_score = score
            best_group = grp

    return best_group, best_score


def process_complaint_clustering(complaint_id):
    """
    Atomically clusters a complaint:
    1. Checks if a matching group exists.
    2. If found, links the complaint to that group and updates group metadata.
    3. If no match, creates a new complaint group and links the complaint to it.
    Thread-safe to prevent race conditions during concurrent submissions.
    """
    with _clustering_lock:
        complaint = get_complaint_by_id(complaint_id)
        if not complaint:
            return None

        # If already linked to a valid group, return that group
        if complaint.get("group_id"):
            existing_group = get_complaint_group(complaint["group_id"])
            if existing_group:
                return existing_group

        matched_group, score = find_matching_group_for_complaint(complaint)

        if matched_group:
            # Associate with existing group
            group_id = matched_group["id"]
            link_complaint_to_group(complaint["id"], group_id)

            # Refresh title and summary with new complaint included
            updated_group = get_complaint_group(group_id)
            linked_complaints = updated_group.get("complaints", [complaint])

            title, summary = generate_group_title_and_summary(
                updated_group["category"],
                updated_group["ward_name"],
                updated_group["address"],
                linked_complaints
            )

            # Re-evaluate priority if not manually overridden by admin
            if updated_group.get("priority_override") != 1:
                combined_desc = " ".join([c.get("description", "") for c in linked_complaints])
                p_eval = evaluate_issue_priority(
                    title=title,
                    description=combined_desc,
                    category=updated_group["category"],
                    complaints_count=len(linked_complaints),
                    first_reported_at=updated_group.get("first_reported_at"),
                    address=updated_group.get("address", ""),
                    ward_name=updated_group.get("ward_name", ""),
                    status=updated_group.get("status", "Submitted")
                )
                update_group_info(
                    group_id,
                    title=title,
                    summary=summary,
                    priority=p_eval["priority"],
                    priority_score=p_eval["priority_score"],
                    priority_reason=p_eval["priority_reason"],
                    priority_factors=p_eval["priority_factors"]
                )
            else:
                update_group_info(group_id, title=title, summary=summary)

            return get_complaint_group(group_id)
        else:
            # Create a brand new group
            now = complaint.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
            ref = "GRP-" + datetime.now(timezone.utc).strftime("%y%m%d") + "-" + uuid.uuid4().hex[:6].upper()

            title, summary = generate_group_title_and_summary(
                complaint["category"],
                complaint.get("ward_name"),
                complaint.get("address"),
                [complaint]
            )

            p_eval = evaluate_issue_priority(
                title=title,
                description=complaint.get("description", ""),
                category=complaint["category"],
                complaints_count=1,
                first_reported_at=now,
                address=complaint.get("address", ""),
                ward_name=complaint.get("ward_name", ""),
                status=complaint.get("status", "Submitted")
            )

            group_data = {
                "reference": ref,
                "title": title,
                "summary": summary,
                "category": complaint["category"],
                "ward_name": complaint.get("ward_name"),
                "corporation": complaint.get("corporation"),
                "address": complaint.get("address"),
                "latitude": complaint.get("latitude"),
                "longitude": complaint.get("longitude"),
                "status": complaint.get("status", "Submitted"),
                "priority": p_eval["priority"],
                "priority_score": p_eval["priority_score"],
                "priority_reason": p_eval["priority_reason"],
                "priority_factors": p_eval["priority_factors"],
                "priority_override": 0,
                "complaints_count": 1,
                "first_reported_at": now,
                "last_reported_at": now
            }

            new_group = create_complaint_group(group_data)
            link_complaint_to_group(complaint["id"], new_group["id"])
            return get_complaint_group(new_group["id"])


def cluster_all_unassigned_complaints():
    """
    Scans all existing complaints in the database and ensures every unassigned complaint
    is clustered into an appropriate complaint group.
    """
    return recluster_all_complaints(force=False)


def recluster_all_complaints(force=False):
    """
    Cleans up fragmented groups and re-clusters complaints from scratch chronologically
    using the enhanced duplicate clustering engine.
    """
    with _clustering_lock:
        with connect() as conn:
            if force:
                conn.execute("UPDATE complaints SET group_id = NULL")
                conn.execute("DELETE FROM citizen_notifications WHERE group_id IS NOT NULL")
                conn.execute("DELETE FROM complaint_groups")
                conn.commit()

            complaints = [dict(r) for r in conn.execute(
                "SELECT id FROM complaints WHERE group_id IS NULL ORDER BY created_at ASC, id ASC"
            ).fetchall()]

        clustered_count = 0
        for item in complaints:
            res = process_complaint_clustering(item["id"])
            if res:
                clustered_count += 1

        all_groups = list_complaint_groups()
        multi_count = sum(1 for g in all_groups if g.get("complaints_count", 1) > 1)

        return {
            "processed": len(complaints),
            "clustered": clustered_count,
            "total_groups": len(all_groups),
            "multi_report_groups": multi_count
        }
