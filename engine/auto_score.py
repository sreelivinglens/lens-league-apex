"""
Apex DDI Auto-Scoring Engine
Calls Claude Vision API to automatically score uploaded images
Returns structured JSON with all module scores, audit text, bylines, badges
"""

import base64
import json
import os
import re
import httpx

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL             = "claude-sonnet-4-20250514"

SYSTEM_BRIEF = """
You are the Apex DDI Engine for The Lens League photography rating platform.

FORMULA:
LL-Score = (DoD × weight) + (Disruption × weight) + (DM × weight) + (Wonder × weight) + (AQ × weight)

GENRE WEIGHTS:
Wildlife:   DoD=25% Disruption=20% DM=25% Wonder=20% AQ=10%
Landscapes: DoD=15% Disruption=20% DM=15% Wonder=20% AQ=30%
Street:     DoD=15% Disruption=25% DM=25% Wonder=15% AQ=20%
Wedding:    DoD=10% Disruption=15% DM=25% Wonder=10% AQ=40%
People:     DoD=10% Disruption=20% DM=15% Wonder=15% AQ=40%
Macro:      DoD=35% Disruption=20% DM=15% Wonder=20% AQ=10%

MODULES:
- DoD: Physical risk, mechanical precision, environmental hostility
- Disruption: Visual originality vs global database. ICM audit, lighting audit, painterly audit
- DM: Decisive moment — multiple variables at peak simultaneously. Selection ≠ Decision
- Wonder: Smithsonian standard — the Unseen Truth. Rare behaviour, scientific significance
- AQ: Affective Quotient — tonal archetype + narrative dissonance

ARCHETYPES: Sadness/Forlorn, Hope/Joy, Tension/Dread, Wonder/Transcendence,
Resilient Forlorn, Sovereign Momentum, Compressed Tension, Joyful Disruption,
Forlorn Transcendence, Chromatic Transcendence, Tender Sovereignty, Primal Dread

APEX LAYER RULES:
- Soul Bonus: AQ >= 8.0 removes technical penalties
- Humanity Check: AQ < 4.0 adds -1.5 penalty
- Iconic Wall: score >= 9.0 requires BOTH Disruption AND AQ > 8.5
- Plateau Penalty: DoD >= 9.5 + Disruption < 5.0 caps at 7.9
- Identity Cap: >85% similarity to known winner caps at 6.0
- 10.0 never awarded

TIERS: Apprentice 0-5.0 | Practitioner 5.1-7.5 | Master 7.6-8.9 | Grandmaster 9.0-9.6 | Legend 9.7-9.9

Respond ONLY with a valid JSON object. No preamble, no markdown, no explanation outside the JSON.
"""

SCORE_PROMPT = """Analyse this photograph using the Apex DDI Engine.

Genre: {genre}
Photographer: {photographer}
Title: {title}
Subject: {subject}
Location: {location}

Score all five modules honestly. Apply all Apex layer rules. Calculate the final weighted score.

Return this exact JSON structure:
{{
  "dod": <float 0-10>,
  "disruption": <float 0-10>,
  "dm": <float 0-10>,
  "wonder": <float 0-10>,
  "aq": <float 0-10>,
  "score": <float — final weighted score after all apex rules>,
  "tier": "<Apprentice|Practitioner|Master|Grandmaster|Legend>",
  "archetype": "<archetype name>",
  "soul_bonus": <true|false>,
  "row_technical": "<2-3 sentence technical integrity analysis>",
  "row_geometric": "<2-3 sentence geometric harmony analysis>",
  "row_dm": "<2-3 sentence decisive moment analysis>",
  "row_wonder": "<2-3 sentence wonder factor analysis>",
  "row_aq": "<2-3 sentence AQ soul analysis>",
  "byline_1": "<gap analysis paragraph — what holds this from next tier>",
  "byline_2": "<THE ONE IMPROVEMENT: specific, physical, actionable. No brand names.>",
  "badges_g": ["<strength 1>", "<strength 2>", "<strength 3>"],
  "badges_w": ["<gap 1>", "<gap 2>", "<gap 3>"],
  "iucn_tag": "<IUCN status if applicable, else null>"
}}"""


def encode_image(image_path):
    """Encode image to base64 for API."""
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def auto_score(image_path, genre, title, photographer, subject="", location=""):
    """
    Send image to Claude Vision and get back full Apex DDI scoring.
    Returns dict with all scores and audit text.
    Raises ValueError on API error.
    """
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    # Encode image
    img_data = encode_image(image_path)

    # Determine media type
    ext = os.path.splitext(image_path)[1].lower()
    media_type = "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"

    prompt = SCORE_PROMPT.format(
        genre=genre,
        photographer=photographer,
        title=title,
        subject=subject or "Not specified",
        location=location or "Not specified",
    )

    payload = {
        "model": MODEL,
        "max_tokens": 2000,
        "system": SYSTEM_BRIEF,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": img_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ],
    }

    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
        timeout=60,
    )

    if response.status_code != 200:
        raise ValueError(f"API error {response.status_code}: {response.text}")

    # Extract text content
    content = response.json()
    text = ""
    for block in content.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")

    # Parse JSON — strip any markdown fences if present
    text = re.sub(r"```json|```", "", text).strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse API response as JSON: {e}\nResponse: {text[:500]}")

    return result


def build_audit_data(result, image_obj):
    """
    Convert auto_score result into the audit data dict
    used by compositor.build_card()
    """
    genre    = image_obj.genre or "Wildlife"
    fmt      = image_obj.format or "JPEG"
    subject  = image_obj.subject or ""
    location = image_obj.location or ""

    return {
        "asset":       image_obj.asset_name or "Untitled",
        "meta":        f"{genre}  ·  {fmt}  ·  {subject}  ·  {location}",
        "score":       str(result.get("score", 0)),
        "tier":        result.get("tier", "Practitioner"),
        "dec":         result.get("archetype", "Sovereign Momentum"),
        "credit":      image_obj.photographer_name or "",
        "genre_tag":   f"{genre.upper()}  ·  {fmt.upper()}",
        "soul_bonus":  result.get("soul_bonus", False),
        "iucn_tag":    result.get("iucn_tag"),
        "modules": [
            ("DoD",        result.get("dod", 0)),
            ("Disruption", result.get("disruption", 0)),
            ("DM",         result.get("dm", 0)),
            ("Wonder",     result.get("wonder", 0)),
            ("AQ",         result.get("aq", 0)),
        ],
        "rows": [
            ("Technical\nIntegrity", result.get("row_technical", "")),
            ("Geometric\nHarmony",   result.get("row_geometric", "")),
            ("Decisive\nMoment",     result.get("row_dm", "")),
            ("Wonder\nFactor",       result.get("row_wonder", "")),
            ("AQ — Soul",            result.get("row_aq", "")),
        ],
        "byline_1":      result.get("byline_1", ""),
        "byline_2_body": result.get("byline_2", ""),
        "badges_g":      result.get("badges_g", []),
        "badges_w":      result.get("badges_w", []),
    }
