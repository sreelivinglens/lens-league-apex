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

# Maximum dimension sent to the API — keeps payload small and response fast
API_MAX_PX = 800

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

DoD (Depth of Difficulty):
  Score BOTH technical execution AND situational difficulty of capture.
  Situational difficulty includes: physical risk, restricted access, environmental
  hostility, subject unpredictability, timing constraints, regulatory complexity,
  and the photographer's physical presence in a demanding or dangerous situation.
  A technically competent shot taken in a war zone, extreme weather, underwater,
  or with a dangerous animal scores higher than the same shot taken safely.
  Technical execution includes: mechanical precision, sharpness where appropriate,
  exposure control, and mastery of the photographic challenge the genre demands.

  Per-genre guidance:
  Wildlife: Physical risk, access to habitat, environmental hostility, mechanical
    precision. Sharp animal subject = high DoD. Rare behaviour or dangerous proximity = maximum DoD.
  Drone: Physical difficulty of aerial operation — wind, altitude, vibration control,
    light management from elevation, regulatory complexity. Geometric patterns and
    impossible ground-level perspectives score highest.
  Street: Speed of reaction, working in chaos, difficult or hostile light conditions,
    photographing in conflict zones, crowded environments, or restricted spaces.
    Motion blur on moving subjects is acceptable and adds energy.
  Macro: Extreme precision at high magnification. Sharpness IS DoD.
  Landscapes: Patience, location access (remote or extreme terrain), weather timing,
    long-exposure control. Predawn climbs, extreme cold, difficult terrain = high DoD.
  Wedding/People: Emotional access, managing unpredictable human subjects, working
    in low light, capturing unrepeatable moments under time pressure.
  Creative: See STEP 0 above.

VD (Visual Disruption):
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

WF (Wonder Factor):
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
- Iconic Wall: score >= 9.0 requires BOTH VD (Visual Disruption) AND AQ > 8.5
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

WRITING STYLE FOR ALL TEXT FIELDS:
Write as an experienced photographer and mentor — direct, specific, no hedging.
Reference what you actually see in this specific image. No generic statements.
Never say "the image demonstrates" or "this photograph shows" — speak directly.
Examples of BAD output: "The technical execution demonstrates strong awareness of peak action."
Examples of GOOD output: "The motion-frozen wingbeat at the top of the arc is the shot — everything else in the frame supports that instant."

CRITICAL — EQUIPMENT AND EXIF ACCURACY:
The EXIF data is provided with the image. Read it carefully before writing any text.
- If the camera make/model is a smartphone (iPhone, Samsung Galaxy, Pixel, Xiaomi, OnePlus etc.) NEVER describe the capture method as "drone", "aerial vehicle", "UAV", or "shot from a drone". It is a handheld or elevated mobile shot. Only reference drone/aerial if EXIF explicitly confirms a drone camera (DJI, Autel, Parrot etc.).
- Do not assume subject matter or objects that are not clearly visible. If you see a colour boundary, describe it as a colour boundary — not a road unless you can clearly see it is a road.
- Do not identify technical flaws (lens flare, dust, noise) unless you can clearly see them. A small coloured element may be part of the scene, not a flare. Describe what you see, not what you assume.
- Never invent equipment, settings, or techniques not supported by the EXIF or the visible image.

