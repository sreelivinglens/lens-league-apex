"""
Apex DDI Auto-Scoring Engine
Apex DDI Engine — AI scoring for uploaded images
Returns structured JSON with all module scores, audit text, bylines, badges
"""

import base64
import io
import json
import os
import re
import time as _time
import httpx
from PIL import Image as PILImage

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL             = os.getenv("APEX_MODEL", "claude-haiku-4-5-20251001")
DETECTION_MODEL   = "claude-sonnet-4-6"   # Sonnet for AI detection — better visual reasoning

# Maximum dimension sent to the API — keeps payload small and response fast
API_MAX_PX       = 800   # Haiku DDI scoring — keeps payload small and fast
DETECTION_MAX_PX = 1600  # Sonnet detection — higher res needed to catch watermarks and text

# Detection prompt — sent to Sonnet only, focused solely on AI detection
DETECTION_PROMPT = """You are an AI image authentication specialist for a photography competition platform.
Your ONLY job is to determine whether this image is AI-generated or a real photograph.

IMPORTANT: You are examining a HIGH RESOLUTION image. Look carefully at fine details — small watermarks,
text on signs, and subtle physics errors that only appear at full resolution.

STEP 1 — CHECK THESE FIRST (highest confidence signals):

WATERMARKS & SIGNATURES (immediate high suspicion if found):
- A small 4-pointed or 8-pointed star symbol anywhere in the image — this is a Gemini AI watermark
- Any stylised logo, symbol or geometric mark in corners or edges that doesn't belong to the scene
- Faint overlaid text or symbols that appear to be from an AI generation tool

TEXT IN THE IMAGE (examine every sign, label, plate carefully):
- Read ALL text visible in the image — signs, billboards, licence plates, labels
- Count how many times the SAME text or sign appears — AI frequently duplicates signage
- Licence plates: check if the text is a valid format or gibberish/random characters
- If the same business name, sign, or text block appears more than once in the same scene → HIGH suspicion

STEP 2 — PHYSICS & ANATOMY CHECKS:

WILDLIFE & NATURE:
- Paw/hoof/claw ground contact: real paws compress and deform. AI paws hover or make impossibly clean contact
- Dust/mud/water physics: AI dust is too uniform and symmetric. Real dust is chaotic and directional
- Multi-animal contact points: check for fur interpenetration or merged body boundaries
- Shadow direction: all shadows must come from ONE consistent light source
- Animal scale/proportion between subjects

STREET & PEOPLE:
- Hands gripping objects: check for merged fingers or impossible joint angles
- Crowd backgrounds: look for repeated identical silhouettes or faces
- Clothing physics: fabric that defies gravity or motion direction
- Facial features: unnaturally smooth skin, asymmetric iris sizes

STEP 3 — GENERAL AI TELLS:
- Hyperreal perfection: impossibly smooth textures, flawless lighting with zero real-world imperfections
- Anatomical errors: extra/fused limbs, malformed extremities, merged body parts
- Background incoherence: dissolving backgrounds, impossible structures
- Over-rendered textures: fur/skin/fabric that looks painted rather than photographic

Respond ONLY with a valid JSON object — no preamble, no markdown:
{
  "ai_suspicion": <float 0.0-1.0>,
  "ai_suspicion_reason": "<concise explanation listing the specific signals detected, or null if clearly real>",
  "needs_review": <true if ai_suspicion >= 0.4, else false>,
  "detection_signals": ["<signal 1>", "<signal 2>"]
}

Scoring scale:
  0.0 — 0.39: Clearly real photograph. Natural imperfections, consistent physics, no watermarks.
  0.4  — 0.69: Uncertain — anomalies present. Warrants human review.
  0.7  — 0.84: Strong AI signals. Multiple tells present.
  0.85 — 1.0:  Almost certainly AI-generated. Watermark found, or multiple strong signals.
"""

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
{calibration_notes}

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
  "row_technical": "<2-3 sentence technical analysis>",
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


def encode_image(image_path: str):
    """
    Load image, resize to API_MAX_PX on longest side, encode as base64.
    Returns (base64_string, media_type).
    Resizing reduces payload size and API latency significantly.
    """
    img = PILImage.open(image_path).convert('RGB')
    w, h = img.size
    if max(w, h) > API_MAX_PX:
        if w >= h:
            new_w = API_MAX_PX
            new_h = int(h * API_MAX_PX / w)
        else:
            new_h = API_MAX_PX
            new_w = int(w * API_MAX_PX / h)
        img = img.resize((new_w, new_h), PILImage.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=85, optimize=True)
    buf.seek(0)
    encoded = base64.standard_b64encode(buf.read()).decode('utf-8')
    return encoded, 'image/jpeg'


def encode_image_for_detection(image_path: str):
    """
    Higher-resolution encode for Sonnet AI detection.
    Uses DETECTION_MAX_PX (1600px) to preserve watermarks, text, and fine detail
    that compress away at 800px and cause missed detections.
    """
    img = PILImage.open(image_path).convert('RGB')
    w, h = img.size
    if max(w, h) > DETECTION_MAX_PX:
        if w >= h:
            new_w = DETECTION_MAX_PX
            new_h = int(h * DETECTION_MAX_PX / w)
        else:
            new_h = DETECTION_MAX_PX
            new_w = int(w * DETECTION_MAX_PX / h)
        img = img.resize((new_w, new_h), PILImage.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=92, optimize=True)  # higher quality for detection
    buf.seek(0)
    encoded = base64.standard_b64encode(buf.read()).decode('utf-8')
    return encoded, 'image/jpeg'


