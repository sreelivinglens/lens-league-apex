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
from engine.scoring import VALID_SUBGENRES

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL             = os.getenv("APEX_MODEL", "claude-sonnet-4-6")
# Vision call uses a more capable model — Haiku misses fine detail (small fish,
# second bird in shadow). Sonnet handles this reliably. Scoring stays on Haiku.
VISION_MODEL      = os.getenv("APEX_VISION_MODEL", "claude-sonnet-4-6")

# Maximum dimension sent to the API.
# Set to 1500 to match the platform minimum upload standard (1500px short side).
# At 800px (previous value) a 2250×1500 image was downsampled to 800×533 —
# losing 64% of resolution and making small subjects (prey in bill, second bird
# in shadow, eye catchlights) invisible to the scoring model.
API_MAX_PX = 1500

SYSTEM_BRIEF = """
You are the Apex DDI Engine for Shutter League photography rating platform.

FORMULA:
LL-Score = (DoD × weight) + (Disruption × weight) + (DM × weight) + (Wonder × weight) + (AQ × weight)

GENRE WEIGHTS:
Wildlife:     DoD=22% Disruption=13% DM=28% Wonder=25% AQ=12%
Nature:       DoD=15% Disruption=13% DM=15% Wonder=35% AQ=22%
Landscape:    DoD=15% Disruption=15% DM=13% Wonder=30% AQ=27%
Street:       DoD=10% Disruption=18% DM=20% Wonder=25% AQ=27%
Wedding:      DoD=8%  Disruption=12% DM=25% Wonder=10% AQ=45%
People:       DoD=8%  Disruption=17% DM=15% Wonder=15% AQ=45%
Macro:        DoD=28% Disruption=18% DM=13% Wonder=25% AQ=16%
Creative:     DoD=15% Disruption=22% DM=13% Wonder=25% AQ=25%
Drone:        DoD=25% Disruption=18% DM=13% Wonder=28% AQ=16%
Documentary:  DoD=15% Disruption=12% DM=23% Wonder=28% AQ=22%
Fashion:      DoD=12% Disruption=22% DM=18% Wonder=22% AQ=26%

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
  Nature: Access to remote ecosystems, hostile weather conditions, patience for
    the right natural moment, underwater or extreme terrain. Technical precision
    on delicate subjects (macro flora, storm photography) = high DoD.
  Drone: Physical difficulty of aerial operation — wind, altitude, vibration control,
    light management from elevation, regulatory complexity. Geometric patterns and
    impossible ground-level perspectives score highest.
  Street: Speed of reaction, working in chaos, difficult or hostile light conditions,
    photographing in conflict zones, crowded environments, or restricted spaces.
    Motion blur on moving subjects is acceptable and adds energy.
  Macro: Extreme precision at high magnification. Sharpness IS DoD.
  Landscape: Patience, location access (remote or extreme terrain), weather timing,
    long-exposure control. Predawn climbs, extreme cold, difficult terrain = high DoD.
  Documentary: Physical access to restricted environments (hospitals, disaster zones,
    conflict areas, slums), ethical difficulty of the shot, working under time
    pressure in chaotic conditions, and the personal risk of bearing witness.
    Access that most photographers will never have = maximum DoD.
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
  The Unseen Truth. Four distinct Wonder signals — any one at high intensity scores 7.5–9.5:

  EYE WONDER: The photographer found something in the ordinary that transforms it.
  A compositional find, an accidental frame, a juxtaposition that could not have been
  planned. The cow shadow on the red wall. The barrel bath under a sign. The woman
  framed through the camel neck. The man surrounded by crowd shadows.
  The subject is not rare — the seeing is.
  Eye Wonder scores 8.0–9.0 when the compositional discovery is complete and unrepeatable.
  Eye Wonder scores 9.0–9.5 when the find is singular — the image that could only exist
  once, in that place, in that light, at that instant. International award-winning
  compositional finds (WSPA, Sony World Photography, similar) score 9.0–9.5.
  DO NOT default to the bottom of this range. Score what the image actually achieved.

  ACCESS WONDER: The photographer was somewhere or trusted by someone that most
  photographers never reach. Working inside a toxic kiln with labourers. A close portrait
  of a stranger who allowed the camera. Inside a restricted religious community.
  A delivery room. The wonder is in the access, not the subject rarity.
  Access Wonder scores 7.5–8.5 depending on the difficulty of the access.
  Access Wonder scores 8.5–9.5 when the access is extraordinary — inside a war zone,
  inside a birth, inside a community that never lets cameras in.

  CULTURAL WONDER: The image shows the viewer a world, a community, or a way of life
  they cannot otherwise enter. Cultural Wonder scores 7.0–8.5 depending on specificity.
  Cultural Wonder scores 8.5–9.0 when the image documents a world that is disappearing
  or inaccessible to almost all viewers.

  EMOTIONAL WONDER: The decisive moment captures not just the geometric or behavioural
  peak but the emotional truth of what is happening. This is the highest Wonder signal.
  The loneliness in a silhouette at dusk. The defiance in a face under a smoky sky.
  The tenderness in a mother's gesture. The resignation of daily life in hardship.
  The joy that cannot be contained. When the image makes the viewer feel something
  specific and nameable — not "powerful" but lonely, defiant, joyful, tender, resigned,
  awed, unsettled — that is Emotional Wonder.
  Emotional Wonder scores 8.5–9.5 when the emotion is specific, genuine, and undeniable.
  Emotional Wonder scores 9.0–9.5 when the decisive moment and the emotional truth
  coincide simultaneously — the geometry AND the feeling, captured in one frame.
  CRITICAL: Name the specific emotion. "Powerful" is not an emotion. "Lonely" is.
  "Defiant" is. "Tender" is. Score accordingly.

  FOR WILDLIFE AND NATURE: Rare behaviour, scientific significance, and perspectives
  the viewer will never witness score highest. Add Emotional Wonder when the image
  creates felt connection between viewer and subject.
  For Drone: perspectives impossible from ground = high Wonder.
  For Creative: revealing the invisible + lingering resonance = high Wonder.

AQ (Affective Quotient):
  The specific feeling the image creates in a viewer. NOT technical quality —
  technical quality lives in DoD.

  CRITICAL: Name the specific emotion or feeling the image creates.
  Score the precision and intensity of that feeling.
  If no specific emotion is identifiable, AQ cannot exceed 7.5 regardless
  of technical quality.

  AQ SCORING SCALE:
  9.0–10.0: A specific, powerful emotion that is undeniable and lingers after
    looking away. The viewer cannot remain neutral. The feeling is singular.
    Award-winning work where the emotional register is the primary achievement.
    DO NOT reserve this range only for People/Wedding — minimalist, landscape,
    and street images can score 9.0+ AQ when the emotional register is complete.
  8.0–8.9:  A clear, specific emotion that lands. The viewer feels something
    definite — loneliness, joy, unease, awe, tenderness, defiance.
  7.0–7.9:  Emotional content present but not fully resolved. The image suggests
    a feeling without fully delivering it. Technically accomplished but emotionally
    incomplete.
  6.0–6.9:  Minimal emotional content. Technically competent but emotionally neutral.
    The viewer admires the craft without feeling anything.
  Below 6.0: No emotional content. Pure documentation or failed execution.
  CRITICAL: DO NOT default to the middle of any range. Score what the image
  actually achieves. An image that genuinely creates suspension, void, stillness
  as a complete emotional statement scores AQ 9.0+.

  PER-GENRE EMOTIONAL VOCABULARY — name the specific emotion from this list
  or use your own specific language:
  Street/Documentary: loneliness, defiance, resignation, solidarity, isolation,
    tenderness, urgency, despair, joy, dignity, invisibility, connection, alienation
  People/Wedding: love, grief, joy, tenderness, pride, relief, overwhelm,
    vulnerability, strength, intimacy, presence, absence
  Wildlife/Nature: awe, reverence, fragility, abundance, power, vulnerability,
    strangeness, belonging, threat
  Landscape: presence (the feeling of being somewhere), vastness, solitude,
    peace, unease, transcendence, melancholy, wonder
  Creative/Minimalist: stillness, absence, boundary, resonance, void, clarity,
    suspension, the space between things
  Fashion: tension, unease, desire, power, otherness, beauty as threat
  Macro/Drone: revelation, scale-shift, insignificance, hidden order, the sublime

APEX LAYER RULES:
- Soul Bonus: AQ >= 8.0 removes ALL technical penalties
- Humanity Check: AQ < 4.0 adds -1.5 penalty to AQ
- Iconic Wall: score >= 9.0 requires at least TWO dimensions above 8.5,
  AND Wonder >= 8.5 OR AQ >= 8.5 (emotional content must be present)
- Plateau Penalty: DoD >= 9.5 + Disruption < 5.0 caps at 7.9
- Identity Cap: >85% similarity to known winner caps at 6.0
- 10.0 never awarded

TIERS: Rookie 0-4.0 | Shooter 4.0-5.0 | Contender 5.0-6.0 | Craftsman 6.0-7.0 | Maverick 7.0-8.0 | Master 8.0-9.0 | Grandmaster 9.0-9.7 | Legend 9.7-10.0

ARCHETYPES: Sadness/Forlorn, Hope/Joy, Tension/Dread, Wonder/Transcendence,
Resilient Forlorn, Sovereign Momentum, Compressed Tension, Joyful Disruption,
Forlorn Transcendence, Chromatic Transcendence, Tender Sovereignty, Primal Dread

CALIBRATION NOTES:
- A technically imperfect image with high emotional truth scores HIGHER
  than a technically perfect but emotionally empty image
- Multiple reflections = compositional complexity = Disruption boost
- Soul Bonus (AQ >= 8.0) removes technical penalties — apply it
- For Creative and technique-detected images: TECHNIQUE WINS
- Award-winning images should reach Grandmaster (9.0+) when Wonder and AQ
  both reflect the genuine emotional achievement of the work
- DO NOT default to the bottom or middle of any scoring range. A range of
  8.0–9.5 means some images score 8.0 and some score 9.5 — evaluate honestly.
- WSPA Photographer of the Year, Sony World Photography, and equivalent
  international award-winning images score 9.0+ in the correct genre.

Respond ONLY with a valid JSON object. No preamble, no markdown, no explanation outside the JSON.
"""