COMPOSITION_TECHNIQUE — identify the PRIMARY compositional structure used in this image.
Return exactly one value from the list below. If two apply equally, return the more visually dominant one.
GOLDEN_SPIRAL: subject or key elements follow a Fibonacci / golden ratio spiral path
LEADING_LINES: lines (road, river, fence, shadow, corridor, gaze direction) draw the eye to the subject
DIAGONAL: dominant diagonal tension sweeps across the frame — subject or elements on a diagonal axis
RULE_OF_THIRDS: subject placed on a thirds intersection or along a thirds line
SYMMETRY: bilateral symmetry, mirror image, or strong reflection creating an axis
NEGATIVE_SPACE: subject isolated in large empty area — the empty space IS the composition
FRAME_IN_FRAME: subject enclosed or framed by a natural or architectural element within the scene
NONE: no single dominant compositional structure identifiable

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
  "composition_technique": "<GOLDEN_SPIRAL|LEADING_LINES|DIAGONAL|RULE_OF_THIRDS|SYMMETRY|NEGATIVE_SPACE|FRAME_IN_FRAME|NONE>",
  "hard_truth": "<One punchy sentence — what this image IS. Written as a photographer would say it to a peer. No hedging. Start with what makes or breaks it. Example: 'The subtraction works — white background forces the eye to the rhythm of repeated forms, but the incoming bird is a beat too early to anchor the geometry.' Never start with 'This image' or 'The photograph'.>",
  "row_technical": "<2-3 sentences. Speak directly about what you see — specific technical decisions, not categories. Name the actual technique. Example: 'High-key exposure held just below blowout — feather detail survives in the wings. Shallow depth collapses the background to white without losing subject separation.'  >",
  "row_geometric": "<2-3 sentences. Name the actual compositional structure visible in this specific image. Reference real elements. Example: 'Vertical post anchors the left third. The perched birds stack into a diagonal that pulls toward the incoming bird in the upper right — the composition is unresolved until that gap closes.'  >",
  "row_dm": "<2-3 sentences. Was this the right moment or not? Be direct. Example: 'Mid-flight approach captured cleanly. The decisive version of this shot is a half-second later when the incoming bird reaches the stack — that frame does not exist yet.'  >",
  "row_wonder": "<2-3 sentences. What is genuinely surprising or rare here, if anything? Be honest if nothing is. Example: 'Colony behaviour in high-key monochrome is uncommon — most bird photography reaches for colour and drama. The restraint is the wonder.'  >",
  "row_aq": "<2-3 sentences. What does this image feel like? Name the emotion precisely. Example: 'Serene but kinetic — stillness and motion in the same frame. The motion blur on the foreground bird creates unresolved tension against the sharp perched group.'  >",
  "byline_1": "<One sentence — what specifically holds this image from the next tier. Name the exact gap. Example: 'The incoming bird placement is slightly too high — it floats outside the geometric connection to the perched group rather than completing it.'  >",
  "byline_2": "<THE ONE IMPROVEMENT. Physical, specific, actionable. What to do differently next time — in the field or in processing. Example: 'Wait for the incoming bird to drop closer to the perched group before firing — the geometric connection that makes this composition complete is half a second away.'  >",
  "badges_g": ["<specific strength visible in this image>", "<specific strength>", "<specific strength>"],
  "badges_w": ["<specific gap in this image>", "<specific gap>", "<specific gap>"],
  "iucn_tag": "<IUCN status if applicable, else null>",
  "ai_suspicion": <float 0.0-1.0>,
  "ai_suspicion_reason": "<concise reason if ai_suspicion >= 0.5, else null>"
}}

AI DETECTION — evaluate BEFORE scoring:
Set ai_suspicion to a value between 0.0 (certainly real photograph) and 1.0 (certainly AI-generated).
Set ai_suspicion >= 0.7 if ANY of these are present:
(a) Biologically or physically impossible scene — animals that would never coexist or interact
    this way in nature (e.g. tiger lunging at baby elephant with mother present, predator and
    prey in impossible calm proximity, multiple apex predators together peacefully);
(b) Fur, feather, or skin texture too regular, symmetrical, or perfectly rendered —
    real animal fur has natural asymmetry and imperfection;
(c) Water reflections geometrically perfect despite surface disturbance from subjects;
(d) Lighting unnaturally perfect and consistent across all subjects simultaneously;
(e) Animal scale or proportions subtly wrong relative to each other or environment;
(f) AI image artifacts — unnaturally smooth transitions, background inconsistencies,
    impossible bokeh, overly sharp subjects against implausibly smooth backgrounds;
