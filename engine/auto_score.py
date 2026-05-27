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
- NEVER open with observation. Open with the gap, the cost, or the fix.
- Every sentence must either name a problem the photographer did not know they had, OR tell them exactly what to do about it.
- If a field has no actionable content, return null — do not fill space.
- UNCERTAIN SUBJECT RULE: If the scene description flags any element as uncertain or unidentified, do NOT reference that element in mentor_technical, mentor_moment, mentor_next, byline_1, byline_2, or hard_truth. Build the analysis around what is definitively known. A wrong identification is worse than a null field.
- Write as a mentor talking to a photographer peer — direct, no hedging.
- BANNED phrases: "the image demonstrates", "this photograph shows", "the composition features", "the subject is positioned", "the technique showcases", "the exposure captures", "the scene reveals", "the frame contains".
- BAD: "The river carves an S-curve through the valley floor that pulls the eye from foreground to the vanishing point." — this is description. The photographer can see the river.
- GOOD: "The right-side peak is 30% heavier than the left — move your frame left until the river exit sits at the right third and the weight balances." — this is a diagnosis and a fix.
- BAD: "The monochrome conversion removes colour information." — observation, not diagnosis.
- GOOD: "Monochrome was the wrong call here — the colour temperature difference between the haze layers was the only thing separating them, and conversion collapsed three depth planes into one." — this is what it cost.

