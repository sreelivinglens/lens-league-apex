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
Creative:   DoD=20% Disruption=30% DM=15% Wonder=20% AQ=15%
Drone:      DoD=30% Disruption=20% DM=15% Wonder=25% AQ=10%

STEP 0 — CREATIVE GENRE OVERRIDE (apply before anything else):
If genre = 'Creative':
- Sharpness is NEVER penalised when absent
- Sharpness IS rewarded when present (sharp subject + technique blur = HIGHEST DoD 8.5-9.5)
- Pure technique/abstract work scores on Disruption and Wonder — equally valid
- DoD tiers:
  8.5-9.5: Sharp subject + technique simultaneously (panning with frozen subject,
           star trails with sharp foreground, astro with sharp Milky Way,
           light painting with sharp subject, ICM with selective focus)
  7.0-8.5: Skilled single-technique outdoor (ICM at dawn/dusk, layered blur patterns,
           zoom burst, long exposure in difficult conditions)
  5.0-7.0: Good technique in standard conditions
  3.0-5.0: Technique present but inconsistent
- Set judge_referral=true if score >= 7.0 OR technique is exceptionally complex
- NEVER mention sharpness as negative, NEVER suggest faster shutter speed,
  NEVER say genre mismatch

STEP 1 — TECHNIQUE DETECTION (for non-Creative genres):
Before scoring any non-Creative image, examine for intentional motion blur:

INTENTIONAL BLUR SIGNALS (treat as deliberate creative choice):
- Consistent, directional blur across entire frame
- Painterly, impressionistic, or watercolour-like rendering
- Long-exposure blur on water, clouds, light trails
- Dreamy, ethereal quality that transforms the subject
- The blur feels COMPOSED, not accidental

ACCIDENTAL BLUR (penalise):
- Random multidirectional blur with no pattern
- Inconsistent blur — some areas randomly sharp, some randomly blurred

IF INTENTIONAL BLUR detected in non-Creative genre:
- Genre label is OVERRIDDEN for DoD — evaluate on technique skill
- "No sharp subject" is NOT a penalty — the technique IS the subject
- Do NOT write criticism about missing fauna/people/subjects
- Do NOT suggest faster shutter speed

MODULE DEFINITIONS:

DoD (Difficulty of Delivery):
  Wildlife: Physical risk, access difficulty, environmental hostility,
    mechanical precision. Sharp animal subject = high DoD.
    Intentional panning blur on moving animal = acceptable technique.
  Drone: Physical difficulty of aerial operation — wind, altitude,
    vibration control, light management from elevation, regulatory complexity.
    Geometric patterns and impossible ground-level perspectives score highest.
  Street: Speed of reaction, working in chaos, difficult light.
    Motion blur on moving subjects is acceptable and adds energy.
  Macro: Extreme precision at high magnification. Sharpness IS DoD.
  Landscapes: Patience, location access, weather timing, long-exposure control.
    Long-exposure blur on water/clouds = HIGH DoD.
  Creative: See STEP 0 above.

Disruption (Visual Originality):
  Evaluate against global photographic database.
  Intentional blur, painterly rendering, multiple reflections, layered
  transparencies, drone geometry, unconventional framing = HIGH Disruption.
  For Drone: patterns only visible from altitude score very high.
  For Creative: layered blur mosaics and atmospheric abstractions that
  create an entirely new visual language score HIGHEST.

DM (Decisive Moment):
  Multiple variables at peak simultaneously.
  For Creative/technique images: the precise decision of when and how
  to execute — right conditions, right timing, right duration.
  Selection ≠ Decision — reward active creative control.

Wonder (Smithsonian Standard):
  The Unseen Truth. Rare behaviour, scientific significance, or a view
  the audience has never seen.
  For Drone: perspectives impossible from ground = high Wonder.
  For Creative: revealing the invisible (star movement, time compression,
  light physics, hidden beauty in motion) = high Wonder.
  Transforming the familiar into the transcendent IS valid Wonder.

AQ (Affective Quotient):
  Emotional resonance and tonal archetype. Evaluate the FEELING the
  image creates, not its technical attributes.

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