SCORE_PROMPT = """Analyse this photograph using the Apex DDI Engine.

Genre: {genre}
Photographer: {photographer}
Title: {title}
Subject: {subject}
Location: {location}

MANDATORY STEP — SCENE ANALYSIS (complete this before any scoring):
Before applying any rubric, examine the full image carefully and identify:
1. ALL subjects visible in the frame — including background, shadow areas, and periphery.
   Do not stop at the most obvious subject. Scan the entire frame.
2. For each subject: what is it doing? Is it in motion, interacting with another subject,
   carrying prey, displaying, fighting, feeding, or in contact with another animal?
3. If the image title or subject field names a behavioural act (fight, catch, predation,
   display, courtship), actively search for evidence of that act in the image.
   If evidence is present but obscured (shadow, underexposure, partial crop), note it.
   If evidence is genuinely absent, note that too — but do not default to "generic motion"
   without first scanning all areas of the frame.
4. Identify any prey, target, or secondary subject — fish in bill, animal in contact,
   rival bird, competing male. These are decisive moment signals, not background elements.
5. State explicitly: what is the behavioural act in progress, and is the decisive moment
   the peak of that act or a generic motion frame?

This scene analysis MUST be reflected in your DM and Wonder scores and text.
If you identify prey, a second subject in conflict, or a specific behavioural act,
score the DM and Wonder relative to THAT act — not relative to generic motion.
A catch freeze with prey visible scores higher DM than a takeoff.
Two birds in contact scores higher Wonder than one bird in flight.

GENRE CONTEXT: {genre_context}

{scene_context}
{calibration_examples}
{calibration_notes}

MANDATORY: If genre is 'Creative' — apply STEP 0 override immediately.
Sharpness is never penalised. Score DoD on technique difficulty.
Set judge_referral=true if score >= 7.0 or technique is exceptional.

For all other genres: check for intentional motion blur before applying
genre rules (STEP 1). If detected, technique overrides genre DoD criteria.

Score all five modules. Apply all Apex layer rules. Calculate final weighted score.

WRITING RULES FOR ALL TEXT FIELDS — NON-NEGOTIABLE:
- NEVER describe what is visible in the image. The photographer knows what they shot.
- NEVER open with observation. Open with the creative truth, the win, or the direction.
- Write as an award-winning photographer talking to a peer — direct, generous, specific.
- The goal is not to find fault. The goal is to help the photographer understand what
  they made and where it could go next.
- If a field has no actionable content, return null — do not fill space.
- UNCERTAIN SUBJECT RULE: If the scene description flags any element as uncertain or
  unidentified, do NOT reference it in any text field. A wrong identification is worse than null.
- BANNED phrases: "the image demonstrates", "this photograph shows", "the composition
  features", "the subject is positioned", "the technique showcases", "the exposure
  captures", "the scene reveals", "the frame contains".

SOUL BONUS IMAGES (soul_bonus = true OR score >= 7.5):
- This image worked. The mentor job is to name exactly what made it work, then offer
  one creative direction that makes the next image untouchable.
- hard_truth: open with what this image IS and why it landed. Not what it missed.
- mentor_technical: name the specific technical DECISION that served the image.
  Not a gap. The choice that made it work.
- mentor_moment: confirm this was the right frame and say exactly why this instant.
  Do not suggest the frame was wrong.
- mentor_next: ONE creative direction — wider, closer, different light, different lens,
  processing transformation — framed as possibility, not correction. Example: "Go back
  with a 50mm and shoot just the faces — let the geometry fall away and it becomes
  entirely about what is in his eyes." Not "shift right six inches."
- byline_1: on Soul Bonus images, name what the NEXT image in this scene needs —
  not a flaw in this image.
- NEVER tell a Soul Bonus photographer to reposition as if the composition failed.
- NEVER give positional corrections (shift right, move left, six inches) as the
  primary recommendation on a high-scoring image.

ALL IMAGES — CREATIVE DIRECTION REQUIREMENT:
Before writing mentor_next, consider these creative alternatives and name the
strongest one that would most transform this specific image:
  WIDER — what context does the scene gain? Does the story become larger?
  CLOSER — what happens if you eliminate everything except the essential element?
  DIFFERENT MOMENT — was there a stronger frame before or after?
  MONOCHROME / COLOUR SWITCH — what does the conversion do to the emotion?
  BLUR AS INTENT — shallow depth or motion blur as the creative statement
  SEQUENCE THINKING — what does the next frame in this series need to be?
  PROCESSING TRANSFORMATION — dark print, high contrast, bleached highlights —
    what register serves the subject truth?
Pick ONE direction and name it specifically in mentor_next.
Technical fixes (lift shadows, burn corners) go in edit_base only.
Creative vision goes in mentor_next.

LOWER-SCORING IMAGES (score < 6.0):
- Name the primary gap clearly and specifically.
- Still offer one creative direction — what COULD this image become?
- Tone is constructive peer, not auditor. Respect the attempt and redirect.

CRITICAL — EQUIPMENT AND EXIF ACCURACY:
The EXIF data is provided with the image. Read it carefully before writing any text.
- If the camera is a smartphone NEVER describe it as drone/aerial/UAV.
- Do not identify technical flaws (lens flare, dust, noise) unless clearly visible.
- Never invent equipment or techniques not supported by EXIF or the image.

COMPOSITION_TECHNIQUE — identify the PRIMARY compositional structure:
GOLDEN_SPIRAL | LEADING_LINES | DIAGONAL | RULE_OF_THIRDS | SYMMETRY |
NEGATIVE_SPACE | FRAME_IN_FRAME | NONE

Return this exact JSON structure:
{{
  "dod": <float 0-10>,
  "disruption": <float 0-10>,
  "dm": <float 0-10>,
  "wonder": <float 0-10>,
  "aq": <float 0-10>,
  "score": <float>,
  "tier": "<Apprentice|Shooter|Contender|Craftsman|Maverick|Master|Grandmaster|Legend>",
  "archetype": "<archetype name>",
  "soul_bonus": <true|false>,
  "judge_referral": <true if Creative genre AND score >= 7.0 OR exceptional technique, else false>,
  "composition_technique": "<GOLDEN_SPIRAL|LEADING_LINES|DIAGONAL|RULE_OF_THIRDS|SYMMETRY|NEGATIVE_SPACE|FRAME_IN_FRAME|NONE>",
  "hard_truth": "<ONE sentence. The creative truth of this image. For high-scoring images: what it achieved and why it landed. For lower-scoring images: the primary gap or missed opportunity. Never open with description. Never start with This image or The photograph. Soul Bonus examples: 'Access wonder earned — you were inside a space most photographers never enter and the direct gaze confirmed it.' / 'The geometry and the confrontation are both present and both working.' Lower score examples: 'Technically clean but the moment passed before the shutter.' / 'The geometry is there but the decisive moment is not.'>",
  "mentor_technical": "<ONE sentence. For high-scoring images: name the specific technical DECISION that served the image — the choice that made it work. For lower-scoring images: name the gap and what it cost. Return null if no actionable point. Soul Bonus example: 'Exposure held shadow detail on the faces while keeping the fabric texture readable — the harder call in mixed shelter light.' Lower score example: 'Exposure pushed half a stop too bright — the highlight detail is gone and cannot be recovered.'>",
  "mentor_moment": "<ONE sentence. Was this the right frame? For Soul Bonus: confirm it was right and say exactly why this instant. For lower scores: name the specific frame that was the shot if this was not it. Return null if moment is irrelevant to genre. Soul Bonus example: 'The center figure holds the gaze while the others rest — half a second later he looks away and the confrontational tension is gone.' Lower score example: 'The bill has cleared the water here — the shot was the entry, when the spray was still rising.'>",
  "mentor_next": "<TWO sentences MAX. First sentence: ONE creative direction — wider, closer, different lens, different moment, processing transformation. Name it specifically. For Soul Bonus: frame as possibility not correction. For lower scores: redirect the creative energy. Second sentence: one processing direction that changes the emotional register. Examples: 'Go back with a 50mm and shoot just the faces — let the geometry disappear and it becomes entirely about what is in his eyes.' / 'A very dark print — push the blacks until the shelter disappears and only the faces remain in darkness — changes the register from documentary to elemental.' NEVER give positional corrections (shift right, move left) as the primary recommendation on high-scoring images.>",
  "byline_1": "<ONE sentence. For Soul Bonus images: what does the NEXT image in this scene or series need — not a flaw in this image, but the frame that completes the story. For lower-scoring images: the specific gap holding this image from the next tier. Never describe what is visible. Soul Bonus example: 'The next frame is the portrait — just his face, close, the environment gone.' Lower score example: 'The incoming bird floats outside the geometric connection — drop it to the lower third and the composition locks.'>",
  "byline_2": "<THE ONE CREATIVE INVITATION. One specific imaginable next move — in the field or in processing — framed as possibility not correction. Examples: 'Shoot this scene again at dusk when the fabric catches the last light — the faces go warm against a cooler background and the claustrophobia becomes beauty.' / 'Shoot this at golden hour from the ridge east — low side-light separates the valley without monochrome.' Never use generic advice.>",
  "badges_g": ["<specific creative or technical strength in this image>", "<specific strength>", "<specific strength>"],
  "badges_w": ["<specific gap or missed opportunity>", "<specific gap>", "<specific gap>"],
  "iucn_tag": "<IUCN status if applicable, else null>",
  "ai_suspicion": <float 0.0-1.0>,
  "ai_suspicion_reason": "<concise reason if ai_suspicion >= 0.5, else null>",
  "species_id": "<For Wildlife and Nature genres only: precise common name from scene description. Null for all other genres.>",
  "edit_base":     "<BASE EDITS — post-processing only. Specific technical adjustments: local exposure, dodging/burning, colour grading within the original palette. Tool-specific. 1-2 sentences.>",
  "edit_creative": "<CREATIVE EDITS — artistic transformation. What processing would change the emotional register of this image — not just correct it? 1-2 sentences.>",
  "genre_suggestion": "<GENRE ROUTING INSIGHT. If the scoring pattern strongly suggests this image would score significantly higher in a different genre or sub-genre, populate this field. Otherwise null. Trigger conditions: (1) Wildlife filed, DoD < 5.0, AQ > 7.0, no behavioural act detected — suggest Creative Minimalist or Creative Graphic. (2) Wildlife or Nature filed, Disruption > 7.0, Wonder < 5.5 — suggest Creative. (3) Street filed, no human detected — suggest Documentary or Creative. (4) People filed, Wonder > 7.5, AQ < 6.5 — suggest Documentary. (5) Creative filed with sub-genre 'other' or 'fineart' or 'graphic', and the image has a single recognisable subject reduced to essential form with strong negative space — suggest Creative Minimalist. (6) Creative filed with sub-genre 'other' and AQ > 8.5 — the image has a specific emotional register that a named sub-genre would score more accurately — suggest the most appropriate Creative sub-genre. (7) Any genre where the image scores primarily on compositional form rather than the genre rubric criteria. Format: {{suggested_genre: string, suggested_subgenre: string, reason: string (one sentence, creative and specific — not clinical), score_note: string (e.g. current score vs estimated score under suggested genre)}}. Example: {{suggested_genre: 'Creative', suggested_subgenre: 'creative_minimalist', reason: 'The image scores on tonal relationship and geometric reduction — not on wildlife behaviour — and would be evaluated on its actual creative achievement under Creative Minimalist.', score_note: 'Current: 5.30 — estimated under Creative Minimalist: 8.0–8.5'}}>"
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
        "exposure, layered blur patterns, atmospheric mosaics, aerial abstract, and any image where artistic or "
        "technical execution is the primary creative statement. "
        "Sharpness is NEVER penalised when absent. Sharpness IS rewarded when present as it "
        "demonstrates simultaneous technical and artistic control (highest DoD). "
        "Pure abstract/mosaic/atmospheric work can score equally high or higher on Disruption and Wonder. "
        "Refer to STEP 0 for full DoD scoring guide.\n\n"
        "CRITICAL FOR CREATIVE GENRE — ABSTRACTION FIRST:\n"
        "When the primary subject is geometric pattern, texture, colour field, or aerial abstraction, "
        "DO NOT attempt to identify incidental small objects in the frame as wildlife or animals unless "
        "they are unambiguously and clearly identifiable at full resolution. A small white or light shape "
        "in an aerial abstract is likely a feather, debris, boat, vehicle, or other object — NOT a bird. "
        "If you cannot confirm the identity of a small object with certainty, treat it as an unidentified "
        "compositional element and describe only its geometric role (scale reference, anchor point, etc). "
        "NEVER name it as a specific animal or wildlife subject. Score DM on the compositional decision "
        "of including it — not on any assumed behavioural moment."
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
        "This is Wildlife photography.\n\n"
        "BEFORE SCORING — identify the behavioural act:\n"
        "Scan the full frame including shadow areas and periphery. Identify every subject "
        "present. For each subject, determine: what is it doing? Is prey visible? Is a second "
        "subject present? Is a behavioural act (predation, conflict, display, feeding, courtship) "
        "in progress? If the image title names a behaviour, actively search for evidence of it. "
        "Do not default to 'generic motion' without first scanning all areas of the frame.\n\n"
        "DoD: Score sharpness, focus accuracy, and exposure in challenging conditions. "
        "A dark subject against bright water or backlit sky is a known exposure challenge — "
        "penalise if the subject is lost to silhouette when detail was the story. "
        "Rare behaviour, dangerous proximity, or extreme environmental conditions raise DoD. "
        "Intentional panning blur on moving subjects is acceptable technique.\n\n"
        "DM: Score relative to the behavioural act identified above — not relative to generic motion. "
        "A catch freeze with prey visible scores higher than a takeoff. "
        "Two subjects in contact scores higher than one subject in flight. "
        "The decisive moment is the peak completion of the identified act — "
        "a half-second either side produces a lesser image.\n\n"
        "WF: Score behavioural rarity explicitly. Common behaviour in ordinary conditions scores low. "
        "Rare species, rare behavioural interactions, prey visible, multiple subjects in conflict, "
        "or scientifically significant documentation scores high. "
        "The wonder is in what the image shows that most humans will never witness in person."
    ),
    'Landscapes': (
        "This is Landscape photography. Long-exposure blur on water, clouds, or moving elements "
        "is deliberate technique and scores HIGH on DoD and Disruption. "
        "Reward light quality, compositional patience, and environmental storytelling."
    ),
    'Landscape': (
        "This is Landscape photography. The subject is a place — land, sea, sky, or the "
        "relationship between them. Long-exposure blur on water, clouds, or moving elements "
        "is deliberate technique and scores HIGH on DoD and Disruption.\n\n"
        "DoD: Score location access (remote terrain, extreme weather, predawn climbs), "
        "patience for the right light, and technical precision of long-exposure control.\n\n"
        "DM: Score the peak of the environmental alignment — the exact moment light, "
        "atmosphere, and composition resolve into their strongest statement. "
        "A landscape DM is the frame where waiting paid off.\n\n"
        "Wonder: Score the revelation of place — does this image show the viewer somewhere "
        "they have never been, or a familiar place in a way they have never seen it?\n\n"
        "AQ: Reward tonal harmony and colour temperature control. Restraint is rewarded — "
        "over-processing is a penalty."
    ),
    'Street': (
        "This is Street photography. The photographer was present and captured something "
        "real — a face, a moment, a condition, a place with life in it.\n\n"
        "DoD: Score speed of reaction, working in chaos, difficult or hostile light, "
        "photographing in restricted or culturally specific environments, and the "
        "physical act of being present in a demanding situation. Motion blur on moving "
        "subjects is acceptable and often enhances energy.\n\n"
        "DM: Score the unrepeatable instant — the precise frame where multiple visual "
        "variables (expression, gesture, light, background alignment) peak simultaneously. "
        "Reward layered compositions, reflections, shadows, and unexpected juxtapositions.\n\n"
        "Wonder: Street Wonder operates on three signals — score whichever is strongest:\n"
        "  EYE WONDER: The compositional find. Something was there and invisible until "
        "the camera saw it — a shadow theatre, an accidental frame, a juxtaposition that "
        "could not have been planned. Score 8.0–9.0 when the discovery is complete.\n"
        "  ACCESS WONDER: The photographer was somewhere most photographers never go, "
        "or trusted by a community that does not trust cameras. Score 7.5–8.5.\n"
        "  CULTURAL WONDER: The image shows a world, community, or way of life most "
        "viewers cannot enter. Score 7.0–8.5 based on cultural specificity and depth.\n"
        "DO NOT score Wonder on subject rarity — a bus terminal, a market, a street "
        "corner are not rare. The photographer's eye IS the wonder in street photography.\n\n"
        "AQ: Reward images where technical choices serve the truth of the moment. "
        "Grain, available light, and imperfect focus are not penalties when they serve the image."
    ),
    'Macro': (
        "This is Macro photography. The subject fills the frame at extreme magnification — "
        "the technique of revelation is the genre's defining characteristic. Subject type "
        "is secondary: a pen nib, a cloth fibre, an insect eye, a water droplet, or a "
        "crystal are all equally valid Macro subjects.\n\n"
        "DoD: Precision at high magnification IS the DoD. Score focus accuracy on the "
        "primary plane, depth of field control, lighting that reveals surface structure "
        "without harsh specular reflections, and stability at extreme magnification. "
        "Handheld field macro in challenging conditions scores higher than controlled "
        "studio macro. Sub-genre context modifies this where relevant (living subjects "
        "add behavioural timing difficulty).\n\n"
        "DM: Score the compositional decision — the exact angle, light position, and "
        "focal plane chosen. The decisive moment in Macro is the moment of maximum "
        "structural revelation — when the subject's hidden geometry, texture, or form "
        "is most completely exposed.\n\n"
        "Wonder: Score the revelation of the invisible. Macro photography's fundamental "
        "value is showing the viewer a world that exists but cannot be seen at normal "
        "scale. A pen nib revealing precision engineering at 10x magnification, a cloth "
        "fibre showing individual thread structure, a water droplet showing refracted "
        "landscape inside it — these are all legitimate Wonder scores. "
        "CRITICAL: Do NOT score man-made object Wonder by rarity or ecological significance. "
        "Score it by the degree to which the image changes how the viewer understands "
        "the object. Does this image reveal something about the subject that was "
        "invisible before the photograph? That is the Wonder question for Macro.\n\n"
        "AQ: Score the rendering quality of the revealed detail — tonal separation "
        "in the subject, background separation that does not fight the main subject, "
        "and light quality that serves the structure being revealed."
    ),
    'Wedding': (
        "This is Wedding photography. Emotional authenticity and decisive moment are paramount. "
        "Reward genuine emotion, storytelling, and the irreplaceable moments that define the day."
    ),
    'People': (
        "This is People photography. AQ and emotional connection are the primary signals. "
        "Reward authentic expression, connection between subject and viewer, and strong narrative."
    ),
    'Nature': (
        "This is Nature photography. The subject is the living natural world beyond animals "
        "in behaviour — plants, fungi, ecosystems, weather phenomena, rivers, forests, "
        "coral, night sky, and natural processes. The photograph reveals something about "
        "the natural world that the casual eye cannot see.\n\n"
        "DoD: Score access to remote or hostile environments, patience for the right natural "
        "moment, technical precision on delicate or ephemeral subjects, and physical challenge "
        "of the environment (extreme cold, heat, rain, depth, darkness).\n\n"
        "DM: Score the moment of natural peak — spore dispersal, lightning strike, fog "
        "rolling in, first light on dew. Nature DM rewards the photographer who understood "
        "the natural process well enough to anticipate its peak.\n\n"
        "Wonder: PRIMARY dimension for Nature (30% weight). Score the degree to which the "
        "image reveals something scientifically or visually significant about the natural "
        "world. Bioluminescent fungi, rare botanical specimens, weather phenomena at their "
        "most extreme, ecosystems under threat — the wonder is showing the viewer something "
        "real that most humans will never witness.\n\n"
        "AQ: Reward technical decisions that serve the natural truth — sharp where sharpness "
        "reveals structure, atmospheric where softness serves the subject."
    ),
    'Fashion': (
        "This is Fashion photography — covering editorial, conceptual, studio, "
        "and beauty work where the image is a directed creative act.\n\n"
        "DoD: Score concept development and art direction complexity, location or "
        "studio production demands, the technical precision of executing a directed "
        "concept (skin rendering against dark backgrounds, costume and environment "
        "alignment, lighting design), and any physical access challenge. "
        "A conceptual art-historical reference executed at this level requires "
        "significant intellectual and production work — score it.\n\n"
        "DM: Score the moment within the directed setup where concept, body geometry, "
        "light, and environment align simultaneously into their strongest statement. "
        "Fashion DM is not reactive — it is the exact frame where the photographer's "
        "vision is most completely realised. The image that could only have been made "
        "in that specific instant of that specific setup.\n\n"
        "Disruption: Score the conceptual statement. Does this image break from "
        "convention in its genre? Art historical references, unexpected environments, "
        "backs-to-camera, unconventional framing, temporal duality — reward ideas "
        "that the viewer has not seen in this form before.\n\n"
        "Wonder: Score the world the image creates. Does it stop the viewer? "
        "Does it make the viewer feel they have entered a complete, fully realised "
        "visual world? Conceptual depth — the Old Masters portrait with modern choker, "
        "the desert landscape that collapses scale — scores Wonder 8.0–9.0 when the "
        "concept is fully executed.\n\n"
        "AQ: Equal weight to Disruption and Wonder. Fashion AQ scores the emotional "
        "and aesthetic tone the image creates — the precise feeling it produces. "
        "Technically clean, tonally controlled, emotionally specific."
    ),
    'Documentary': (
        "This is Documentary photography. The photographer witnessed something — an event, "
        "a condition, or a story — and the image is evidence of that witness.\n\n"
        "DoD: Score access difficulty — hospitals, disaster zones, conflict areas, slums, "
        "delivery rooms. Trust, risk, and often personal danger are required. "
        "Access that most photographers will never have = maximum DoD. "
        "Chaotic, dark, emotionally charged environments with no control over light or "
        "position raise DoD significantly.\n\n"
        "DM: Score the unrepeatable moment that makes the condition undeniable. "
        "A technically imperfect image that captures the truth of a moment scores "
        "higher DM than a technically perfect image of a lesser moment. "
        "The decisive moment in documentary work is the frame that carries the full "
        "weight of what is happening.\n\n"
        "Wonder: Score significance — not visual beauty, but the image's power to change "
        "how the viewer understands something. Does this make the viewer understand a "
        "reality they could not ignore? Images that document realities most people choose "
        "not to see score highest.\n\n"
        "AQ: Weight LOW (10%). Truth matters more than polish. Over-processing documentary "
        "work aestheticises suffering and weakens the message. Penalise heavy post-processing "
        "that removes the rawness of the moment. The best documentary photography is "
        "technically honest."
    ),
    'default': (
        "Evaluate using genre-appropriate criteria. Reward artistic intent, "
        "technical mastery relative to the genre, and emotional resonance."
    ),
}


# ── People sub-genre context blocks ───────────────────────────────────────────
# Injected into the scoring prompt when sub_genre is provided for a People image.
# Each block replaces the flat People genre_context with sub-type-specific rubric
# guidance for DM, DoD, and WF — the three dimensions most affected by sub-type.
#
# CRITICAL DESIGN NOTES:
# - AQ weights and rubric are unchanged across sub-types (emotional resonance is
#   universal — the People AQ=0.40 weight applies regardless of sub-type)
# - VD (Visual Disruption) rubric is unchanged — composition is composition
# - Weights in scoring.py are NOT changed — only rubric criteria text changes
# - The sub-type block REPLACES the generic People genre_context in the prompt

PEOPLE_SUBGENRE_CONTEXT = {
    'portrait_posed': (
        "This is People photography — sub-type: PORTRAIT (POSED / STUDIO).\n"
        "The subject is collaborating with the photographer. Setup is deliberate. "
        "Evaluate by the standards of intentional portraiture, not candid photography.\n\n"
        "DoD: Score the emotional access and technical precision the setup demanded. "
        "Controlled light rendering, depth management between subject layers, and "
        "skin or fabric detail are primary DoD signals. A studio environment does not "
        "reduce DoD — the difficulty is in achieving genuine revelation under control.\n\n"
        "DM: Score the moment the subject reveals themselves — when expression, posture, "
        "and gaze align into a single honest frame. Stillness is NOT a penalty. "
        "A posed portrait earns a high DM score when the subject's inner state is fully "
        "present in that specific frame. Being aware of the camera is EXPECTED and does "
        "NOT reduce the DM score. Score whether the photographer found the right moment "
        "within the session — not whether the subject was unaware.\n\n"
        "WF: Score concept and styling originality. What elevates this above competent "
        "execution? Unexpected light, cultural depth, an expression that surprises — "
        "the wonder is in the controlled setup revealing something uncontrolled."
    ),
    'portrait_cultural': (
        "This is People photography — sub-type: PORTRAIT (CULTURAL / DOCUMENTARY).\n"
        "The subject exists in their cultural, religious, or ceremonial context. "
        "Environmental authenticity and the subject's relationship to that context "
        "are as important as the subject itself.\n\n"
        "DoD: Score garment detail, contextual environmental elements, and cultural "
        "signifiers rendered with accuracy and respect. Physical access to the context "
        "and the trust required to photograph in it are valid DoD signals.\n\n"
        "DM: Score authenticity of presence — how fully the subject inhabits their "
        "cultural environment in this specific frame. Dignity and self-possession are "
        "STRENGTHS. The subject being aware of the camera is NOT a deduction. "
        "The decisive moment is the one where subject and environment are in complete accord.\n\n"
        "WF: CULTURAL WONDER is the primary Wonder signal for this sub-type. Score on "
        "three dimensions simultaneously:\n"
        "1. WORLD BEHIND THE FACE: The subject's face is the entry point — the world "
        "visible behind and around them is the Wonder. A face surrounded by cultural "
        "signifiers that most viewers will never encounter in person scores Wonder 7.5–8.5. "
        "The more specific the cultural context (not 'Indian woman' but 'Rajasthani bride "
        "at a specific ceremonial moment'), the higher the Wonder score.\n"
        "2. ACCESS DEPTH: Did this image require genuine relationship and trust to make? "
        "A photographer who embedded themselves in a community for weeks scores higher "
        "Access Wonder than a tourist who pointed a camera at a colourful ceremony.\n"
        "3. SIGNIFICANCE OF THE ENCOUNTER: Does this image communicate something about "
        "a community's way of life that would be lost without photography? "
        "Traditions under threat, communities shrinking, ways of life disappearing — "
        "documentation of these carries additional Wonder weight.\n"
        "CRITICAL: Do NOT score Wonder low because the image is a 'posed' portrait or "
        "because the subject is aware of the camera. Cultural portrait Wonder is in the "
        "world the image shows, not in the spontaneity of capture."
    ),
    'portrait_candid': (
        "This is People photography — sub-type: PORTRAIT (CANDID / STREET).\n"
        "The defining quality is the unguarded moment — subject unaware, or a stranger "
        "who consented to a moment of eye contact in a public space. "
        "Timing and physical proximity are the primary criteria.\n\n"
        "DoD: Score sharpness on a potentially moving subject and background separation "
        "in uncontrolled ambient light. CRITICAL: Working at close portrait distance "
        "with a stranger in a public space — no studio, no relationship, no control — "
        "is a distinct DoD signal. The physical act of approaching a stranger and earning "
        "or capturing that moment scores DoD 6.5–7.5. A weathered face in a working-class "
        "environment, a person in a restricted cultural space, a subject in psychological "
        "distress who allowed the camera — all raise DoD significantly.\n\n"
        "DM: Score the unrepeatable instant where expression, gesture, and gaze align. "
        "A direct gaze from a stranger who held eye contact for one moment is as valid "
        "a decisive moment as a caught expression. Score the frame that could not have "
        "been made a second earlier or later.\n\n"
        "WF: Score on ACCESS WONDER and EYE WONDER:\n"
        "ACCESS WONDER: A direct, unguarded gaze from a stranger photographed at close "
        "range scores Wonder 7.0–8.5. The access required to get this close and the "
        "subject's willingness to be seen cannot be replicated in a studio. "
        "The more visible the subject's life in their face and environment, the higher.\n"
        "EYE WONDER: A background element, light condition, or juxtaposition that "
        "transforms the portrait into something larger than a face.\n"
        "DO NOT score Wonder low because the subject is ordinary or the environment familiar."
    ),
    'lifestyle': (
        "This is People photography — sub-type: LIFESTYLE / EDITORIAL.\n"
        "Narrative and aspirational quality are the primary signals. The image may be "
        "directed or styled but communicates a world, not just a subject.\n\n"
        "DoD: Score environmental detail, prop and location specificity, and overall "
        "production quality. The effort and access required to construct or find "
        "the scene are valid DoD signals.\n\n"
        "DM: Score the narrative peak — the single frame that implies the full story "
        "without a caption. A lifestyle image with high DM needs no explanation; "
        "the moment selected does all the communicative work.\n\n"
        "WF: Score aspirational pull and visual world-building. Does the image create "
        "a world the viewer wants to enter? Is the visual language specific and original, "
        "or generic? Wonder here is the sense of a fully realised visual world."
    ),
    'lifestyle_intimate': (
        "This is People photography — sub-type: LIFESTYLE (INTIMATE / DIARY).\n"
        "Diary photography, domestic documentary, the private world shared willingly. "
        "This sub-type covers intimate access to someone's private life — bedroom, "
        "domestic space, personal moment. In the tradition of Nan Goldin and Larry Clark.\n\n"
        "DoD: Score TRUST AND ACCESS — the primary DoD signal is that the photographer "
        "was given access to a private world. This is NOT technical difficulty — it is "
        "relationship difficulty. The hardest thing in photography is being trusted with "
        "a camera in an intimate space. Score DoD 7.5–8.5 when the access is genuine "
        "and the intimacy is real. Score 8.5+ when the subject is in a vulnerable or "
        "private state that required deep trust to photograph. The rawness of the "
        "technical execution (grain, available light, domestic clutter) is EVIDENCE "
        "of this access, not a penalty. NEVER score DoD below 6.0 for genuine intimate "
        "access — the difficulty is the relationship, not the exposure settings.\n\n"
        "DM: Score the unguarded moment within intimacy — the expression, gesture, or "
        "position that reveals the subject's private self. The decisive moment here is "
        "not a public peak but a private truth. A direct gaze while remaining completely "
        "relaxed in a private space scores DM 7.5–8.5.\n\n"
        "WF: Score ACCESS WONDER — the sense that the viewer is seeing something "
        "private that was shared willingly. The wonder is in the trust. "
        "Score 8.0–8.5 when the intimacy feels genuine and the access feels earned. "
        "Score 8.5–9.0 when the access is extraordinary — a private moment of "
        "vulnerability, tenderness, or raw domestic truth that almost no photographer "
        "is ever allowed to document. The direct gaze in a private space while the "
        "subject remains completely relaxed scores Access Wonder 8.5+.\n\n"
        "AQ: CRITICAL — DO NOT penalise grain, available light, soft focus, or domestic "
        "clutter in this sub-type. The rawness IS the aesthetic. Score AQ on the "
        "specific emotion the intimate moment creates — tenderness, vulnerability, "
        "solitude, connection. Score 8.5–9.0 when the emotional register is specific "
        "and the viewer feels something precise about the subject's inner state. "
        "Award-winning intimate documentary work scores AQ 8.5+."
    ),
    'event_ceremony': (
        "This is People photography — sub-type: EVENT / CEREMONY.\n"
        "Group or crowd moments, gatherings, performances. The challenge is extracting "
        "a singular moment from collective activity.\n\n"
        "DoD: Score clean subject separation in complex scenes, compression of crowd "
        "elements into a coherent, readable image, and the physical demands of working "
        "in busy, unpredictable, or restricted environments.\n\n"
        "DM: Score the unrepeatable collective moment — the laugh, the tear, the gesture "
        "that defines the event. One frame in five hundred. Reward the photographer who "
        "found the emotional truth of the occasion in a single image.\n\n"
        "WF: Score scale and energy. Does the image carry the emotional weight of being "
        "present at something significant? The wonder is in the feeling that this moment "
        "mattered and the photographer was there for it."
    ),
}



# ── Wildlife sub-genre context blocks ─────────────────────────────────────────
# Mirrors the People sub-genre architecture exactly.
# Injected into the scoring prompt when sub_genre is provided for a Wildlife image.
# Each block replaces the flat Wildlife genre_context with sub-type-specific rubric
# guidance for DM, DoD, and WF — the three dimensions most affected by sub-type.
#
# CRITICAL DESIGN NOTES:
# - Weights in scoring.py are NOT changed — only rubric criteria text changes
# - The sub-type block REPLACES the generic Wildlife genre_context in the prompt
# - DM for all Wildlife sub-types: IDENTIFY THE BEHAVIOURAL ACT FIRST before scoring.
#   Generic motion (takeoff, flight) scores lower than behavioural act (predation,
#   display, conflict, feeding) captured at its precise completion point.

WILDLIFE_SUBGENRE_CONTEXT = {

    # ── BIRDS ──────────────────────────────────────────────────────────────────

    'bird_in_flight': (
        "This is Wildlife photography — sub-type: BIRD IN FLIGHT.\n"
        "The primary challenge is freezing motion at the peak of the flight arc "
        "with accurate focus on the eye and primary feathers.\n\n"
        "DoD: Score shutter speed precision, tracking accuracy at speed, and "
        "exposure management on a fast-moving subject against variable backgrounds. "
        "Wing extension at full spread, primary feather separation visible, and eye "
        "sharp are the three DoD gold standards.\n\n"
        "DM: Score the peak of the flight arc — the single frame where wing geometry "
        "is most resolved and body axis cleanest. IDENTIFY whether this is pure transit "
        "or a behavioural act (prey strike, territorial display, landing approach) — "
        "behavioural flight peaks score higher than generic transit.\n\n"
        "WF: Score species rarity, behaviour rarity, and light quality. Common birds "
        "in flat light score lower than rare species, unusual plumage states, or "
        "exceptional light. Migration formations and murmurations score higher than "
        "single-bird transit."
    ),

    'bird_behaviour': (
        "This is Wildlife photography — sub-type: BIRD PREDATION / BEHAVIOUR.\n"
        "A behavioural act is in progress — predation, feeding, display, conflict, "
        "courtship, or nesting. The decisive moment is defined by THAT ACT.\n\n"
        "DoD: Score the technical difficulty of the specific act. Predation at water "
        "surface demands correct exposure for dark plumage and bright water simultaneously. "
        "IDENTIFY prey or target if present — fish in bill, insect in talon, rival in "
        "contact. Its absence when the title implies it is a deduction.\n\n"
        "DM: FIRST identify the behavioural act and its completion point. Catch freeze "
        "with prey visible scores higher than catch freeze without prey. Two birds in "
        "contact scores higher than one bird in motion. Generic takeoff in this sub-type "
        "scores LOWER — reward the act, not the transit.\n\n"
        "WF: Score behavioural rarity explicitly. Common takeoff = low. Catch freeze "
        "with prey visible = moderate. Mid-air prey transfer, cooperative hunting, "
        "rare display = high. The wonder is the complete behavioural narrative."
    ),

    'bird_family': (
        "This is Wildlife photography — sub-type: BIRD FAMILY / JUVENILE.\n"
        "Parent-offspring relationships, nest life, fledgling behaviour, chick "
        "development, juvenile learning. The emotional and biological bond is the subject.\n\n"
        "DoD: Score access to the nest or family group without disturbing behaviour, "
        "exposure management in typically shaded or backlit nest environments, and "
        "sharpness on small, fast-moving chick subjects. Nest photography at height "
        "or in concealed locations raises DoD significantly.\n\n"
        "DM: Score the peak of the relational moment — first feeding, fledgling's "
        "first flight attempt, chick sheltering under parent's wing, juvenile copying "
        "adult behaviour. The decisive moment is the one that communicates the bond "
        "or the developmental stage most completely.\n\n"
        "WF: Score species rarity and behavioural specificity. Common garden bird "
        "feeding chicks scores lower than rare species at nest, unusual parental "
        "behaviour, or documentation of a specific developmental milestone. "
        "Cooperative breeding, allopreening, or adoption behaviour scores highest."
    ),

    'bird_migration': (
        "This is Wildlife photography — sub-type: BIRD MIGRATION / MURMURATION.\n"
        "Mass movement, formations, murmurations, staging grounds. Scale and "
        "collective behaviour are the primary subjects.\n\n"
        "DoD: Score the logistical challenge of being in the right location at the "
        "right time — migration timing is unpredictable, staging grounds are remote, "
        "and murmurations are fleeting. Exposure management across a sky full of "
        "moving subjects, and sharpness across the formation, are technical criteria.\n\n"
        "DM: Score the peak of the collective behaviour — the moment the murmuration "
        "forms its most complex shape, the instant the V-formation is most perfectly "
        "resolved, the second the entire flock lifts from a staging ground simultaneously. "
        "The decisive moment for migration is scale and geometry, not individual action.\n\n"
        "WF: Score scale and rarity. A murmuration of millions is rarer than a flock "
        "of hundreds. Species in genuine decline make migration documentation "
        "scientifically significant. The wonder is in the collective intelligence "
        "of the movement — shapes that no individual bird planned."
    ),

    # ── MAMMALS ────────────────────────────────────────────────────────────────

    'mammal_behaviour': (
        "This is Wildlife photography — sub-type: MAMMAL BEHAVIOUR / CONFLICT.\n"
        "Adult mammal behaviour across the full range: predation, territorial conflict, "
        "sparring, aggression, dominance display, scent marking, alarm response. "
        "The behavioural act — not the animal alone — is the primary subject.\n\n"
        "DoD: Score tracking difficulty of fast-moving subjects, correct exposure "
        "across different fur tones, and sharpness at the point of maximum action. "
        "Dangerous proximity to large predators, access to remote habitat, or night "
        "photography all raise DoD significantly.\n\n"
        "DM: IDENTIFY the specific behavioural act before scoring. Predation: is prey "
        "visible and readable? Conflict: is the moment of contact or maximum threat "
        "display captured? Both subjects must be readable in the decisive frame. "
        "A half-second before contact is often the peak — reward the photographer "
        "who pre-positioned for that frame.\n\n"
        "WF: Score narrative completeness and species/behaviour rarity. Does the image "
        "tell the full story — predator, prey, tension, environment? Rare species, "
        "rarely documented interactions, or scientifically significant behaviour "
        "scores highest. Tiger siblings sparring = juvenile play, not predation — "
        "score DM on the peak of the play interaction, WF on the rarity of "
        "documenting big cat juvenile behaviour in wild conditions."
    ),

    'mammal_family': (
        "This is Wildlife photography — sub-type: MAMMAL FAMILY / JUVENILE.\n"
        "Mother-offspring bonds, cub/calf/pup development, sibling interactions, "
        "juvenile learning, play behaviour, nursing, protection. The biological "
        "and emotional relationship is the subject.\n\n"
        "DoD: Score access to family groups (typically highly protective and difficult "
        "to approach), exposure in low light (dawn/dusk nursing behaviour), and "
        "sharpness on fast-moving cubs. Wild family groups are significantly harder "
        "to access than solitary adults.\n\n"
        "DM: Score the peak of the relational or developmental moment — the first "
        "steps of a calf, a mother lifting her cub by the scruff, siblings at play "
        "with the exact moment of mock-attack frozen, a juvenile copying adult "
        "behaviour for the first time. The decisive moment is the one that makes "
        "the bond or the learning visible.\n\n"
        "WF: Score species rarity and developmental specificity. Elephant calves "
        "nursing are seen; elephant calves learning to use their trunk for the "
        "first time is rarer. Document a specific milestone — first hunt attempt, "
        "first water crossing, first independent kill — and WF climbs significantly."
    ),

    'mammal_migration': (
        "This is Wildlife photography — sub-type: MAMMAL MIGRATION / HERD.\n"
        "Mass movement, river crossings, seasonal aggregations, herd dynamics. "
        "Scale, danger, and collective behaviour are the primary subjects.\n\n"
        "DoD: Score location access (Mara river crossings require specific timing "
        "and positioning), exposure management in dusty or chaotic conditions, "
        "and the physical challenge of working around large moving animals. "
        "Being in the right position for the crossing moment requires days of waiting.\n\n"
        "DM: Score the peak of the collective movement — the moment the herd commits "
        "to the crossing, the instant the lead animal enters the water, the frame "
        "where predator and migrating prey are simultaneously readable. Migration "
        "DM rewards scale and narrative over individual animal action.\n\n"
        "WF: Score scale, species, and ecological significance. A wildebeest "
        "crossing of thousands is less rare than the same image with crocodile "
        "predation visible. Declining species in migration have conservation "
        "documentary value. The wonder is witnessing a planetary biological rhythm."
    ),

    'primate_behaviour': (
        "This is Wildlife photography — sub-type: PRIMATE SOCIAL / BEHAVIOUR.\n"
        "All primates — great apes, monkeys, prosimians. Social intelligence, "
        "hierarchy, grooming, aggression, tool use, play, infant care, "
        "and the mirror of human behaviour in non-human primates.\n\n"
        "DoD: Score the difficulty of working in dense forest or complex social "
        "groups, maintaining focus on fast-moving subjects in dappled light, "
        "and the access required to be trusted by a habituated primate group. "
        "Wild unhabituated primates are maximum DoD.\n\n"
        "DM: Score the peak of the social or behavioural moment — the exact "
        "instant of aggressive display, the moment of reconciliation after conflict, "
        "the precise gesture of tool use, the expression of play or fear. "
        "Primate faces communicate emotion with human-like expressiveness — "
        "the decisive moment is when that communication is at its most legible.\n\n"
        "WF: Score behavioural complexity and the degree to which the image "
        "reveals primate intelligence. Grooming = low WF. Tool use = moderate. "
        "Problem-solving, coalition behaviour, deceptive behaviour, or "
        "documented cultural transmission = high WF."
    ),

    'bat_behaviour': (
        "This is Wildlife photography — sub-type: BAT BEHAVIOUR / EMERGENCE.\n"
        "Bats are the most nocturnal and most technically challenging mammal subjects. "
        "Emergence flights, echolocation hunting, roost behaviour, "
        "mother-pup relationships, and cave colony documentation.\n\n"
        "DoD: Score the extreme technical challenge of fast-moving subjects in "
        "near-darkness, requiring high ISO, fast shutter, and accurate tracking "
        "on erratic flight paths. Cave emergence photography — thousands of bats "
        "exiting in low light — is among the highest DoD in wildlife photography. "
        "Echolocation hunting freeze requires precise triggering.\n\n"
        "DM: Score the peak of the specific behaviour — the moment of prey contact "
        "for a hunting bat, the maximum density point of an emergence flight, "
        "the instant a mother lands to nurse a pup. Bat DM rewards the photographer "
        "who mastered the technical challenge AND found the behavioural peak.\n\n"
        "WF: Score species rarity (many bat species are threatened or rarely "
        "photographed), behavioural documentation value, and the sense of revealing "
        "a hidden nocturnal world. Mass emergence from a cave at dusk = high WF. "
        "Hunting bat catching a moth mid-air = very high WF."
    ),

    # ── AQUATIC / MARINE ───────────────────────────────────────────────────────

    'dolphin_behaviour': (
        "This is Wildlife photography — sub-type: DOLPHIN / CETACEAN BEHAVIOUR.\n"
        "Dolphins, whales, orcas, porpoises. Social intelligence, cooperative "
        "hunting, breach sequences, bow-riding, superpod formations, "
        "mother-calf bonding, and cetacean play.\n\n"
        "DoD: Score the unpredictability of cetacean behaviour at sea, exposure "
        "management on fast-moving dark subjects against bright water, and "
        "the access challenge of open ocean photography. Underwater cetacean "
        "photography adds the additional medium challenge.\n\n"
        "DM: IDENTIFY the specific behaviour — breach, spy-hop, bow-ride, hunt, "
        "mother-calf interaction, play. Score the peak of THAT act. A breach "
        "peaks at full airborne extension. A hunt peaks at prey contact. "
        "A superpod peaks at maximum visible density with behavioural coherence.\n\n"
        "WF: Score species rarity, behaviour rarity, and documentation value. "
        "Orca cooperative hunting is rarer than dolphin bow-riding. "
        "Humpback lunge-feeding, whale song behaviour above water, or "
        "rare species documentation scores highest."
    ),

    'marine': (
        "This is Wildlife photography — sub-type: MARINE / UNDERWATER.\n"
        "Aquatic and underwater subjects across all marine environments. "
        "The technical challenges of the medium — colour shift, refraction, "
        "buoyancy control — are inherent DoD signals.\n\n"
        "DoD: Score colour correction in a colour-shifting medium, focus through "
        "water, correct exposure without strobes washing the subject, and the "
        "physical access challenge of the marine environment — dive depth, "
        "current, visibility, and equipment management.\n\n"
        "DM: Score the peak of animal behaviour or ideal environmental alignment — "
        "the frame where subject, light shaft, and background are optimally placed. "
        "IDENTIFY the behavioural act (feeding, mating, predation, cleaning station "
        "behaviour) before scoring. Apply the same behavioural identification test "
        "as bird_behaviour — generic 'fish swimming' scores lower than behaviour.\n\n"
        "WF: Score access rarity and environmental revelation. Healthy reef ecosystems, "
        "deep-water species, bioluminescence, or documentation of threatened habitat "
        "scores highest. The wonder is showing the viewer a world they cannot access."
    ),

    'marine_migration': (
        "This is Wildlife photography — sub-type: MARINE MIGRATION / SHOALING.\n"
        "Fish schools, whale migration routes, turtle aggregations, salmon runs, "
        "sardine bait balls, and other mass aquatic movements.\n\n"
        "DoD: Score the access challenge of being in the water during a mass "
        "movement event, correct exposure on thousands of moving subjects, "
        "and the physical challenge of the marine environment during biological "
        "events (upwellings, spawning aggregations).\n\n"
        "DM: Score the peak of the collective movement — the moment a bait ball "
        "is at maximum compression, the frame where a salmon run is densest, "
        "the instant predators and prey are simultaneously visible in the shoal. "
        "Scale and narrative completeness define the decisive moment.\n\n"
        "WF: Score ecological significance and rarity. Sardine bait ball with "
        "multiple predator species visible = high WF. Documented species in "
        "decline during their migration = conservation value. The wonder is "
        "the scale of coordinated biological movement."
    ),

    # ── REPTILES & AMPHIBIANS ──────────────────────────────────────────────────

    'reptile_amphibian': (
        "This is Wildlife photography — sub-type: REPTILE / AMPHIBIAN BEHAVIOUR.\n"
        "Snakes, lizards, crocodilians, turtles, frogs, salamanders. "
        "Cold-blooded subjects with behaviour driven by thermoregulation, "
        "ambush predation, and seasonal breeding events.\n\n"
        "DoD: Score the access and patience required to work with ectothermic "
        "subjects — reptiles require specific temperature conditions to be active, "
        "and crocodilian predation photography requires proximity to large dangerous "
        "animals. Frog breeding events are triggered by rain and last hours only.\n\n"
        "DM: IDENTIFY the specific act — ambush strike, frog breeding mass, "
        "snake-prey coiling, lizard territorial display, turtle egg-laying. "
        "Score the peak of THAT act. An anaconda-caiman coil peaks at maximum "
        "constriction force. A frog breeding event peaks at maximum density. "
        "A strike peaks at point of contact.\n\n"
        "WF: Score species rarity and behavioural documentation value. "
        "Common garden lizard sunbathing = low WF. Rare frog species in "
        "rain-triggered breeding aggregation = high WF. Snake predation on "
        "a bat = very high WF. Conservation documentation of declining "
        "amphibian species adds scientific value."
    ),

    # ── INVERTEBRATES ──────────────────────────────────────────────────────────

    'butterfly_behaviour': (
        "This is Wildlife photography — sub-type: BUTTERFLY / INSECT BEHAVIOUR.\n"
        "Butterflies, moths, beetles, flies, and other winged insects. "
        "Metamorphosis, mating, migration swarms, feeding, and "
        "the extraordinary visual complexity of insect life.\n\n"
        "DoD: Score focus precision on small, fast-moving subjects in ambient "
        "conditions, depth of field control that renders wing detail while "
        "separating from background, and the access challenge of finding "
        "specific behaviours (metamorphosis emergence is brief and unpredictable).\n\n"
        "DM: Score the behavioural peak — the exact moment of emergence from "
        "chrysalis, the mating wheel formation locked, the monarch at maximum "
        "migration density, the feeding posture at its most structured. "
        "For migration swarms, DM rewards scale and collective geometry.\n\n"
        "WF: Score what the image reveals that the naked eye cannot see unaided — "
        "wing scale structure, compound eye geometry, mating behaviour complexity. "
        "Rare species, migration documentation, or metamorphosis capture scores "
        "highest. Bee mating balls, butterfly migration corridors, and "
        "bioluminescent firefly displays are among the highest WF in invertebrate photography."
    ),

    'invertebrate_behaviour': (
        "This is Wildlife photography — sub-type: INVERTEBRATE BEHAVIOUR.\n"
        "Ants, bees, spiders, crabs, octopus, jellyfish, worms, and all "
        "non-insect invertebrates. Collective intelligence, predation, "
        "construction, and the alien complexity of invertebrate life.\n\n"
        "DoD: Score the extreme close-focus challenge, lighting in tight spaces, "
        "and the patience required to document invertebrate behaviour — ant colony "
        "dismembering prey, spider web construction, octopus colour change. "
        "Many invertebrate subjects require macro or super-macro technique.\n\n"
        "DM: Score the specific behavioural peak — maximum dismemberment activity "
        "on an ant prey item, the spider at the precise moment of web-tension "
        "adjustment, the octopus at the instant of colour-change. "
        "Invertebrate DM rewards the photographer who understood the behaviour "
        "well enough to anticipate the peak.\n\n"
        "WF: Score what the image reveals about invertebrate intelligence and "
        "complexity. Ant trail = low WF. Ant colony cooperative prey transport = "
        "moderate. Ant colony problem-solving or bee waggle dance documented = "
        "high WF. The wonder is in the discovery that these small animals "
        "have social structures as complex as any vertebrate."
    ),

    # ── PLANTS & FUNGI ─────────────────────────────────────────────────────────

    'flora': (
        "This is Wildlife photography — sub-type: FLORA / BOTANICAL / FUNGI.\n"
        "Plant life, fungi, spore dispersal, germination, and botanical subjects. "
        "The challenge is revealing structural and biological detail invisible "
        "to the casual eye.\n\n"
        "DoD: Score depth of field control at close focus distances, light quality "
        "on translucent or textured organic surfaces, and environmental context. "
        "Background separation that isolates the subject while retaining habitat "
        "context is the DoD gold standard. Spore dispersal photography requires "
        "precise timing and triggering.\n\n"
        "DM: Score the moment of botanical or fungal peak — first light on morning "
        "dew, spores at maximum dispersal density, the specific angle that reveals "
        "internal structure, germination at the exact moment of soil emergence. "
        "Flora DM rewards timing and angle choice over reaction speed.\n\n"
        "WF: Score what the photograph reveals that the eye cannot see unaided — "
        "structural geometry, translucency, spore cloud physics, bioluminescent "
        "fungi, or rare species documentation. Conservation significance of "
        "threatened plant or fungal species adds scientific value."
    ),

    # ── MACRO ──────────────────────────────────────────────────────────────────

    'macro_wildlife': (
        "This is Wildlife photography — sub-type: MACRO WILDLIFE.\n"
        "Insects, arachnids, small reptiles, and micro-fauna at extreme "
        "magnification. Precision focus and depth of field management are "
        "the primary technical criteria.\n\n"
        "DoD: Score focus accuracy at high magnification (eye or primary feature "
        "sharp), depth of field control that renders the critical structure while "
        "separating from background, and lighting that reveals surface texture "
        "without harsh specular reflections. Handheld field macro scores higher "
        "DoD than studio macro.\n\n"
        "DM: Score the behavioural or structural peak — eye contact moment, "
        "feeding posture, mating display, emergence from chrysalis. "
        "Macro Wildlife DM rewards the frame where behaviour and optimal focus "
        "alignment coincide. A technically sharp macro of a static subject scores "
        "lower DM than a more challenging capture of a live behavioural moment.\n\n"
        "WF: Score subject rarity and structural revelation — the hidden face, "
        "the structure invisible without the photograph. Common species in "
        "extraordinary detail scores higher than rare species in poor light."
    ),

    # ── ENVIRONMENTAL / CONTEXTUAL ─────────────────────────────────────────────

    'animals_in_environment': (
        "This is Wildlife photography — sub-type: ANIMAL IN HABITAT / ENVIRONMENT.\n"
        "The animal is in the frame but the habitat, ecosystem, or environmental "
        "context is the co-subject. The relationship between creature and place "
        "is the story.\n\n"
        "DoD: Score location access (remote terrain, extreme weather, restricted "
        "environments), the patience required for the right light-animal-landscape "
        "alignment, and technical management of a wide dynamic range between "
        "animal subject and landscape background.\n\n"
        "DM: Score the peak of the environmental relationship — the moment the "
        "animal's position within its habitat is most perfectly expressed. "
        "A wolf silhouetted against an aurora, a bear in a salmon river at "
        "last light, an elephant dwarfed by a dust storm. The decisive moment "
        "is when subject and environment are in complete narrative accord.\n\n"
        "WF: Score the environmental storytelling. Does the image communicate "
        "something about the habitat, ecosystem health, or the animal's "
        "relationship to its world that a portrait alone cannot? "
        "Conservation context — habitat loss, climate impact, human encroachment "
        "visible in the frame — raises WF significantly."
    ),

    'urban_wildlife': (
        "This is Wildlife photography — sub-type: URBAN WILDLIFE.\n"
        "Animals navigating human-built environments — foxes in cities, leopards "
        "in Mumbai suburbs, peregrine falcons on skyscrapers, deer in car parks, "
        "birds nesting on buildings. The human-wildlife interface is the story.\n\n"
        "NOTE ON CAPTIVE/ZOO IMAGES: Urban wildlife specifically means wild animals "
        "in urban environments, NOT captive animals in zoos, aquariums, or wildlife "
        "parks. If cage bars, enclosure walls, zoo signage, unnatural substrate, "
        "or feeding troughs are visible, this is NOT urban wildlife — DoD must be "
        "penalised and the captive context noted in the score text.\n\n"
        "DoD: Score the challenge of finding and photographing wild animals in "
        "urban environments — unpredictable timing, mixed artificial and natural "
        "light, cluttered backgrounds, and the ethical challenge of not habituating "
        "wild animals to human presence.\n\n"
        "DM: Score the peak of the human-wildlife interaction narrative — the fox "
        "looking directly into a shop window, the leopard crossing a lit road, "
        "the moment where the wildness of the animal and the artificiality of "
        "the environment are in maximum visual tension.\n\n"
        "WF: Score the environmental storytelling and the degree to which the "
        "image prompts reflection on coexistence, habitat loss, or adaptation. "
        "The wonder is in the surprise of wildness in a human space."
    ),

    'animal_portrait': (
        "This is Wildlife photography — sub-type: ANIMAL PORTRAIT.\n"
        "Frame-filling or close single-animal portraits where expression, "
        "personality, and eye contact are the primary subjects. No specific "
        "action required — the animal's presence and gaze are the story.\n\n"
        "NOTE ON CAPTIVE SUBJECTS: If cage bars, enclosure walls, unnatural "
        "substrate, or zoo infrastructure are visible in the frame, DoD must "
        "be penalised — the access difficulty of a zoo enclosure is not "
        "equivalent to a wild portrait. Note the captive context explicitly.\n\n"
        "DoD: Score the access and proximity required for a frame-filling wild "
        "portrait, correct exposure on fur/feather/scale texture, and the "
        "challenge of achieving eye sharpness on an animal that may not "
        "cooperate. Genuinely wild unhabituated subjects at portrait distance "
        "represent maximum DoD.\n\n"
        "DM: Score eye contact and expression — the single frame where the "
        "animal's personality or inner state is most fully present. "
        "Stillness is NOT a penalty. A portrait earns high DM when the "
        "subject's awareness of the camera creates genuine visual tension, "
        "or when an expression of alertness, curiosity, aggression, or calm "
        "is perfectly resolved in that specific frame.\n\n"
        "WF: Score species rarity, proximity rarity, and the degree to which "
        "the portrait reveals something about the animal beyond its appearance. "
        "Eye contact with a wild apex predator = high WF. The same contact "
        "with a captive zoo animal = low WF. The wonder is in genuine wildness "
        "meeting the camera."
    ),

}




# ── Nature sub-genre context blocks ──────────────────────────────────────────

NATURE_SUBGENRE_CONTEXT = {

    'nature_flora': (
        "This is Nature photography — sub-type: FLOWERS AND PLANTS.\n"
        "The subject is plant life — flowers, leaves, roots, seeds, germination, "
        "plant structures. The photograph reveals botanical detail or beauty "
        "that the naked eye cannot fully appreciate.\n\n"
        "DoD: Score depth of field precision, background separation without losing "
        "habitat context, light quality on translucent petals or surfaces, and "
        "environmental access. Dew photography at dawn, sub-canopy forest light, "
        "or remote botanical specimens raise DoD.\n\n"
        "DM: Score the moment of botanical peak — first light, peak bloom, dew at "
        "maximum surface tension, the exact angle that reveals petal geometry. "
        "Timing and angle are the primary DM variables for flora.\n\n"
        "Wonder: Score what the image reveals that the eye cannot see unaided — "
        "petal translucency, structural geometry, hidden colour in UV-sensitive "
        "surfaces, or rare species documentation."
    ),

    'nature_fungi': (
        "This is Nature photography — sub-type: FUNGI AND MOSSES.\n"
        "Mushrooms, bracket fungi, moulds, bioluminescent fungi, lichens, mosses. "
        "The photograph reveals the extraordinary structures of the fungal kingdom.\n\n"
        "DoD: Score the challenge of low-light forest environments, precise focus on "
        "complex three-dimensional structures, and access to remote forest habitats. "
        "Night photography of bioluminescent fungi represents maximum DoD in this sub-type.\n\n"
        "DM: Score the moment of ecological peak — spore dispersal in progress, "
        "bioluminescence at its strongest, the specific angle that reveals gill "
        "structure or surface texture most completely.\n\n"
        "Wonder: Score ecological significance and visual revelation. Bioluminescent "
        "fungi = very high Wonder. Rare or threatened species = high Wonder. "
        "Common woodland mushroom in extraordinary detail = moderate Wonder."
    ),

    'nature_ecosystem': (
        "This is Nature photography — sub-type: FORESTS AND ECOSYSTEMS.\n"
        "Habitat-scale photography — forests, wetlands, coral reefs, grasslands, "
        "tundra. The subject is the system itself, not a single organism.\n\n"
        "DoD: Score access to remote or threatened ecosystems, the patience and "
        "planning required for the right light and atmospheric conditions, and "
        "any physical challenge of the environment.\n\n"
        "DM: Score the moment when the ecosystem reveals its character most fully — "
        "morning mist in a forest, the light shaft moment, the season change instant. "
        "Ecosystem DM rewards patience and environmental knowledge.\n\n"
        "Wonder: Score conservation significance. A healthy, biodiverse ecosystem "
        "scores higher Wonder than a visually beautiful but ecologically depleted one. "
        "Threatened habitats carry additional significance weight."
    ),

    'nature_weather': (
        "This is Nature photography — sub-type: WEATHER AND ATMOSPHERIC PHENOMENA.\n"
        "Storms, lightning, fog, cloud formations, rainbows, sundogs, auroras, "
        "dust devils, tornadoes. The atmosphere itself is the subject.\n\n"
        "DoD: Score the physical challenge and risk of positioning for extreme weather — "
        "lightning photography requires both timing and physical exposure to storms, "
        "tornado documentation is inherently dangerous, aurora photography requires "
        "remote dark-sky access in cold conditions.\n\n"
        "DM: Score the peak of the atmospheric event — the lightning strike, the "
        "moment the storm cell is most defined, the aurora at maximum intensity, "
        "the fog at its most sculptural. Weather DM is unforgiving — the peak "
        "moment is brief and unrepeatable.\n\n"
        "Wonder: Score the power and rarity of the phenomenon. A common suburban "
        "rainbow scores lower than a circumzenithal arc. A single lightning bolt "
        "scores lower than a storm cell with multiple strikes. Aurora borealis "
        "at maximum geomagnetic activity scores highest."
    ),

    'nature_water': (
        "This is Nature photography — sub-type: RIVERS, WATERFALLS AND WATER.\n"
        "Freshwater systems — rivers, waterfalls, lakes, pools, rapids. "
        "The movement, light, and physics of water are the primary subjects.\n\n"
        "DoD: Score long-exposure control, location access (remote waterfalls, "
        "rapid-water environments), timing for the right flow conditions, and "
        "technical management of high-contrast water-and-rock scenes.\n\n"
        "DM: Score the moment of optimal flow and light alignment — silky water "
        "at the right shutter speed, the waterfall at peak seasonal flow, "
        "the reflection at perfect stillness.\n\n"
        "Wonder: Score the environmental storytelling — does the image communicate "
        "the power, beauty, or fragility of the water system? Conservation context "
        "(drought-reduced rivers, glacial retreat) raises Wonder."
    ),

    'nature_astro': (
        "This is Nature photography — sub-type: NIGHT SKY AND ASTRONOMY.\n"
        "Milky Way, star trails, meteor showers, lunar photography, eclipse, "
        "planetary conjunctions, and dark sky landscapes.\n\n"
        "DoD: Score the access difficulty (remote dark sky locations, extreme cold), "
        "technical precision of night exposure (star sharpness vs trailing, correct "
        "ISO/shutter balance), and any landscape foreground challenge.\n\n"
        "DM: Score the alignment of sky event and landscape — the Milky Way core "
        "over a significant foreground, the meteor at the peak of the shower, "
        "the eclipse at totality. Astro DM rewards planning and positioning.\n\n"
        "Wonder: Score the scale revelation — the image that makes the viewer feel "
        "the immensity of the universe. Rare celestial events (eclipses, conjunctions, "
        "significant meteor showers) score highest."
    ),

    'nature_underwater': (
        "This is Nature photography — sub-type: UNDERWATER AND CORAL.\n"
        "Marine and freshwater underwater environments — reefs, kelp forests, "
        "open water, caves, and underwater landscapes.\n\n"
        "DoD: Score the physical challenge of the underwater environment — dive depth, "
        "current, visibility, colour correction in a colour-shifting medium, "
        "buoyancy control for stable composition, and equipment management.\n\n"
        "DM: Score the peak of environmental beauty or ecological alignment — "
        "the light shaft moment, the schooling fish at maximum density, "
        "the coral formation under ideal light.\n\n"
        "Wonder: Score conservation significance. Healthy reef ecosystems with high "
        "biodiversity, deep-water environments, bioluminescence, or documentation "
        "of threatened habitat scores highest."
    ),

    'nature_seasons': (
        "This is Nature photography — sub-type: SEASONS AND NATURAL CHANGE.\n"
        "Autumn colour, spring bloom, winter frost, summer drought — the visible "
        "evidence of seasonal and environmental change.\n\n"
        "DoD: Score timing precision (peak autumn colour lasts days, not weeks), "
        "location access, and the patience required for the right light.\n\n"
        "DM: Score the moment of seasonal peak — the single frame where the "
        "transformation is most completely expressed.\n\n"
        "Wonder: Score both visual beauty and environmental significance. "
        "First frost on an urban environment, drought-cracked earth, bleached "
        "coral during a heat event — seasonal change as evidence of environmental "
        "stress carries additional Wonder weight."
    ),
}


# ── Documentary sub-genre context blocks ─────────────────────────────────────

DOCUMENTARY_SUBGENRE_CONTEXT = {

    'doc_environment': (
        "This is Documentary photography — sub-type: ENVIRONMENT AND CLIMATE.\n"
        "The image documents the state of the environment — climate change effects, "
        "industrial impact, deforestation, drought, flooding, pollution, ecological "
        "damage, or environmental resilience. The photograph is evidence of "
        "a condition of the planet.\n\n"
        "DoD: Score access to affected environments (flood zones, post-disaster "
        "landscapes, remote deforested regions, polluted waterways), and the "
        "physical challenge of working in degraded or hostile environments.\n\n"
        "DM: Score the moment that makes the environmental condition undeniable — "
        "the cracked earth that captures drought, the waterline mark that shows "
        "sea level change, the before/after that requires no caption.\n\n"
        "Wonder: Score the image's power to change how the viewer understands an "
        "environmental reality. Does this image make the climate crisis visible? "
        "Does it show something most viewers choose not to see? "
        "The strongest environmental documentary images are the ones that cannot "
        "be ignored once seen."
    ),

    'doc_urban': (
        "This is Documentary photography — sub-type: CITY SYSTEMS AND URBAN LIFE.\n"
        "Urban infrastructure, city systems under stress, industrial landscapes, "
        "urban poverty, city transformation, and the human cost of urban systems. "
        "Distinct from Street photography — the subject is the system, not the moment.\n\n"
        "DoD: Score access to restricted urban environments (industrial facilities, "
        "infrastructure, areas undergoing demolition or transformation), and the "
        "technical challenge of urban documentary light (industrial, mixed, artificial).\n\n"
        "DM: Score the moment that most completely reveals the system being documented — "
        "the shift change at a factory, the eviction moment, the demolition instant.\n\n"
        "Wonder: Score the image's power to reveal how the city actually works — "
        "the infrastructure most people never see, the cost of urban life most "
        "people choose to ignore."
    ),

    'doc_health': (
        "This is Documentary photography — sub-type: HEALTH AND MEDICINE.\n"
        "Hospitals, clinics, patient care, medical procedures, healthcare access, "
        "and the human experience of illness and healing. The image documents a "
        "medical reality.\n\n"
        "DoD: Score access to clinical environments (hospital wards, operating "
        "theatres, emergency settings), the difficulty of working with natural or "
        "available light in clinical spaces, and the trust required to be given "
        "access to photograph medical situations.\n\n"
        "DM: Score the moment of human truth within the medical context — the moment "
        "of diagnosis, the expression of pain or relief, the gesture of care. "
        "Health documentary DM rewards the frame that carries the weight of what "
        "the patient or carer is experiencing.\n\n"
        "Wonder: Score the image's significance as a document of healthcare reality. "
        "Images that show the viewer a medical reality they would not otherwise see — "
        "healthcare access inequality, the experience of chronic illness, the work "
        "of medical staff under pressure — score highest."
    ),

    'doc_birth': (
        "This is Documentary photography — sub-type: BIRTH AND NEW LIFE.\n"
        "Birth, delivery, immediate postnatal moments, and the first hours of life. "
        "This is among the most significant documentary subjects in all of photography.\n\n"
        "DoD: Score the extreme access difficulty (delivery rooms are restricted), "
        "the technical challenge of one-shot moments with no control over light or "
        "position, and the emotional complexity of working in a delivery environment. "
        "A genuine birth documentation represents DoD 7.0 minimum.\n\n"
        "DM: CRITICAL — the DM ceiling for birth photography is 9.5. "
        "The moment of first breath, first contact between mother and newborn, "
        "or the physical act of delivery are among the highest DM opportunities "
        "in all of photography. These moments are absolutely unrepeatable. "
        "Do NOT penalise motion blur, difficult angles, or clinical light — "
        "the photographer had one chance and no control.\n\n"
        "Wonder: Score the primal significance of the moment. Birth photography "
        "Wonder is not visual beauty — it is the recognition of life beginning. "
        "The first breath, the first cry, the first skin-to-skin contact are among "
        "the highest Wonder scores available to any genre. "
        "Score the image's power to make the viewer feel the weight of the moment."
    ),

    'doc_social': (
        "This is Documentary photography — sub-type: SOCIAL ISSUES.\n"
        "Poverty, hunger, displacement, homelessness, conflict aftermath, refugee "
        "conditions, inequality, and the human cost of social systems. "
        "The image is a document of how people live.\n\n"
        "DoD: Score access to difficult social environments, the trust required to "
        "photograph people in vulnerable situations with dignity, and the physical "
        "and emotional challenge of working in conditions of hardship.\n\n"
        "DM: Score the frame that carries the full weight of the social reality — "
        "not the most dramatic, but the most true. In multi-figure images, score the "
        "narrative tension between figures — the foreground resignation against the "
        "background defiance, the single figure isolated from the group, the gesture "
        "that carries the whole story. The most true frame, not the most dramatic.\n\n"
        "Wonder: CULTURAL WONDER and ACCESS WONDER are both primary signals here.\n"
        "CULTURAL WONDER: A slum community going about daily life beside railway tracks, "
        "workers in a toxic industrial environment, people living in conditions most "
        "viewers will never enter — this is Wonder 8.0–8.5. The image shows a reality "
        "most people choose not to see.\n"
        "ACCESS WONDER: Being inside the working environment — not photographing it "
        "from outside — scores Access Wonder 7.5–8.5. Physical presence in the difficult "
        "space is the access signal.\n"
        "DO NOT score Wonder low because the setting is ordinary or the subjects are "
        "not doing anything dramatic. Daily life in difficult conditions IS the Wonder."
    ),

    'doc_community': (
        "This is Documentary photography — sub-type: COMMUNITY AND CULTURE.\n"
        "Cultural traditions, community life, traditions under threat, ways of "
        "living that are changing or disappearing. The image preserves a cultural "
        "reality.\n\n"
        "DoD: Score access to communities and cultural events that require trust "
        "and relationship to photograph, the challenge of working within cultural "
        "contexts with sensitivity and respect, and remote or restricted access.\n\n"
        "DM: Score the moment of cultural authenticity — when the tradition, the "
        "community, or the way of life is most completely expressed in a single frame.\n\n"
        "Wonder: Score cultural significance and the image's value as preservation. "
        "Traditions that are disappearing, communities under threat, ways of life "
        "that most viewers will never encounter — the wonder is in the documentation "
        "of human cultural diversity."
    ),

    'doc_crisis': (
        "This is Documentary photography — sub-type: CRISIS AND EMERGENCY.\n"
        "Disease outbreaks, natural disasters, conflict, emergency response, "
        "and acute human crisis. The image documents a moment of collective emergency.\n\n"
        "DoD: Score the personal risk and physical challenge of being present "
        "during a crisis, access to restricted emergency environments, and the "
        "technical difficulty of working in chaotic, dangerous, or rapidly "
        "changing conditions. Crisis documentary photography represents the highest "
        "DoD in the documentary genre.\n\n"
        "DM: Score the moment that carries the full weight of the crisis — the "
        "frame that makes the emergency real and undeniable. In crisis photography, "
        "the decisive moment is the one that will be remembered.\n\n"
        "Wonder: Score the image's historical and human significance. Does this "
        "image document something that must not be forgotten? Crisis images that "
        "change public understanding of an emergency score highest."
    ),
}


# ── Macro sub-genre context blocks ───────────────────────────────────────────

MACRO_SUBGENRE_CONTEXT = {

    'macro_living': (
        "This is Macro photography — sub-type: LIVING SUBJECTS.\n"
        "Insects, arachnids, small reptiles, amphibians, eyes, skin texture, "
        "and any living subject at extreme magnification. Behaviour and "
        "precision combine as the primary criteria.\n\n"
        "DoD: Score focus accuracy on a potentially moving subject at high "
        "magnification, depth of field control that renders the critical feature "
        "sharp, and lighting that reveals surface texture without harsh reflections. "
        "Handheld field macro on a live subject scores higher than controlled studio macro.\n\n"
        "DM: Score the behavioural or expression peak — the eye-contact moment, "
        "the feeding posture, the display behaviour, the exact frame where behaviour "
        "and optimal focus alignment coincide. Living macro DM rewards the photographer "
        "who anticipated the behavioural peak.\n\n"
        "Wonder: Score structural revelation AND behavioural significance — the hidden "
        "face of a familiar creature, the compound eye geometry, the expression of "
        "intelligence in a small subject. Common species in extraordinary detail "
        "scores higher than rare species in poor execution."
    ),

    'macro_natural': (
        "This is Macro photography — sub-type: NATURAL OBJECTS.\n"
        "Flowers, seeds, pollen, crystals, minerals, feathers, shells, dew drops, "
        "and natural non-living objects at extreme magnification.\n\n"
        "DoD: Score depth of field precision on complex three-dimensional subjects, "
        "lighting that reveals natural surface structure, and the challenge of "
        "working with fragile or ephemeral natural subjects (dew evaporates, "
        "flowers wilt, crystals are damaged by handling).\n\n"
        "DM: Score the compositional decision — the exact angle and light position "
        "that reveals the subject's form most completely. For dew photography, "
        "the DM is the moment of maximum surface tension.\n\n"
        "Wonder: Score what the image reveals about natural geometry and structure — "
        "the mathematical precision of a snowflake, the fractal structure of a fern, "
        "the light physics inside a water droplet. Nature's hidden engineering is "
        "the Wonder dimension for natural object macro."
    ),

    'macro_manmade': (
        "This is Macro photography — sub-type: MAN-MADE OBJECTS.\n"
        "Pen nibs, fabric fibres, circuit boards, watch mechanisms, coins, tools, "
        "food surfaces, industrial components — any manufactured object at extreme "
        "magnification. The reveal of human engineering at a scale the eye cannot see.\n\n"
        "DoD: Score precision focus on hard geometric surfaces (more demanding than "
        "organic subjects — no forgiveness for focus errors on a pen nib slit), "
        "lighting that reveals metallic or textile surface structure without harsh "
        "specular blow-out, and depth of field management across flat or complex "
        "manufactured geometries.\n\n"
        "DM: Score the compositional decision — the angle and light position that "
        "reveals the manufactured structure most completely. The decisive moment "
        "in man-made macro is the alignment of light, angle, and focal plane that "
        "makes the engineering visible.\n\n"
        "Wonder: CRITICAL SCORING NOTE — do NOT score Wonder by rarity or ecological "
        "significance. Score Wonder by REVELATION: does this image change how the "
        "viewer understands the object? A pen nib at 10x magnification showing the "
        "precision of the slit and the tipping ball scores Wonder 7.0+ if the image "
        "makes the viewer understand the engineering they have been touching daily "
        "without ever seeing. A cloth fibre showing individual thread structure and "
        "light catching each strand scores Wonder 6.5+ if the image reveals the "
        "craft invisible in the finished fabric. The question is always: does this "
        "image show the viewer something about this object that was invisible before?"
    ),

    'macro_water': (
        "This is Macro photography — sub-type: WATER AND LIQUID.\n"
        "Water droplets, splash crowns, bubble surfaces, liquid surface tension, "
        "condensation patterns, and liquid physics at extreme magnification.\n\n"
        "DoD: Score BOTH macro precision AND timing — capturing a droplet at peak "
        "crown shape requires macro technique AND split-second trigger control. "
        "This is among the highest combined DoD in Macro photography. "
        "Studio water photography with triggering systems scores slightly lower "
        "than natural-environment water droplet capture.\n\n"
        "DM: Score the peak of the liquid physics event — the droplet crown at "
        "maximum spread, the bubble at perfect spherical geometry, the impact "
        "at maximum splash height. Water macro DM is the most timing-dependent "
        "in the genre.\n\n"
        "Wonder: Score the physics revelation — the world refracted inside a droplet, "
        "the geometry of a splash crown, the interference patterns on a bubble surface. "
        "Water macro that reveals optical or physical phenomena scores highest."
    ),

    'macro_texture': (
        "This is Macro photography — sub-type: TEXTURE AND SURFACE.\n"
        "Pure surface documentation — skin, bark, rust, paint, stone, sand, "
        "fabric, food surfaces. The texture itself is the entire subject.\n\n"
        "DoD: Score lighting precision (raking light for maximum texture revelation, "
        "avoiding specular hot-spots that flatten the surface), depth of field "
        "control across a flat plane, and any environmental challenge.\n\n"
        "DM: Score the light angle and focal plane decision — the exact raking "
        "angle that makes every surface detail cast a shadow and reveal its depth. "
        "Texture macro DM is entirely about the quality of the lighting decision.\n\n"
        "Wonder: Score the transformation of the familiar into the abstract. "
        "Does the viewer recognise what they are looking at immediately, or "
        "does the extreme close-up transform something ordinary into pure pattern? "
        "The best texture macro makes the familiar completely unrecognisable and "
        "then delivers the reveal."
    ),

    'macro_optical': (
        "This is Macro photography — sub-type: LIGHT AND OPTICAL PHENOMENA.\n"
        "Prisms, refraction, soap films, interference patterns, caustics, "
        "bokeh patterns, and the photography of light physics at close range.\n\n"
        "DoD: Score the technical mastery required to control and direct "
        "optical phenomena — prism photography requires precise angle control, "
        "soap film photography requires understanding of interference patterns, "
        "caustic photography requires careful light positioning.\n\n"
        "DM: Score the moment of maximum optical complexity and beauty — "
        "the prism at full spectral spread, the soap film at peak interference "
        "colour, the caustic pattern at maximum resolution.\n\n"
        "Wonder: Score the revelation of light physics — does the image show "
        "the viewer how light actually behaves in a way they have never seen? "
        "Optical macro that reveals the physics of colour, refraction, or "
        "interference scores highest in this sub-type."
    ),
}


# ── Fashion sub-genre context blocks ─────────────────────────────────────────

FASHION_SUBGENRE_CONTEXT = {

    'fashion_editorial': (
        "This is Fashion photography — sub-type: EDITORIAL / LOCATION.\n"
        "Concept-driven, location-based fashion work. The environment is a deliberate "
        "creative choice that extends or contrasts the concept.\n\n"
        "DoD: Score location access and production complexity — getting models, "
        "costume, and crew to a remote desert, a rooftop, an industrial space. "
        "The technical challenge of executing a concept outdoors in uncontrolled "
        "conditions (wind, light changes, physical terrain) raises DoD.\n\n"
        "DM: Score the moment where concept, body geometry, environment, and light "
        "all align simultaneously. Editorial DM rewards the photographer who "
        "pre-visualised the frame and executed it at the exact right instant.\n\n"
        "Wonder: Score the world the image creates. Does the location choice "
        "transform the fashion concept into something larger? Two figures in "
        "contrasting black and white dresses in a volcanic desert — the environment "
        "and the concept create a world together. Score 8.0–9.0 when the "
        "environment-concept alignment is complete."
    ),

    'fashion_concept': (
        "This is Fashion photography — sub-type: CONCEPTUAL / ART-DIRECTED.\n"
        "Intellectual concept drives the image — art historical reference, "
        "temporal duality, cultural quotation, narrative fiction. The idea is "
        "the primary subject.\n\n"
        "DoD: Score the intellectual and production complexity of executing the "
        "concept. An Old Masters painting quotation requires costume research, "
        "lighting design that replicates specific painterly qualities, and technical "
        "precision of skin against dark backgrounds. Score the work behind the idea.\n\n"
        "DM: Score the exact frame where the concept is most completely resolved — "
        "where the art historical reference is most readable, where the temporal "
        "tension is most present, where the idea and the execution align.\n\n"
        "Disruption: Score the conceptual statement. Art historical quotation in "
        "contemporary fashion photography, temporal duality, cultural collision — "
        "reward ideas the viewer has not seen in this form before.\n\n"
        "Wonder: Score conceptual depth. Does the image create genuine intellectual "
        "wonder — the sense of time collapsing, of a world being constructed, of "
        "an idea being made visible? Score 8.0–9.0 when the concept is fully "
        "executed and the viewer feels both the idea and the image simultaneously."
    ),

    'fashion_studio': (
        "This is Fashion photography — sub-type: STUDIO.\n"
        "Controlled studio environment. Product, beauty, or person in clean "
        "controlled light. Technical precision is the primary criterion.\n\n"
        "DoD: Score lighting design precision, background and subject tonal "
        "separation, and the technical challenge of rendering garment, skin, "
        "or product at their best simultaneously.\n\n"
        "DM: Score the exact moment of peak expression, pose, or garment movement "
        "within the controlled session.\n\n"
        "Wonder: Score the image's ability to stop the viewer despite the controlled "
        "environment — the expression that transcends the studio setup, the garment "
        "rendered so precisely it becomes sculpture."
    ),

    'fashion_beauty': (
        "This is Fashion photography — sub-type: BEAUTY / DETAIL.\n"
        "Face, cosmetic detail, jewellery, or garment detail as the primary subject. "
        "Extreme technical precision and the revelation of detail are primary.\n\n"
        "DoD: Score lighting precision on skin or material surfaces, focus accuracy "
        "on small detail areas, and the technical challenge of revealing cosmetic "
        "or garment craftsmanship.\n\n"
        "DM: Score the exact focus and light alignment that makes the detail most "
        "completely visible.\n\n"
        "Wonder: Score the revelation — does the detail reveal something about "
        "the craft, the skin, the material that the viewer had not seen before?"
    ),
}

# ── Street sub-genre context blocks ──────────────────────────────────────────

STREET_SUBGENRE_CONTEXT = {

    'street_candid': (
        "This is Street photography — sub-type: SINGLE CANDID SUBJECT.\n"
        "One primary subject, unaware or in an unguarded public moment — anywhere. "
        "Village, market, beach, transit, street. Location is irrelevant. "
        "The photographer found a person and a context that said something together.\n\n"
        "DoD: Score reaction speed, working in difficult or chaotic conditions, and "
        "the physical challenge of being present. PROXIMITY BONUS: Working at "
        "close distance to an unaware subject scores DoD 6.5–7.5.\n\n"
        "DM: Score the unrepeatable instant — expression, gesture, background "
        "alignment all at their peak simultaneously.\n\n"
        "Wonder: Score EYE WONDER primarily — what compositional or contextual "
        "discovery made this image possible? The background element that changes "
        "the meaning, the light that transforms the ordinary face, the accidental "
        "frame. Score 7.5–8.5 when the Eye Wonder discovery is complete and clear.\n"
        "ACCESS WONDER: Score 7.0–8.0 when the subject's face or environment reveals "
        "a world most viewers will not enter."
    ),

    'street_crowd': (
        "This is Street photography — sub-type: CROWD AND COLLECTIVE ENERGY.\n"
        "Multiple subjects, collective energy, public gathering — market, festival, "
        "transport hub, religious event, village celebration. Location is irrelevant.\n\n"
        "DoD: Score the challenge of finding order and narrative within chaos — "
        "the right position, the right moment of collective peak, clean separation "
        "of key subjects from the mass.\n\n"
        "DM: Score the moment of maximum collective energy and narrative coherence — "
        "when the crowd tells a story in a single frame.\n\n"
        "Disruption: Score layered compositions, unexpected geometries within the "
        "crowd, and the use of colour, shadow, or reflection to organise chaos.\n\n"
        "Wonder: EYE WONDER — the compositional find within the crowd that makes "
        "the image more than documentation. Score 7.5–8.5."
    ),

    'street_night': (
        "This is Street photography — sub-type: NIGHT AND LOW LIGHT.\n"
        "Low light, available or artificial illumination, atmosphere after dark — "
        "anywhere. A village fire, a market lamp, city neon. Light source is irrelevant.\n\n"
        "DoD: Score the technical management of low light, high ISO noise, and the "
        "challenge of decisive moments in low visibility conditions.\n\n"
        "DM: Score the moment when light, subject, and atmosphere align.\n\n"
        "Wonder: EYE WONDER from light — unexpected colour, geometry, or atmosphere "
        "created by the available light source."
    ),

    'street_architecture': (
        "This is Street photography — sub-type: ARCHITECTURE AND ENVIRONMENT.\n"
        "Built or natural environment as the primary subject — no human presence "
        "required. A village wall, a temple gate, an industrial structure, a doorway. "
        "Not landscape — the environment as a stage for life.\n\n"
        "DoD: Score compositional precision and timing of the right light.\n\n"
        "DM: Score the moment of optimal light and geometry alignment.\n\n"
        "Wonder: EYE WONDER — geometric discoveries, unexpected scale, or light "
        "behaviour that transforms the familiar environment into something new."
    ),

    'street_market': (
        "This is Street photography — sub-type: MARKET AND COMMERCE.\n"
        "Market, commerce, exchange, trade — anywhere people buy and sell. "
        "Village market, roadside vendor, transit hub shop. Not urban-specific.\n\n"
        "DoD: Score chaos management, difficult light in covered or outdoor market "
        "environments, and the timing of transaction peaks.\n\n"
        "DM: Score the transaction moment — the exchange, the negotiation, "
        "the gesture of commerce.\n\n"
        "Wonder: CULTURAL WONDER and EYE WONDER equally — the market as a window "
        "into how a community lives and trades."
    ),

    'street_transport': (
        "This is Street photography — sub-type: TRANSPORT AND MOVEMENT.\n"
        "Buses, trains, boats, cycles, carts — human movement through any transit "
        "system. Village bus stop, rural train station, city subway. All valid.\n\n"
        "DoD: Score timing within fast-moving transit environments.\n\n"
        "DM: Score the moment of peak human expression within transit — "
        "the departure gesture, the arrival expression, the window portrait.\n\n"
        "Wonder: EYE WONDER from the juxtaposition of human life against the "
        "colour, geometry, and motion of vehicles and transit. Score 7.5–8.5."
    ),

    'street_juxtaposition': (
        "This is Street photography — sub-type: JUXTAPOSITION.\n"
        "The image's meaning comes from an unexpected relationship between two "
        "or more elements — a sign and a gesture, a shadow and its owner, a word "
        "and a face, scale contrast, irony, or visual pun. Anywhere, any subject.\n\n"
        "DoD: Score the photographer's patience and positioning — juxtapositions "
        "require waiting for the right alignment or recognising it in a fraction "
        "of a second. Score 6.5–8.0 depending on complexity of the find.\n\n"
        "DM: Score the exact alignment — the fraction of a second when the "
        "juxtaposition is most complete and most readable.\n\n"
        "Wonder: EYE WONDER is the PRIMARY signal. Score 7.5–9.0 when the "
        "juxtaposition creates genuine surprise, humour, or new meaning. "
        "The DREAMGIRL bus and the elderly woman, the cow shadow on the wall, "
        "the woman framed through the camel neck — these are Wonder 8.5–9.0."
    ),

    'street_reflection': (
        "This is Street photography — sub-type: REFLECTION.\n"
        "Mirrors, water, glass, polished surfaces — reflections that double, "
        "distort, or layer the story. Car windows, shop fronts, puddles, handheld mirrors.\n\n"
        "DoD: Score the compositional precision required to align the reflected "
        "world with the real world into a coherent image. Score 7.0–8.5.\n\n"
        "DM: Score the moment when the reflected and real elements are in their "
        "most complete and most surprising alignment.\n\n"
        "Wonder: EYE WONDER — the discovery of a reflected world that reveals "
        "something the direct view cannot. Score 8.0–9.0 when the reflection "
        "creates genuine visual complexity or surprise."
    ),

    'street_geometry': (
        "This is Street photography — sub-type: GEOMETRY AND LIGHT/SHADOW.\n"
        "Bold shapes, lines, angles, shadows — the graphic structure of the "
        "physical world with human presence. Architecture, shadows, patterns, "
        "light shafts. Village or city, natural or built.\n\n"
        "DoD: Score the timing and positioning required to align the human "
        "element with the geometric structure. Score 6.5–8.0.\n\n"
        "DM: Score the moment when the human and geometric elements are in "
        "their most resolved alignment — the figure at the exact geometric centre, "
        "the shadow at maximum length.\n\n"
        "Wonder: EYE WONDER — geometric discovery. Score 7.5–8.5 when the "
        "compositional structure is original and complete."
    ),

    'street_silhouette': (
        "This is Street photography — sub-type: SILHOUETTE.\n"
        "Subject revealed by shape alone against a bright background — backlit, "
        "against sky, in doorways, against lit surfaces. The absence of detail "
        "creates mystery, graphic power, and universality.\n\n"
        "DoD: Score the exposure precision required to render the silhouette "
        "cleanly while holding background detail, and the timing of the "
        "right gesture or shape.\n\n"
        "DM: Score the gesture or shape at its most readable and most powerful — "
        "the silhouette that tells the story through outline alone.\n\n"
        "Wonder: EYE WONDER — the graphic discovery. Score 7.5–8.5 when the "
        "silhouette creates a shape that is both specific and universal."
    ),
}



# ── Creative sub-genre context blocks ────────────────────────────────────────

CREATIVE_SUBGENRE_CONTEXT = {

    'creative_minimalist': (
        "This is Creative photography — sub-type: MINIMALIST.\n"
        "A real, recognisable subject reduced to its essential form. Negative space "
        "IS the composition. Tonal relationship IS the statement. The creative act "
        "is the reduction — the vision to strip everything away and commit to "
        "simplicity. A swan as geometric punctuation. A lone figure under vast sky. "
        "A single tree in snow. A boat on still water.\n\n"
        "CRITICAL SCORING NOTE: Minimalist images are systematically underscored "
        "when DoD and Disruption are evaluated against conventional criteria. "
        "Apply the following corrections:\n\n"
        "DoD: The compositional DECISION is the difficulty. Finding the exact "
        "relationship between subject, negative space, and tonal field — the "
        "patience to wait for the right geometry, the technical precision to "
        "render white plumage against near-black water without clipping either, "
        "the deliberate choice of angle and focal length that makes the reduction "
        "work — this is DoD 8.0–9.0 for precisely executed minimalist work. "
        "Score 8.5+ when the technical execution serves the reduction perfectly "
        "with no element fighting for attention.\n\n"
        "Disruption: A living subject (animal, person) treated as pure geometric "
        "form goes against EVERY convention of its subject genre. A swan as "
        "geometric study instead of wildlife portrait. A figure as negative space "
        "anchor instead of human subject. This genre violation IS maximum "
        "disruption — score 8.5–9.5. The more completely the reduction breaks "
        "from the expected treatment of that subject, the higher the score.\n\n"
        "DM: Score the exact moment when the subject is in its most resolved "
        "geometric relationship with the frame. Half a second earlier or later "
        "and the geometry changes. For minimalist work, the decisive moment is "
        "the instant of perfect resolution — score 8.0–9.0.\n\n"
        "Wonder: EYE WONDER is the primary signal. Score the transformation of "
        "the familiar into the singular. The swan is everywhere — this image is "
        "not. Score 8.5–9.5 when the reduction reveals something about the "
        "subject that the conventional view cannot. Score 9.0–9.5 for images "
        "that have won or would win international awards — the singular find "
        "that could only exist once, in that light, at that moment.\n\n"
        "AQ: Score the specific emotional register the minimalist reduction creates. "
        "Stillness. Suspension. The space between things. Absence as presence. "
        "Void. Clarity. The image that lingers because it removed everything "
        "except the essential truth. Score 8.5–9.5 when the emotional register "
        "is specific and complete. Score 9.0+ when the feeling is undeniable "
        "and stays with the viewer after they look away.\n\n"
        "AWARD-LEVEL CALIBRATION: International award-winning minimalist work "
        "(WSPA Photographer of Year, Sony World Photography, similar) should "
        "score Grandmaster (9.0+). If the image has: precise technical execution "
        "(DoD 8.5+), genuine genre disruption (Dis 8.5+), perfect geometric "
        "resolution (DM 8.0+), singular Eye Wonder (Wonder 9.0+), and a specific "
        "named emotional register (AQ 9.0+) — the score must reach 9.0+."
    ),

    'creative_graphic': (
        "This is Creative photography — sub-type: GRAPHIC.\n"
        "Strong geometric shapes, bold tonal or colour relationships, architectural "
        "or environmental forms composed as visual design. Real subjects — but the "
        "graphic structure IS the image. Shadow geometry. Bold colour contrast. "
        "Architectural pattern. The image reads as design before it reads as subject.\n\n"
        "DoD: Score the compositional precision required to find and frame the graphic "
        "structure — the exact position that makes the geometry work, the timing of "
        "light that reveals the shape. Score 7.0–9.0 for precisely executed graphic work.\n\n"
        "DM: Score the moment of maximum graphic resolution — when the shapes, "
        "tones, and any human element are in their most complete visual relationship.\n\n"
        "Disruption: Score the visual impact of the graphic statement. Bold, "
        "unexpected, visually arresting — the image that reads from across the room. "
        "Score 8.0–9.5 for strong graphic work that genuinely stops the viewer.\n\n"
        "Wonder: EYE WONDER — the graphic discovery. The shadow pattern that creates "
        "a second subject. The architectural geometry that frames the human. "
        "Score 8.0–9.5 when the graphic find is original, complete, and singular.\n\n"
        "AQ: Score the specific feeling the graphic structure creates — tension, "
        "order, unease, power, clarity. Score 8.5–9.5 when the emotional register "
        "of the graphic statement is specific and undeniable."
    ),

    'creative_fineart': (
        "This is Creative photography — sub-type: FINE ART.\n"
        "Conceptually directed, constructed, or painterly work where the photograph "
        "IS the artwork. Staged, lit, or conceived as a complete artistic statement. "
        "The Old Masters portrait with a modern choker. The surreal constructed scene. "
        "The image that exists because the photographer built it.\n\n"
        "DoD: Score the intellectual and production complexity of the concept — "
        "the research, the construction, the lighting design, the casting, the "
        "technical execution of a pre-visualised image. Score 7.0–9.0 for work "
        "that required significant conception and execution.\n\n"
        "DM: Score the exact frame where the concept is most completely resolved — "
        "where idea and execution align into their strongest single statement.\n\n"
        "Disruption: Score the conceptual originality. Does this image exist in a "
        "visual tradition the viewer recognises, and does it add something new to it? "
        "Art historical quotation, cultural collision, temporal duality — reward "
        "ideas the viewer has not encountered in this exact form.\n\n"
        "Wonder: Score conceptual depth and the world the image creates. Does the "
        "viewer feel both the idea and the image simultaneously? Score 8.0–9.0 "
        "when concept and execution are both fully achieved."
    ),

    'creative_icm': (
        "This is Creative photography — sub-type: ICM AND INTENTIONAL BLUR.\n"
        "Intentional camera movement, panning, or blur as the primary creative "
        "statement. Apply STEP 0 Creative Genre Override fully. "
        "Sharpness is NEVER penalised. Score DoD on technique difficulty and "
        "intentionality. Score Wonder on what the blur reveals that sharpness cannot."
    ),

    'creative_longexp': (
        "This is Creative photography — sub-type: LONG EXPOSURE AND LIGHT TRAILS.\n"
        "Long exposure — silky water, light trails, star trails, movement rendered "
        "as flow. Apply STEP 0 Creative Genre Override fully. DoD on exposure "
        "precision and environmental challenge. Wonder on time revealed."
    ),

    'creative_multiexp': (
        "This is Creative photography — sub-type: MULTIPLE EXPOSURE.\n"
        "Two or more exposures layered — in-camera or in post — as a single "
        "unified statement. DoD on the complexity of the layering decision. "
        "Wonder on what the combination reveals that neither image alone contains."
    ),

    'creative_abstract': (
        "This is Creative photography — sub-type: ABSTRACT AND PATTERN.\n"
        "Subject unrecognisable or irrelevant — pure colour field, pattern, "
        "texture, or form. The image is not about what it depicts but what it IS. "
        "DoD on the compositional decision and technical precision. "
        "Wonder on the visual experience created."
    ),

    'creative_astro': (
        "This is Creative photography — sub-type: ASTROPHOTOGRAPHY.\n"
        "Night sky, Milky Way, star trails, lunar, planetary. Apply STEP 0 "
        "Creative Genre Override. DoD on dark sky access, technical precision, "
        "and foreground planning. Wonder on scale revelation."
    ),

    'creative_silhouette': (
        "This is Creative photography — sub-type: SILHOUETTE.\n"
        "Subject revealed by shape alone. Apply STEP 0. DoD on exposure precision "
        "and timing of the right gesture. Wonder on EYE WONDER — the shape "
        "that is both specific and universal."
    ),
}


def get_genre_context(genre, sub_genre=None):
    """
    Returns the genre context string for the scoring prompt.
    Routes to sub-type-specific context blocks for all genres with sub-types.
    _other sub-genres fall back to generic genre context — no sub-type penalty.
    """
    # _other sub-genres always fall back to generic genre context
    if sub_genre and sub_genre.endswith('_other'):
        return GENRE_CONTEXT.get(genre, GENRE_CONTEXT['default'])
    # Cross-genre sub-types: apply the correct rubric regardless of filed genre
    # lifestyle_intimate can be filed under Documentary, People, or Street
    if sub_genre == 'lifestyle_intimate':
        return PEOPLE_SUBGENRE_CONTEXT.get('lifestyle_intimate', GENRE_CONTEXT.get(genre, GENRE_CONTEXT['default']))
    if genre == 'People' and sub_genre and sub_genre in PEOPLE_SUBGENRE_CONTEXT:
        return PEOPLE_SUBGENRE_CONTEXT[sub_genre]
    if genre == 'Wildlife' and sub_genre and sub_genre in WILDLIFE_SUBGENRE_CONTEXT:
        return WILDLIFE_SUBGENRE_CONTEXT[sub_genre]
    if genre == 'Nature' and sub_genre and sub_genre in NATURE_SUBGENRE_CONTEXT:
        return NATURE_SUBGENRE_CONTEXT[sub_genre]
    if genre == 'Documentary' and sub_genre and sub_genre in DOCUMENTARY_SUBGENRE_CONTEXT:
        return DOCUMENTARY_SUBGENRE_CONTEXT[sub_genre]
    if genre == 'Macro' and sub_genre and sub_genre in MACRO_SUBGENRE_CONTEXT:
        return MACRO_SUBGENRE_CONTEXT[sub_genre]
    if genre == 'Fashion' and sub_genre and sub_genre in FASHION_SUBGENRE_CONTEXT:
        return FASHION_SUBGENRE_CONTEXT[sub_genre]
    if genre == 'Street' and sub_genre and sub_genre in STREET_SUBGENRE_CONTEXT:
        return STREET_SUBGENRE_CONTEXT[sub_genre]
    if genre == 'Creative' and sub_genre and sub_genre in CREATIVE_SUBGENRE_CONTEXT:
        return CREATIVE_SUBGENRE_CONTEXT[sub_genre]
    return GENRE_CONTEXT.get(genre, GENRE_CONTEXT['default'])


# ── Two-call vision architecture ──────────────────────────────────────────────
# Call 1 (VISION): Model describes what it actually sees — subjects, behaviour,
#                  prey, interactions. Returns structured JSON. No scoring.
# Call 2 (SCORE):  Model scores using Call 1's scene description as ground truth.
#                  Cannot contradict the verified scene description.
# This prevents the model pattern-matching to "bird at water = takeoff" without
# looking at the image — the scene description is injected as fact into scoring.

VISION_SYSTEM = """
You are a precise visual analyst for a wildlife photography platform.
Your only job is to describe exactly what you see in the image.
Do NOT score, evaluate, or give feedback.
Do NOT infer or assume — only describe what is clearly visible.
If something is ambiguous or partially obscured, say so explicitly.
Respond ONLY with a valid JSON object. No preamble, no markdown.
"""

VISION_PROMPT = """Examine this photograph carefully. Scan the ENTIRE frame including:
- Background, midground, and foreground
- Shadow areas and dark regions
- Edges and corners
- Any partially visible subjects