(g) Scene appears to be a composite of elements that could not be photographed together;
(h) Overall aesthetic resembles AI image generation (Midjourney/DALL-E/Firefly style).
Wildlife images with dramatic impossible animal interactions should score >= 0.85.

PEOPLE, STREET, WEDDING AND ARCHITECTURE images — additional tells:
Only apply rules (i)-(o) when the image contains human subjects or built environments.
Set ai_suspicion >= 0.7 if ANY of these are present:
(i) Human proportions subtly wrong — head-to-body ratio, limb length, hand or finger
    geometry that a real person could not have; children especially: AI frequently
    misrenders child proportions (oversized head, too-short limbs, doll-like features);
(j) Lighting physically inconsistent with the visible scene — backlit subjects
    in a colonnade or alley with shadows falling in the wrong direction; overcast street
    scenes with hard directional shadows; indoor candid with studio-quality rim lighting
    and no visible light source; single subject lit too evenly for the environment;
(k) Upscaling or interpolation artifacts — unnaturally smooth fine detail (hair strands
    merge into a single mass, fabric weave too regular, skin has no pores or sensor
    noise), transitions between subject and background too clean, no chromatic
    aberration where a real lens would produce it;
(l) B&W grain pattern is synthetic — AI grain is spatially uniform and perfectly
    distributed; real sensor or film grain has clumping, variation, and luminance
    dependency; a B&W image with perfectly even grain across shadows and highlights
    is suspicious;
(m) Background architectural or environmental details inconsistent — windows with
    wrong perspective for the building angle, repeating tiles or patterns that do not
    tile correctly, text on signs illegible or malformed, reflections in glass or
    puddles that do not match the scene geometry;
(n) Street or documentary image with a too-composed aesthetic — perfect expression,
    perfect light, and perfect background separation simultaneously in a genre where
    capturing all three at once is extremely rare; feels directed, not captured;
(o) Hands and fingers showing AI generation artifacts — fingers that merge, incorrect
    counts, unnatural smoothness at knuckles under grip tension, implausible geometry
    for the posed action; halos or luminance edges around limbs or body parts where
    they meet the background.
Street and People images where multiple tells from (i)-(o) are present should score >= 0.75.
Even if the image looks beautiful and photographic, flag AI tells honestly."""

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


def auto_score(image_path, genre, title, photographer, subject="", location=""):
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    img_data, media_type = encode_image(image_path)

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
        "model":       MODEL,
        "max_tokens":  1500,
        "temperature": 0.2,
        "system":      SYSTEM_BRIEF,
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

    response  = None
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
                print(f"[auto_score] API overloaded (529), retrying in {wait}s... (attempt {attempt+1}/5)")
                _time.sleep(wait)
                continue
            break
        except httpx.TimeoutException as e:
            last_error = e
            wait = (attempt + 1) * 15
            print(f"[auto_score] Timeout on attempt {attempt+1}/5, retrying in {wait}s...")
            _time.sleep(wait)
            continue
        except Exception as e:
            last_error = e
            print(f"[auto_score] Request error on attempt {attempt+1}/5: {e}")
            break

    if response is None:
        raise ValueError(f"All retry attempts failed. Last error: {last_error}")

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
        "asset":                image_obj.asset_name or "Untitled",
        "meta":                 f"{genre}  ·  {fmt}  ·  {subject}  ·  {location}",
        "score":                str(result.get("score", 0)),
        "tier":                 result.get("tier", "Practitioner"),
        "dec":                  result.get("archetype", "Sovereign Momentum"),
        "credit":               image_obj.photographer_name or "",
        "genre_tag":            f"{genre.upper()}  ·  {fmt.upper()}",
        "soul_bonus":           result.get("soul_bonus", False),
        "composition_technique": result.get("composition_technique", "NONE"),
        "iucn_tag":             result.get("iucn_tag"),
        "hard_truth":           result.get("hard_truth", ""),
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