CRITICAL — EQUIPMENT AND EXIF ACCURACY:
The EXIF data is provided with the image. Read it carefully before writing any text.
- If the camera make/model is a smartphone (iPhone, Samsung Galaxy, Pixel, Xiaomi, OnePlus etc.) NEVER describe the capture method as "drone", "aerial vehicle", "UAV", or "shot from a drone". It is a handheld or elevated mobile shot. Only reference drone/aerial if EXIF explicitly confirms a drone camera (DJI, Autel, Parrot etc.).
- Do not assume subject matter or objects that are not clearly visible. If you see a colour boundary, describe it as a colour boundary — not a road unless you can clearly see it is a road.
- Do not identify technical flaws (lens flare, dust, noise) unless you can clearly see them. A small coloured element may be part of the scene, not a flare. Describe what you see, not what you assume.
- CRITICAL — small white or light objects at distance or in aerial shots: do NOT assume these are birds, animals, or wildlife. A small white speck could be a feather, debris, a boat, a vehicle, a person, or any other object. If you cannot clearly identify the object with confidence, label it as "unidentified object" or "possible [x] — uncertain" in your scene description. NEVER build scoring rationale or text fields around an uncertain identification.
- If subject identity is uncertain: score MOMENT and set mentor_moment to null. Do not build mentor_next around an uncertain element. Score what is certain in the frame.
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
  "hard_truth": "<ONE sentence. What this image IS — the single thing that makes or breaks it. Start with the verdict, not the scene. Never open with description of what is visible. BAD: 'The atmospheric layering and winding river create depth, but the monochrome conversion flattens tonal separation.' GOOD: 'Monochrome killed the depth — the colour temperature gap between the haze layers was the only separation between three planes, and conversion collapsed them.' Never start with 'This image' or 'The photograph'.>",
  "mentor_technical": "<ONE sentence. Name the technical gap and what it cost — or, if technically clean, name the one decision that made it work. Never describe what is visible. Never open with observation. Start with the gap or the win. Example of gap: 'Exposure pushed half a stop too bright — highlights on the primary wing feathers are gone and cannot be recovered.' Example of win: 'ISO held at 1600 with a shutter fast enough to freeze the primary — the gamble paid.' If there is no actionable technical point, omit this field entirely (return null).>",
  "mentor_moment": "<ONE sentence. Was this the right frame? If yes, say exactly why this instant and not the one before or after. If no, name the specific frame that was the shot. Never explain what a decisive moment is. Never say 'there is no peak action'. Example of right frame: 'Wingbeat at the top of the arc with the eye catching light — half a second earlier and the wing blocks the face.' Example of wrong frame: 'The bill has cleared the water here — the shot was the entry, when the spray was still rising.' If moment is irrelevant to the genre, omit (return null).>",
  "mentor_next": "<TWO sentences MAX. First sentence: the field fix — what to do differently at the point of capture (position, timing, light, distance, angle). Second sentence: the processing fix — one specific adjustment that would change the read of this image (not generic; name the tool or method). This replaces The One Improvement and the Edit Guide as a single unified block. Example: 'Get lower — eye level with the subject removes the downward angle that flattens the depth. In post, pull the highlights on the water surface down 40 points to recover the reflection detail that anchors the foreground.' If only a field fix applies, one sentence is enough. Never give generic advice.>",
  "byline_1": "<ONE sentence. What specifically holds this image from the next tier — name the exact gap, not a description of what is there. Start with the problem, not the scene. BAD: 'The incoming bird placement is slightly high.' GOOD: 'The incoming bird floats outside the geometric connection — drop it to the lower third and the composition locks.' Never describe what is visible.>",
  "byline_2": "<THE ONE IMPROVEMENT. One specific, physical action — in the field or in processing. Name the exact move, not the problem. BAD: 'Wait for better light.' GOOD: 'Shoot this at golden hour from the ridge to the east — the low side-light will separate the valley floor from the peaks without needing monochrome.' Never use generic advice. Never describe what the image does.>",
  "badges_g": ["<specific strength visible in this image>", "<specific strength>", "<specific strength>"],
  "badges_w": ["<specific gap in this image>", "<specific gap>", "<specific gap>"],
  "iucn_tag": "<IUCN status if applicable, else null>",
  "ai_suspicion": <float 0.0-1.0>,
  "ai_suspicion_reason": "<concise reason if ai_suspicion >= 0.5, else null>",
  "species_id": "<For Wildlife and Nature genres only: carry forward the precise common name of the primary subject from the verified scene description. Use exactly the same name. If not identified with certainty, null. For Creative, Drone, Landscape, Street, and People genres: always null — do not attempt species identification.>",
  "edit_base":     "<BASE EDITS — post-processing only. Name the specific adjustments: white balance correction, local exposure/contrast, dodging/burning, colour grading within the original scene's palette. Tool-specific where possible (radial filter, graduated filter, HSL panel). 1-2 sentences.>",
  "edit_creative": "<CREATIVE EDITS — artistic, heavy editing permitted. Generative removal, major colour grade, composite elements, heavy vignette, stylistic transformation. What would make this image an entirely different, stronger statement. 1-2 sentences.>"
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
        "STRENGTHS, not indicators of a posed or less-valuable moment. "
        "The subject being aware of the camera is NOT a deduction in this sub-type. "
        "Cultural documentary work operates by different rules than street candid — "
        "the decisive moment is the one where subject and environment are in complete accord.\n\n"
        "WF: Score cultural resonance. Does this image create the feeling of genuine "
        "encounter with a world the viewer might not otherwise access? "
        "Ethnographic gravity, cultural specificity, and the sense that this moment "
        "could only have been made by a photographer with real access — all count."
    ),
    'portrait_candid': (
        "This is People photography — sub-type: PORTRAIT (CANDID / STREET).\n"
        "The defining quality is the unguarded moment — subject unaware, or caught "
        "in a real, unrepeatable expression of self. Timing is the primary criterion.\n\n"
        "DoD: Score sharpness on a potentially moving subject, background separation "
        "achieved in uncontrolled ambient light, and the physical challenge of working "
        "fast in unpredictable conditions.\n\n"
        "DM: Score the unrepeatable instant. The peak moment where expression, gesture, "
        "and background alignment all converge. A half-second either side is lesser. "
        "This is the sub-type where traditional decisive moment scoring applies fully — "
        "reward the photograph that could not have been made a frame earlier or later.\n\n"
        "WF: Score surprise — did the photographer catch something that could not have "
        "been staged? The best candid portraits show the viewer something they could not "
        "have planned. Unexpected gesture, rare expression, environmental coincidence — "
        "the wonder is the world revealing itself."
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


def get_genre_context(genre, sub_genre=None):
    """
    Returns the genre context string for the scoring prompt.
    For People images with a valid sub_genre, returns the sub-type-specific
    context block instead of the generic People context.
    For Wildlife images with a valid sub_genre, returns the sub-type-specific
    context block instead of the generic Wildlife context.
    Falls back to generic genre context for unknown or missing sub_genre.
    """
    if genre == 'People' and sub_genre and sub_genre in PEOPLE_SUBGENRE_CONTEXT:
        return PEOPLE_SUBGENRE_CONTEXT[sub_genre]
    if genre == 'Wildlife' and sub_genre and sub_genre in WILDLIFE_SUBGENRE_CONTEXT:
        return WILDLIFE_SUBGENRE_CONTEXT[sub_genre]
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
  "species_id": "<precise common name of the primary subject species — e.g. 'Great Cormorant', 'Indian Kingfisher', 'Bengal Tiger'. Use 'Unknown' if genuinely unidentifiable.>"
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
        "max_tokens":  600,
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
        print(f"[vision_analyse] Scene: {result.get('behavioural_act','?')} | Subjects: {result.get('subject_count','?')} | Contact: {result.get('physical_contact_between_subjects','?')} | Bill/talons: {result.get('object_in_bill_or_talons','?')}")
        return result
    except Exception as e:
        print(f"[vision_analyse] Failed ({e}) — scoring will proceed without scene description")
        return {}


def build_scene_context(vision: dict) -> str:
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
    vision       = vision_analyse(img_data, media_type, title, subject)
    scene_context = build_scene_context(vision)

    calibration_block = get_calibration_examples(genre)
    correction_block  = get_calibration_notes(genre)

    prompt = SCORE_PROMPT.format(
        genre                = genre,
        photographer         = photographer,
        title                = title,
        subject              = subject or "Not specified",
        location             = location or "Not specified",
        genre_context        = get_genre_context(genre, sub_genre=sub_genre),
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

    return result


def build_audit_data(result, image_obj):
    genre      = image_obj.genre or "Wildlife"
    sub_genre  = getattr(image_obj, 'sub_genre', None) or ""
    fmt        = image_obj.format or "JPEG"
    subject    = image_obj.subject or ""
    location   = image_obj.location or ""

    genre_tag_label = f"{genre.upper()}  ·  {sub_genre.replace('_', ' ').upper()}" if sub_genre else genre.upper()

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
        "edit_base":            result.get("edit_base", ""),
        "edit_creative":        result.get("edit_creative", ""),
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