Answer each question based ONLY on what you can actually see:

1. How many distinct subjects are in the frame? List each one.
2. For each subject: what species/type is it (use the precise common name — e.g. "Great Cormorant", "Indian Kingfisher", "Spotted Deer" — not just "bird" or "animal"), where is it in the frame, and what is it doing?
3. Is any subject carrying, holding, or in contact with prey? If yes: describe the prey (species, size, position).
4. Are any subjects in physical contact with each other? If yes: describe the contact.
5. What behavioural act is in progress? (predation, conflict, display, takeoff, landing, feeding, roosting, transit — pick the most specific one that applies)
6. Is there any object in any subject's bill, talons, or mouth? Describe it precisely.
7. What is the lighting condition? (backlit, frontlit, sidelit, overcast)
8. Is the primary subject sharp or soft?
9. Is there any evidence the animal is captive? Look for: cage bars or mesh, enclosure walls, zoo signage, unnatural substrate (concrete, artificial grass), feeding troughs, unnaturally tame proximity to humans, identification tags or collars. Answer yes/no and describe evidence if present.

SUB-GENRE DETECTION — examine the image's PRIMARY creative structure and select the
most accurate sub-genre from the list below. This overrides the photographer's selection
when they have filed under a generic or incorrect sub-type. Be precise — the sub-genre
determines which scoring rubric is applied.