def _call_api(model, system, prompt, img_data, media_type, max_tokens=512, temperature=0.1):
    """Single API call with retry logic. Returns parsed JSON dict."""
    payload = {
        "model":       model,
        "max_tokens":  max_tokens,
        "temperature": temperature,
        "system":      system,
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
    response   = None
    last_error = None
    for attempt in range(5):
        try:
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json=payload,
                timeout=90,
            )
            if response.status_code == 529:
                wait = (attempt + 1) * 20
                print(f"[{model}] overloaded (529), retrying in {wait}s... (attempt {attempt+1}/5)")
                _time.sleep(wait)
                continue
            break
        except httpx.TimeoutException as e:
            last_error = e
            wait = (attempt + 1) * 15
            print(f"[{model}] Timeout on attempt {attempt+1}/5, retrying in {wait}s...")
            _time.sleep(wait)
            continue
        except Exception as e:
            last_error = e
            print(f"[{model}] Request error on attempt {attempt+1}/5: {e}")
            break

    if response is None:
        raise ValueError(f"All retry attempts failed. Last error: {last_error}")
    if response.status_code != 200:
        raise ValueError(f"API error {response.status_code}: {response.text}")

    text = ""
    for block in response.json().get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")
    text = re.sub(r"```json|```", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse API response: {e}\nResponse: {text[:500]}")


def detect_ai(img_data, media_type):
    """
    Call 1 — Sonnet only, focused purely on AI detection.
    Returns dict with ai_suspicion, needs_review, ai_suspicion_reason, detection_signals.
    Falls back to clean result on any error so scoring can always proceed.
    """
    try:
        result = _call_api(
            model       = DETECTION_MODEL,
            system      = "You are an AI image authentication specialist. Respond only with valid JSON.",
            prompt      = DETECTION_PROMPT,
            img_data    = img_data,
            media_type  = media_type,
            max_tokens  = 512,
            temperature = 0.1,
        )
        return {
            "ai_suspicion":        float(result.get("ai_suspicion", 0.0)),
            "ai_suspicion_reason": result.get("ai_suspicion_reason") or None,
            "needs_review":        bool(result.get("needs_review", False)),
            "detection_signals":   result.get("detection_signals", []),
        }
    except Exception as e:
        print(f"[detect_ai] Detection call failed: {e} — proceeding with suspicion=0")
        return {
            "ai_suspicion":        0.0,
            "ai_suspicion_reason": None,
            "needs_review":        False,
            "detection_signals":   [],
        }


def auto_score(image_path, genre, title, photographer, subject="", location=""):
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    img_data, media_type         = encode_image(image_path)             # 800px for Haiku DDI
    det_img_data, det_media_type = encode_image_for_detection(image_path)  # 1600px for Sonnet

    # ── CALL 1: Sonnet — AI detection only ───────────────────────────────────
    detection    = detect_ai(det_img_data, det_media_type)
    ai_suspicion = detection["ai_suspicion"]
    print(f"[detect_ai] suspicion={ai_suspicion:.2f} needs_review={detection['needs_review']} "
          f"signals={detection['detection_signals']}")

    # If clearly AI-generated skip DDI scoring — return early with zeroed scores
    if ai_suspicion >= 0.7:
        return {
            "ai_suspicion":        ai_suspicion,
            "ai_suspicion_reason": detection["ai_suspicion_reason"],
            "needs_review":        True,
            "dod":        0.0, "disruption": 0.0, "dm": 0.0, "wonder": 0.0, "aq": 0.0,
            "score":      0.0, "tier": "Apprentice", "archetype": "",
            "soul_bonus": False, "judge_referral": False,
            "row_technical": "", "row_geometric": "", "row_dm": "",
            "row_wonder": "", "row_aq": "",
            "byline_1": "", "byline_2": "",
            "badges_g": [], "badges_w": [], "iucn_tag": None,
        }

    # ── CALL 2: Haiku — DDI scoring only ─────────────────────────────────────
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

    result = _call_api(
        model       = MODEL,
        system      = SYSTEM_BRIEF,
        prompt      = prompt,
        img_data    = img_data,
        media_type  = media_type,
        max_tokens  = 1500,
        temperature = 0.2,
    )

    # Merge detection results into DDI result
    result["ai_suspicion"]        = ai_suspicion
    result["ai_suspicion_reason"] = detection["ai_suspicion_reason"]
    result["needs_review"]        = detection["needs_review"]  # app.py also sets for Grandmaster

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
            ("Technical Integrity", result.get("row_technical", "")),
            ("Geometric Harmony",   result.get("row_geometric", "")),
            ("Decisive Moment",     result.get("row_dm", "")),
            ("Wonder Factor",       result.get("row_wonder", "")),
            ("AQ — Soul",           result.get("row_aq", "")),
        ],
        "byline_1":      result.get("byline_1", ""),
        "byline_2_body": result.get("byline_2", ""),
        "badges_g":      result.get("badges_g", []),
        "badges_w":      result.get("badges_w", []),
    }
