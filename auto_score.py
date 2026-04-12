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
Wildlife:     DoD=25% Disruption=20% DM=25% Wonder=20% AQ=10%
Landscapes:   DoD=15% Disruption=20% DM=15% Wonder=20% AQ=30%
Street:       DoD=15% Disruption=25% DM=25% Wonder=15% AQ=20%
Wedding:      DoD=10% Disruption=15% DM=25% Wonder=10% AQ=40%
People:       DoD=10% Disruption=20% DM=15% Wonder=15% AQ=40%
Macro:        DoD=35% Disruption=20% DM=15% Wonder=20% AQ=10%
ICM:          DoD=20% Disruption=35% DM=15% Wonder=20% AQ=10%
Aerial:       DoD=30% Disruption=20% DM=15% Wonder=25% AQ=10%
Abstract:     DoD=10% Disruption=35% DM=10% Wonder=25% AQ=20%

CRITICAL — MODULE DEFINITIONS BY GENRE:

DoD (Difficulty of Delivery):
  Wildlife/Aerial: Physical risk, access difficulty, environmental hostility,
    mechanical precision (sharpness, exposure in challenging conditions).
    Blur = technical failure UNLESS the subject is in flight/motion and blur
    is consistent with intentional panning technique.
  ICM / Abstract: DoD measures the SKILL and CONTROL required to execute
    intentional camera movement or long-exposure artistry. Precise,
    repeatable, controlled blur = HIGH DoD. Accidental muddy blur = low DoD.
    Sharpness is IRRELEVANT and must NOT be penalised.
  Street: DoD = speed of reaction, working in chaotic environments,
    capturing fleeting moments in difficult light. Mild motion blur on
    moving subjects is acceptable and often desirable.
  Macro: Extreme DoD — precise focus at high magnification, depth of field
    control, diffraction management. Sharpness IS the DoD criterion here.
  Landscapes: Patience, location access, weather timing, long-exposure
    technique. Intentional long-exposure blur on water/clouds = HIGH DoD.

Disruption (Visual Originality):
  Evaluate against global photographic database. ICM, multiple reflections,
  layered transparencies, painterly rendering, unconventional framing = HIGH
  Disruption. Disruption rewards the UNUSUAL and UNEXPECTED.
  Multiple reflections in a single frame = significant Disruption bonus.
  Intentional blur creating painterly or impressionistic effect = HIGH
  Disruption — this is a deliberate creative choice, not a flaw.

DM (Decisive Moment):
  Multiple variables at peak simultaneously. For ICM this means the
  photographer chose EXACTLY the right duration, direction, and intensity
  of movement. Selection ≠ Decision — reward active creative control.

Wonder (Smithsonian Standard):
  The Unseen Truth. Rare behaviour, scientific significance, or a view of
  the world the audience has never seen. For ICM/Abstract, Wonder is the
  ability to transform the mundane into the extraordinary — showing familiar
  subjects in completely unfamiliar, revelatory ways.

AQ (Affective Quotient):
  Emotional resonance and tonal archetype. Evaluate the FEELING the image
  creates, not its technical attributes.

APEX LAYER RULES:
- Soul Bonus: AQ >= 8.0 removes ALL technical penalties
- Humanity Check: AQ < 4.0 adds -1.5 penalty to AQ
- Iconic Wall: score >= 9.0 requires BOTH Disruption AND AQ > 8.5
- Plateau Penalty: DoD >= 9.5 + Disruption < 5.0 caps at 7.9
- Identity Cap: >85% similarity to known winner caps at 6.0
- 10.0 never awarded

TIERS: Apprentice 0-5.0 | Practitioner 5.1-7.5 | Master 7.6-8.9 | Grandmaster 9.0-9.6 | Legend 9.7-9.9

ARCHETYPES: Sadness/Forlorn, Hope/Joy, Tension/Dread, Wonder/Transcendence,
Resilient Forlorn, Sovereign Momentum, Compressed Tension, Joyful Disruption,
Forlorn Transcendence, Chromatic Transcendence, Tender Sovereignty, Primal Dread

IMPORTANT CALIBRATION NOTES:
- NEVER penalise intentional blur in ICM, Abstract, Street, or long-exposure Landscapes
- Multiple reflections in one frame = compositional complexity = Disruption boost
- Painterly, impressionistic, or ethereal rendering = artistic mastery = reward it
- A technically "imperfect" image with high artistic intent scores HIGHER than a
  technically perfect but creatively empty image
- When in doubt about intent, read the genre — ICM = intentional, always

Respond ONLY with a valid JSON object. No preamble, no markdown, no explanation outside the JSON.
"""

SCORE_PROMPT = """Analyse this photograph using the Apex DDI Engine.

Genre: {genre}
Photographer: {photographer}
Title: {title}
Subject: {subject}
Location: {location}

GENRE CONTEXT: {genre_context}
{calibration_examples}