CREATIVE sub-genres:
  creative_minimalist — single recognisable subject in large negative space; tonal
    relationship IS the statement; the reduction IS the creative act. A swan as
    geometric form. A lone figure under vast sky. Subject clearly identifiable but
    stripped of context.
  creative_graphic — bold geometric shapes, strong tonal contrast, shadow patterns,
    architectural forms as pure visual design. The image reads as design before subject.
  creative_fineart — constructed, staged, or conceptually directed work. The photograph
    was built, not found.
  creative_icm — intentional camera movement; consistent directional blur across frame.
  creative_longexp — long exposure: silky water, light trails, star trails.
  creative_multiexp — multiple exposures layered as single statement.
  creative_abstract — subject unrecognisable; pure colour, pattern, or texture.
  creative_astro — night sky, Milky Way, star trails, lunar.
  creative_silhouette — subject revealed by shape only; background pure tone.
  creative_other — does not fit any above.

WILDLIFE sub-genres (select when genre is Wildlife):
  wildlife_bird_inflight — bird captured in flight, wings spread or mid-wingbeat
  wildlife_bird_behaviour — specific behaviour: predation, feeding, display, conflict
  wildlife_bird_portrait — bird static; perched, resting, or standing
  wildlife_mammal_action — mammal in motion, predation, or conflict
  wildlife_mammal_portrait — mammal static; environmental portrait
  wildlife_reptile — reptile or amphibian as primary subject
  wildlife_underwater — underwater subject
  wildlife_insect — insect or spider as primary subject
  wildlife_other — does not fit above