CALIBRATION NOTES:
- A technically "imperfect" image with high artistic intent scores HIGHER
  than a technically perfect but creatively empty image
- Multiple reflections = compositional complexity = Disruption boost
- Soul Bonus (AQ >= 8.0) removes technical penalties — apply it
- For Creative and technique-detected images: TECHNIQUE WINS

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

MANDATORY: If genre is 'Creative' — apply STEP 0 override immediately.
Sharpness is never penalised. Score DoD on technique difficulty.
Set judge_referral=true if score >= 7.0 or technique is exceptional.

For all other genres: check for intentional motion blur before applying
genre rules (STEP 1). If detected, technique overrides genre DoD criteria.

Score all five modules. Apply all Apex layer rules. Calculate final weighted score.

Return this exact JSON structure:
{{
  "dod": <float 0-10>,
  "disruption": <float 0-10>,
  "dm": <float 0-10>,
  "wonder": <float 0-10>,
  "aq": <float 0-10>,
  "score": <float>,
  "tier": "<Apprentice|Practitioner|Master|Grandmaster|Legend>",
  "archetype": "<archetype name>",
  "soul_bonus": <true|false>,
  "judge_referral": <true if Creative genre AND score >= 7.0 OR exceptional technique, else false>,
  "row_technical": "<2-3 sentence technical analysis — for Creative/technique images praise the technique>",
  "row_geometric": "<2-3 sentence geometric harmony analysis>",
  "row_dm": "<2-3 sentence decisive moment analysis>",
  "row_wonder": "<2-3 sentence wonder factor analysis>",
  "row_aq": "<2-3 sentence AQ soul analysis>",
  "byline_1": "<gap analysis — what holds this from next tier>",
  "byline_2": "<THE ONE IMPROVEMENT: specific, physical, actionable. No brand names.>",
  "badges_g": ["<strength 1>", "<strength 2>", "<strength 3>"],
  "badges_w": ["<gap 1>", "<gap 2>", "<gap 3>"],
  "iucn_tag": "<IUCN status if applicable, else null>"
}}"""

GENRE_CONTEXT = {
    'Creative': (
        "This is Creative photography covering all technique-driven work: ICM, panning, zoom burst, "
        "intentional blur, long exposure, star trails, astrophotography, light painting, multiple "
        "exposure, layered blur patterns, atmospheric mosaics, and any image where artistic or "
        "technical execution is the primary creative statement. "
        "Sharpness is NEVER penalised when absent. Sharpness IS rewarded when present as it "
        "demonstrates simultaneous technical and artistic control (highest DoD). "
        "Pure abstract/mosaic/atmospheric work can score equally high or higher on Disruption and Wonder. "
        "Refer to STEP 0 for full DoD scoring guide."
    ),
    'Drone': (
        "This is Drone photography. DoD reflects the physical and regulatory difficulty of aerial "
        "operation — wind management, altitude, vibration control, light from elevation, "
        "airspace regulations, battery constraints. "
        "Reward geometric patterns only visible from altitude, scale contrast between "
        "foreground and background, shadow patterns, and perspectives physically impossible "
        "from ground level. Wonder scores highest for images that genuinely reveal something "
        "the human eye has never seen from the ground."
    ),
    'Wildlife': (
        "This is Wildlife photography. Sharpness, focus accuracy, and exposure in challenging "
        "conditions are the primary DoD criteria. Reward rare behaviour, scientific significance, "
        "and peak-action capture. Intentional panning blur on moving subjects is acceptable technique."
    ),
    'Landscapes': (
        "This is Landscape photography. Long-exposure blur on water, clouds, or moving elements "
        "is deliberate technique and scores HIGH on DoD and Disruption. "
        "Reward light quality, compositional patience, and environmental storytelling."
    ),
    'Street': (
        "This is Street photography. Evaluate for decisive moment, human narrative, and "
        "environmental storytelling. Motion blur on moving subjects is acceptable and often "
        "enhances energy. Reward layered compositions, reflections, shadows, and unexpected "
        "juxtapositions."
    ),
    'Macro': (
        "This is Macro photography. DoD is primarily about precision focus at extreme "
        "magnification, depth of field control, and lighting in tight spaces. "
        "Sharpness on the primary subject is critical. Reward rare subjects and unusual perspectives."
    ),
    'Wedding': (
        "This is Wedding photography. Emotional authenticity and decisive moment are paramount. "
        "Reward genuine emotion, storytelling, and the irreplaceable moments that define the day."
    ),
    'People': (
        "This is People photography. AQ and emotional connection are the primary signals. "
        "Reward authentic expression, connection between subject and viewer, and strong narrative."
    ),
    'default': (
        "Evaluate using genre-appropriate criteria. Reward artistic intent, "
        "technical mastery relative to the genre, and emotional resonance."
    ),
}


def get_genre_context(genre):
    return GENRE_CONTEXT.get(genre, GENRE_CONTEXT['default'])


def get_calibration_notes(genre, limit=5):
    """
    Fetch admin correction notes for this genre.
    These are injected as negative/positive examples to prevent recurring mistakes.
    """
    try:
        from models import CalibrationNote
        from flask import current_app
        with current_app.app_context():
            notes = (
                CalibrationNote.query
                .filter_by(genre=genre, is_active=True)
                .order_by(CalibrationNote.created_at.desc())
                .limit(limit)
                .all()
            )
            if not notes:
                return ''
            lines = ['\nADMIN CALIBRATION CORRECTIONS FOR THIS GENRE:']
            lines.append('These are corrections made by human judges. Learn from these mistakes.\n')
            for n in notes:
                score_info = ''
                if n.original_score and n.corrected_score:
                    score_info = f'(AI scored {n.original_score} → correct score is {n.corrected_score})'
                elif n.corrected_score:
                    score_info = f'(correct score should be {n.corrected_score})'
                lines.append(
                    f'Module: {n.module.upper()} {score_info}\n'
                    f'Correction: {n.reason}\n'
                    f'---'
                )
            return '\n'.join(lines)
    except Exception as e:
        print(f'[calibration notes] {e}')
        return ''



def get_calibration_examples(genre, limit=3):
    try:
        from models import Image as ImageModel
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
            lines.append('These are admin-verified scores. Use them as anchors.\n')
            for ex in examples:
                audit = ex.get_audit()
                lines.append(
                    f'Title: {ex.asset_name or "Untitled"}\n'
                    f'Score: {ex.score} | Tier: {ex.tier}\n'
                    f'DoD: {ex.dod_score} | Disruption: {ex.disruption_score} | '
                    f'DM: {ex.dm_score} | Wonder: {ex.wonder_score} | AQ: {ex.aq_score}\n'
                    f'Archetype: {ex.archetype}\n'
                    f'Gap Analysis: {audit.get("byline_1", "")[:200]}\n'
                    f'---'
                )
            return '\n'.join(lines)
    except Exception as e:
        print(f'[calibration examples] {e}')
        return ''


def encode_image(image_path):
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def auto_score(image_path, genre, title, photographer, subject="", location=""):
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    img_data   = encode_image(image_path)
    ext        = os.path.splitext(image_path)[1].lower()
    media_type = "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"

    calibration_block = get_calibration_examples(genre)
    correction_block  = get_calibration_notes(genre)

    prompt = SCORE_PROMPT.format(
        genre                = genre,
        photographer         = photographer,
        title                = title,
        subject              = subject or "Not specified",
        location             = location or "Not specified",
        genre_context        = get_genre_context(genre),
        calibration_examples = calibration_block,
        calibration_notes    = correction_block,
    )

    payload = {
        "model":      MODEL,
        "max_tokens": 1200,
        "temperature": 0.2,
        "system":     SYSTEM_BRIEF,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type":       "base64",
                            "media_type": media_type,
                            "data":       img_data,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }

    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
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
        raise ValueError(f"Failed to parse API response: {e}\nResponse: {text[:500]}")

    return result


def build_audit_data(result, image_obj):
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