Score all five modules using the genre-specific definitions above.
Use the calibration examples above as scoring anchors if provided.
Apply all Apex layer rules. Calculate the final weighted score.

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
  "row_technical": "<2-3 sentence technical integrity analysis — for ICM/Abstract acknowledge intentional blur as mastery, not failure>",
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

# Genre-specific context injected into the prompt
GENRE_CONTEXT = {
    'ICM': (
        "This is Intentional Camera Movement photography. Blur is the medium, not a flaw. "
        "Evaluate DoD on the SKILL and CONTROL of the movement — precise, repeatable, "
        "directional blur scores high. Evaluate Disruption on visual originality and "
        "painterly quality. Do NOT mention sharpness as a negative. The photographer "
        "deliberately moved the camera to create this effect."
    ),
    'Abstract': (
        "This is Abstract photography. Conventional sharpness rules do not apply. "
        "Reward visual originality, colour relationships, compositional tension, "
        "and the ability to create meaning from non-literal imagery. "
        "Disruption and Wonder are the primary quality signals."
    ),
    'Street': (
        "This is Street photography. Evaluate for decisive moment, human narrative, "
        "and environmental storytelling. Motion blur on moving subjects is acceptable "
        "and often enhances the sense of energy and life. Reward layered compositions, "
        "reflections, shadows, and unexpected juxtapositions."
    ),
    'Macro': (
        "This is Macro photography. DoD is primarily about precision focus at extreme "
        "magnification, depth of field control, and lighting in tight spaces. "
        "Sharpness on the primary subject is critical. Reward rare subjects, "
        "unusual perspectives, and scientific detail."
    ),
    'Aerial': (
        "This is Aerial photography. DoD reflects the physical difficulty of airborne "
        "capture — vibration control, altitude, light management from elevation. "
        "Reward geometric patterns, scale contrast, and perspectives impossible "
        "from ground level."
    ),
    'Landscapes': (
        "This is Landscape photography. Long-exposure blur on water, clouds, or "
        "moving elements is a deliberate technique and scores HIGH on DoD and Disruption. "
        "Reward light quality, compositional patience, and environmental storytelling."
    ),
    'Wildlife': (
        "This is Wildlife photography. Sharpness, focus accuracy, and exposure in "
        "challenging conditions are the primary DoD criteria. Reward rare behaviour, "
        "scientific significance, and peak-action capture."
    ),
    'default': (
        "Evaluate using genre-appropriate criteria. Reward artistic intent, "
        "technical mastery relative to the genre, and emotional resonance."
    ),
}


def get_genre_context(genre):
    return GENRE_CONTEXT.get(genre, GENRE_CONTEXT['default'])


def get_calibration_examples(genre, limit=3):
    """
    Fetch admin-approved calibration examples for this genre from the DB.
    Returns a formatted string to inject into the prompt, or empty string.
    """
    try:
        # Import here to avoid circular imports
        from models import Image as ImageModel, db
        from flask import current_app
        with current_app.app_context():
            examples = (
                ImageModel.query
                .filter_by(genre=genre, is_calibration_example=True, status='scored')
                .order_by(ImageModel.score.desc())
                .limit(limit)
                .all()
            )
            if not examples:
                return ''
            lines = ['\nCALIBRATION REFERENCE EXAMPLES FOR THIS GENRE:']
            lines.append('These are admin-verified scores for this genre. Use them as anchors.\n')
            for ex in examples:
                audit = ex.get_audit()
                lines.append(
                    f'Title: {ex.asset_name or "Untitled"}\n'
                    f'Score: {ex.score} | Tier: {ex.tier}\n'
                    f'DoD: {ex.dod_score} | Disruption: {ex.disruption_score} | '
                    f'DM: {ex.dm_score} | Wonder: {ex.wonder_score} | AQ: {ex.aq_score}\n'
                    f'Archetype: {ex.archetype}\n'
                    f'Technical: {audit.get("rows", [["",""],["",""],["",""],["",""],["",""]])[0][1][:120] if audit.get("rows") else ""}\n'
                    f'Gap Analysis: {audit.get("byline_1", "")[:200]}\n'
                    f'---'
                )
            return '\n'.join(lines)
    except Exception as e:
        print(f'[calibration examples] {e}')
        return ''



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

    img_data   = encode_image(image_path)
    ext        = os.path.splitext(image_path)[1].lower()
    media_type = "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"

    calibration_block = get_calibration_examples(genre)

    prompt = SCORE_PROMPT.format(
        genre              = genre,
        photographer       = photographer,
        title              = title,
        subject            = subject or "Not specified",
        location           = location or "Not specified",
        genre_context      = get_genre_context(genre),
        calibration_examples = calibration_block,
    )

    payload = {
        "model": MODEL,
        "max_tokens": 2000,
        "temperature": 0.2,
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
            "x-api-key":          ANTHROPIC_API_KEY,
            "anthropic-version":  "2023-06-01",
            "content-type":       "application/json",
        },
        json=payload,
        timeout=60,
    )

    if response.status_code != 200:
        raise ValueError(f"API error {response.status_code}: {response.text}")

    content = response.json()
    text = ""
    for block in content.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")

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