STREET sub-genres (select when genre is Street):
  street_candid — spontaneous human moment; no awareness of camera
  street_crowd — multiple figures; crowd energy or density is the subject
  street_geometry — architectural lines, shadows, urban geometry; human may be absent
  street_juxtaposition — two elements in unexpected visual relationship
  street_reflection — reflections in glass, water, or mirrors as primary element
  street_silhouette — figure(s) as silhouette against light source
  street_market — market, vendor, or commercial transaction
  street_transport — vehicles, transit, movement
  street_night — night street; artificial light as primary element
  street_other — does not fit above

PEOPLE sub-genres (select when genre is People):
  portrait_candid — unposed; subject unaware or caught in natural moment
  portrait_posed — subject aware and posed; cooperative portrait
  portrait_cultural — subject's cultural identity, dress, or context is primary
  lifestyle_environmental — person in their environment; context is the story
  lifestyle_intimate — diary/documentary; trust and access are primary

DOCUMENTARY sub-genres (select when genre is Documentary):
  doc_social — daily life in social or economic hardship
  doc_environment — environmental crisis, pollution, ecological damage
  doc_community — community life, ritual, celebration
  doc_health — medical, health crisis, caregiving
  doc_crisis — emergency, disaster, conflict
  doc_other — does not fit above

For all other genres (Landscape, Nature, Wedding, Macro, Drone, Fashion) return the
most specific matching sub-genre, or null if genuinely unclear.

Return this exact JSON:
{
  "subject_count": <integer>,
  "subjects": [
    {
      "type": "<species or description>",
      "position": "<where in frame>",
      "action": "<what it is doing>",
      "carrying_prey": <true|false>,
      "prey_description": "<describe if present, else null>",
      "in_contact_with_other": <true|false>
    }
  ],
  "behavioural_act": "<most specific act: predation|conflict|display|takeoff|landing|feeding|roosting|transit|unknown>",
  "physical_contact_between_subjects": <true|false>,
  "object_in_bill_or_talons": "<describe precisely, or null if none>",
  "lighting": "<backlit|frontlit|sidelit|overcast|mixed>",
  "primary_subject_sharp": <true|false>,
  "scene_summary": "<2-3 sentences describing exactly what is happening in the image>",
  "captive_indicators": "<describe any evidence of captivity — cage, enclosure, zoo, tags — or null if none>",
  "is_captive": <true if any captive indicators present, else false>,
  "species_id": "<precise common name of the primary subject species — e.g. 'Great Cormorant', 'Indian Kingfisher', 'Bengal Tiger'. Use 'Unknown' if genuinely unidentifiable.>",
  "suggested_subgenre": "<most accurate sub-genre id from the lists above — e.g. 'creative_minimalist', 'wildlife_bird_behaviour', 'street_candid'. null if genre is Landscape/Nature/Wedding/Macro/Drone/Fashion and no clear sub-genre match.>",
  "suggested_subgenre_reason": "<one sentence: what specific visual evidence leads to this sub-genre. e.g. 'Single swan in 60% negative space with tonal relationship as primary compositional statement.'>"
}
"""


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


def vision_analyse(img_data: str, media_type: str, title: str, subject: str) -> dict:
    """
    Call 1 of the two-call architecture.
    Sends the image to the API with a pure description prompt — no scoring.
    Returns a dict with scene description facts (subjects, behaviour, prey, contact).
    Falls back to an empty dict on any failure — scoring proceeds without it
    rather than blocking entirely.
    """
    prompt = VISION_PROMPT
    # Inject title and subject as hints — not as constraints
    if title or subject:
        hint = f"\nImage title: {title or 'Not provided'}. Subject field: {subject or 'Not provided'}.\nUse these as hints only — do not assume they are accurate. Describe what you actually see."
        prompt = prompt + hint

    payload = {
        "model":       VISION_MODEL,
        "max_tokens":  1200,
        "temperature": 0.1,
        "system":      VISION_SYSTEM,
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

    try:
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
            print(f"[vision_analyse] API error {response.status_code} — scoring will proceed without scene description")
            return {}
        content = response.json()
        text = ""
        for block in content.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
        text = re.sub(r"```json|```", "", text).strip()
        result = json.loads(text)
        print(f"[vision_analyse] Scene: {result.get('behavioural_act','?')} | Subjects: {result.get('subject_count','?')} | Contact: {result.get('physical_contact_between_subjects','?')} | Bill/talons: {result.get('object_in_bill_or_talons','?')} | SubGenre: {result.get('suggested_subgenre','?')}")
        return result
    except Exception as e:
        print(f"[vision_analyse] Failed ({e}) — scoring will proceed without scene description")
        return {}


def build_scene_context(vision: dict, genre: str = "") -> str:
    """
    Converts the vision_analyse() result into a ground-truth block
    injected into the scoring prompt. The scorer cannot contradict this.
    Returns empty string if vision dict is empty (fallback path).
    """
    if not vision:
        return ""

    subjects = vision.get("subjects", [])
    subject_lines = []
    for i, s in enumerate(subjects, 1):
        line = f"  Subject {i}: {s.get('type','unknown')} — {s.get('action','unknown')}"
        if s.get("carrying_prey"):
            line += f" — CARRYING PREY: {s.get('prey_description','unspecified')}"
        if s.get("in_contact_with_other"):
            line += " — IN CONTACT WITH ANOTHER SUBJECT"
        subject_lines.append(line)

    bill = vision.get("object_in_bill_or_talons")
    contact = vision.get("physical_contact_between_subjects", False)
    act = vision.get("behavioural_act", "unknown")
    summary = vision.get("scene_summary", "")

    species_id = vision.get("species_id", "")

    lines = [
        "VERIFIED SCENE DESCRIPTION — GROUND TRUTH (do not contradict this):",
        f"Subject count: {vision.get('subject_count', 'unknown')}",
    ]
    if species_id and species_id.lower() != "unknown":
        lines.append(f"Primary subject species: {species_id}")
        lines.append(f"- Use this species name in all text fields (hard_truth, mentor_technical, mentor_moment, mentor_next, bylines).")
        lines.append(f"- Do NOT write generic terms like 'the bird' or 'the animal' when the species is known.")
    lines.extend(subject_lines)
    lines.append(f"Behavioural act: {act}")
    lines.append(f"Physical contact between subjects: {'YES' if contact else 'NO'}")
    if bill:
        lines.append(f"Object in bill/talons: {bill}")
    else:
        lines.append("Object in bill/talons: none visible")
    lines.append(f"Scene summary: {summary}")
    lines.append("")
    lines.append("SCORING RULES BASED ON SCENE DESCRIPTION:")
    if contact:
        lines.append("- Two subjects in physical contact are present. DM must reflect the conflict/interaction peak, not generic motion.")
        lines.append("- Wonder must score the inter-subject behavioural rarity, not single-subject action.")
        lines.append("- DO NOT describe this as a single-subject takeoff or suggest 'waiting for a second bird' — a second subject IS present.")
    if bill:
        lines.append(f"- Prey/object is present in bill/talons: {bill}. This is a predation/feeding moment.")
        lines.append("- DM must score the catch/feeding freeze, not a generic water exit.")
        lines.append("- Wonder must reflect predation behavioural rarity, not common takeoff behaviour.")
    if act in ("conflict", "predation", "display"):
        lines.append(f"- Behavioural act confirmed as: {act.upper()}. Score DM and Wonder relative to this act.")

    # Captive/zoo detection
    is_captive = vision.get("is_captive", False)
    captive_indicators = vision.get("captive_indicators")
    if is_captive and captive_indicators:
        lines.append("")
        lines.append("CAPTIVE SUBJECT DETECTED:")
        lines.append(f"- Evidence: {captive_indicators}")
        lines.append("- DoD MUST be penalised — captive access is not equivalent to wild access.")
        lines.append("- Score text MUST explicitly note the captive context.")
        lines.append("- Wonder MUST reflect that wildness and access difficulty are absent.")
        lines.append("- Do NOT score as if this is a wild encounter.")

    # ── Street genre mismatch gate ────────────────────────────────────────────
    # If the photographer submitted as Street but vision detects no human
    # presence, the Street rubric (DM=20%, Wonder=25% weighted to emotional truth)
    # will systematically undervalue the image. Detect this and override.
    if genre and genre.lower() == "street":
        _human_terms = {
            "person", "people", "man", "woman", "child", "boy", "girl",
            "human", "pedestrian", "crowd", "figure", "photographer",
            "vendor", "worker", "commuter", "cyclist", "rider",
        }
        subject_types = [str(s.get("type", "")).lower() for s in subjects]

        def _positive_human(text):
            """True if a human term appears in text and is not negated."""
            for term in _human_terms:
                pattern = r'\b' + term + r'\b'
                for m in re.finditer(pattern, text):
                    ctx = text[max(0, m.start() - 20):m.start()]
                    if not re.search(r'\b(?:no|without|absent|empty)\s*$', ctx.strip()):
                        return True
            return False

        has_human = (
            any(_positive_human(t) for t in subject_types) or
            _positive_human(summary.lower())
        )

        if not has_human:
            lines.append("")
            lines.append("GENRE MISMATCH DETECTED — STREET WITHOUT HUMAN PRESENCE:")
            lines.append("- Vision analysis confirms NO human subjects in this image.")
            lines.append("- The Street rubric (human narrative, decisive urban moment, social context)")
            lines.append("  does not apply to this image. Scoring against it will produce a false low.")
            lines.append("- OVERRIDE: Score DM and Wonder against Creative/atmospheric rubric instead:")
            lines.append("  DM — score the quality of the compositional decision and the moment of")
            lines.append("       atmospheric or structural peak, not the absence of a human moment.")
            lines.append("  Wonder — score visual impact, sculptural quality, and the image's power")
            lines.append("           to stop the viewer, not human emotional narrative.")
            lines.append("- DoD and AQ: score normally — no change.")
            lines.append("- Disruption: reward images that break from convention in their genre.")
            lines.append("- DO NOT penalise this image for lacking a human story.")
            lines.append("- DO NOT suggest the photographer missed a human moment.")
            lines.append("- The NEXT field may note the genre label and suggest Documentary (City Systems or")
            lines.append("  Environment) or Creative as a better fit — but frame it as an opportunity, not a mistake.")
            lines.append("  Do not say the genre cost them points or capped the score.")

    return "\n".join(lines)


def auto_score(image_path, genre, title, photographer, subject="", location="", sub_genre=None):
    """
    Score an image using the Apex DDI Engine.

    sub_genre: optional sub-type id (e.g. 'portrait_cultural') — used to inject
               sub-type-specific rubric context for DM, DoD, and WF scoring.
               Currently active for People genre only; ignored for all others.
               Values must match VALID_SUBGENRES in engine/scoring.py.
    """
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    img_data, media_type = encode_image(image_path)

    # ── Call 1: Vision analysis — identify scene facts before scoring ──────────
    # This prevents the scorer from hallucinating scene content (e.g. describing
    # a two-bird conflict as a single-bird takeoff). The scene description is
    # injected as verified ground truth into the scoring prompt.
    vision        = vision_analyse(img_data, media_type, title, subject)
    scene_context = build_scene_context(vision, genre=genre)

    # ── Sub-genre auto-routing ─────────────────────────────────────────────────
    # Use vision's detected sub-genre to override the photographer's selection.
    # This ensures the correct rubric is always applied regardless of what the
    # photographer filed. The photographer's selection is kept as a hint only.
    # Priority: vision detection > photographer selection > None
    vision_subgenre = vision.get('suggested_subgenre') or None
    if vision_subgenre and vision_subgenre in VALID_SUBGENRES:
        effective_subgenre = vision_subgenre
        if vision_subgenre != sub_genre:
            print(f"[auto_score] Sub-genre override: photographer={sub_genre!r} → engine={vision_subgenre!r} ({vision.get('suggested_subgenre_reason','')[:60]})")
    else:
        effective_subgenre = sub_genre

    calibration_block = get_calibration_examples(genre)
    correction_block  = get_calibration_notes(genre)

    prompt = SCORE_PROMPT.format(
        genre                = genre,
        photographer         = photographer,
        title                = title,
        subject              = subject or "Not specified",
        location             = location or "Not specified",
        genre_context        = get_genre_context(genre, sub_genre=effective_subgenre),
        scene_context        = scene_context,
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

    # Attach routing metadata so build_audit_data and callers can access it
    result['_effective_subgenre']        = effective_subgenre
    result['_photographer_subgenre']     = sub_genre
    result['_subgenre_overridden']       = (vision_subgenre and vision_subgenre != sub_genre and vision_subgenre in VALID_SUBGENRES)
    result['_vision_subgenre_reason']    = vision.get('suggested_subgenre_reason', '')

    return result


def _species_display(species_id):
    """
    Convert a full vision species ID to a display-safe common family name.
    Rules (Session 37 spec):
      - Gate: return None if species_id is empty, generic, or uncertain
      - Display: strip leading adjectives to return family common name only
        e.g. "Great Cormorant" → "Cormorant"
             "Indian Kingfisher" → "Kingfisher"
             "Bengal Tiger" → "Tiger"
             "Spotted Deer" → "Deer"
      - Never show Latin binomials or subspecies strings
    """
    if not species_id:
        return None

    # Gate: uncertain / generic terms — hide card entirely
    _generic = {
        'bird', 'birds', 'animal', 'animals', 'plant', 'plants',
        'unknown', 'unidentified', 'unidentifiable', 'creature',
        'insect', 'fish', 'mammal', 'reptile', 'amphibian',
        'object', 'subject', 'wildlife', 'nature', 'null', 'none',
    }
    _lower = species_id.strip().lower()
    if _lower in _generic:
        return None
    # Also gate on very short strings (< 4 chars) and anything with Latin format (Genus species)
    import re as _re
    if len(_lower) < 4:
        return None
    if _re.match(r'^[A-Z][a-z]+ [a-z]+$', species_id.strip()):
        # Looks like a Latin binomial — do not show
        return None

    # Extract family common name: take the LAST capitalised word
    # "Great Indian Hornbill" → "Hornbill"
    # "Indian Kingfisher" → "Kingfisher"
    # "Bengal Tiger" → "Tiger"
    # "Flamingo" → "Flamingo" (already family name)
    words = species_id.strip().split()
    # Find last meaningful capitalised word
    family = words[-1] if words else species_id
    # Handle possessives / trailing punctuation
    family = family.rstrip('.,;:)')
    return family if family else None


def build_audit_data(result, image_obj):
    genre      = image_obj.genre or "Wildlife"
    sub_genre  = getattr(image_obj, 'sub_genre', None) or ""
    fmt        = image_obj.format or "JPEG"
    subject    = image_obj.subject or ""
    location   = image_obj.location or ""

    # Use engine-detected sub-genre for display if it overrode photographer's selection
    effective_subgenre   = result.get('_effective_subgenre') or sub_genre
    subgenre_overridden  = result.get('_subgenre_overridden', False)
    vision_subgenre_reason = result.get('_vision_subgenre_reason', '')

    display_subgenre = effective_subgenre or sub_genre
    genre_tag_label  = f"{genre.upper()}  ·  {display_subgenre.replace('_', ' ').upper()}" if display_subgenre else genre.upper()

    return {
        "asset":                image_obj.asset_name or "Untitled",
        "meta":                 f"{genre}  ·  {fmt}  ·  {subject}  ·  {location}",
        "score":                str(result.get("score", 0)),
        "tier":                 result.get("tier", "Practitioner"),
        "dec":                  result.get("archetype", "Sovereign Momentum"),
        "credit":               image_obj.photographer_name or "",
        "genre_tag":            f"{genre_tag_label}  ·  {fmt.upper()}",
        "soul_bonus":           result.get("soul_bonus", False),
        "composition_technique": result.get("composition_technique", "NONE"),
        "iucn_tag":             result.get("iucn_tag"),
        "hard_truth":           result.get("hard_truth", ""),
        "species_id":           result.get("species_id", ""),
        "species_display":      _species_display(result.get("species_id", "")),
        "edit_base":            result.get("edit_base", ""),
        "edit_creative":        result.get("edit_creative", ""),
        "genre_suggestion":     result.get("genre_suggestion", None),
        "effective_subgenre":   effective_subgenre,
        "subgenre_overridden":  subgenre_overridden,
        "vision_subgenre_reason": vision_subgenre_reason,
        "modules": [
            ("DoD",        result.get("dod", 0)),
            ("Disruption", result.get("disruption", 0)),
            ("DM",         result.get("dm", 0)),
            ("Wonder",     result.get("wonder", 0)),
            ("AQ",         result.get("aq", 0)),
        ],
        "rows": [
            ("Technical",  result.get("mentor_technical", "")),
            ("Moment",     result.get("mentor_moment", "")),
            ("Next",       result.get("mentor_next", "")),
        ],
        "byline_1":      result.get("byline_1", ""),
        "byline_2_body": result.get("byline_2", ""),
        "badges_g":      result.get("badges_g", []),
        "badges_w":      result.get("badges_w", []),
    }
