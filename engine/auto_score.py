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
  "row_technical": "<1-2 sentences MAX. State the one technical decision that defines this image — name it precisely, no buildup, no category labels. If it worked say why; if it didn't say what it cost. Example: 'High-key exposure held just below blowout — feather detail survives where most photographers would have blown it.' Never say 'the technique demonstrates' or 'the execution shows'. Write like a photographer talking to another photographer.>",
  "row_geometric": "<1-2 sentences MAX. Name what the composition DOES, not what it contains. Start with the structure, end with whether it works. Example: 'The birds stack into a diagonal that pulls toward the gap in the upper right — the composition is unresolved until that gap closes.' Never say 'the subject is positioned' or describe what is visible. Say what the geometry is doing.>",
  "row_dm": "<1-2 sentences MAX. Was this the right moment? Answer directly — yes or no — then name what the better moment would have been or confirm this was it. Example: 'This is the right frame — the wingbeat frozen at the top of the arc. A half-second either side and the geometry collapses.' Never explain what a decisive moment is. Never say 'there is no peak action'. Just say what this moment is or isn't.>",
  "row_wonder": "<1-2 sentences MAX. If something is genuinely rare or surprising, name it and say why in one line. If nothing is, say so cleanly. Example: 'Colony behaviour in high-key monochrome is uncommon — the restraint is the wonder.' Never spend three sentences explaining an absence. One honest line is enough.>",
  "row_aq": "<1-2 sentences MAX. Name the exact feeling this image creates — not its subject, not its technique, the feeling. Be precise and direct. Example: 'Serene but kinetic — the blur on the foreground bird creates unresolved tension against the stillness behind it.' Never say 'the image evokes' or 'the viewer experiences'. Say what it feels like, as if you are standing in front of it.",
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
    'bird_in_flight': (
        "This is Wildlife photography — sub-type: BIRD IN FLIGHT.\n"
        "The primary challenge is freezing motion at the peak of the flight arc "
        "with accurate focus on the eye and primary feathers.\n\n"
        "DoD: Score shutter speed precision, tracking accuracy at speed, and "
        "exposure management on a fast-moving subject against variable backgrounds "
        "(sky, water, foliage). Wing extension at full spread, primary feather "
        "separation visible, and eye sharp are the three DoD gold standards.\n\n"
        "DM: Score the peak of the flight arc — the single frame where wing "
        "geometry is most resolved, the bird's body axis is cleanest, and the "
        "relationship to the background is strongest. A half-frame earlier or "
        "later produces a lesser image. IDENTIFY whether this is pure flight or "
        "a behavioural act (landing approach, prey strike, territorial display) — "
        "behavioural flight peaks score higher than generic transit.\n\n"
        "WF: Score species rarity, behaviour rarity, and light quality. Common "
        "garden birds in flat light score lower than rare species, unusual "
        "plumage states, or flight captured in exceptional light. The wonder is "
        "in the combination of access, timing, and conditions — not motion alone."
    ),
    'bird_behaviour': (
        "This is Wildlife photography — sub-type: BIRD PREDATION / BEHAVIOUR.\n"
        "A behavioural act is in progress — predation, feeding, display, conflict, "
        "courtship, or nesting. The decisive moment is defined by THAT ACT, not "
        "by generic motion or composition.\n\n"
        "DoD: Score the technical difficulty of the specific act — predation at "
        "water surface demands correct exposure for both dark plumage and bright "
        "water simultaneously; display behaviour requires fast enough shutter to "
        "freeze feather detail in full extension; conflict requires tracking two "
        "moving subjects. IDENTIFY the prey or target if present: a fish, insect, "
        "or rival in frame is a DoD signal — its absence when expected is a deduction.\n\n"
        "DM: FIRST identify the behavioural act and its completion point before "
        "scoring. Predation: is the prey visible and identifiable? Catch freeze "
        "with prey in bill scores higher than catch freeze without prey visible. "
        "Display: are the display features (crest, plumage, posture) at full "
        "expression? Conflict: is the moment of contact, or the frame before "
        "contact, captured? Generic motion (takeoff, landing) in this sub-type "
        "scores LOWER — reward the photographer who captured the act, not the transit.\n\n"
        "WF: Score behavioural rarity explicitly. Common takeoff = low WF. "
        "Catch freeze with prey visible = moderate WF. Prey transfer mid-air, "
        "cooperative hunting, rare display posture = high WF. The wonder is "
        "in the completeness of the behavioural narrative — the image that tells "
        "the story of the act without a caption."
    ),
    'predator_prey': (
        "This is Wildlife photography — sub-type: PREDATOR–PREY (MAMMAL).\n"
        "A predation, pursuit, or conflict moment between mammals. The "
        "behavioural narrative — not the animal alone — is the primary subject.\n\n"
        "DoD: Score the tracking difficulty of two or more fast-moving subjects, "
        "correct exposure across different fur tones, and sharpness at the point "
        "of maximum action. Dust, motion blur on non-key elements, and environmental "
        "chaos are acceptable — the key subjects must be sharp.\n\n"
        "DM: IDENTIFY the behavioural peak: the moment of contact, the instant "
        "the prey changes direction, the predator's commitment point. A half-second "
        "before contact is often the peak — reward the photographer who read the "
        "sequence and pre-positioned for that frame. Both predator and prey must "
        "be readable in the decisive frame.\n\n"
        "WF: Score narrative completeness. Does the image tell the full story — "
        "predator, prey, tension, environment — in a single frame? Rare species, "
        "rare behavioural interactions, or documentation of scientifically "
        "significant behaviour score highest. The wonder is the sense of witnessing "
        "something that most humans will never see in person."
    ),
    'flora': (
        "This is Wildlife photography — sub-type: FLORA / BOTANICAL.\n"
        "Plant life, fungi, and botanical subjects. The challenge is revealing "
        "structural and textural detail invisible to the casual eye.\n\n"
        "DoD: Score depth of field control at close focus distances, light quality "
        "on translucent or textured organic surfaces, and environmental context. "
        "Background separation that isolates the subject while retaining habitat "
        "context is the DoD gold standard for Flora.\n\n"
        "DM: Score the moment of botanical peak — first light on morning dew, "
        "the specific angle that reveals internal structure, the frame where "
        "environmental conditions (light, wind stillness, dew) all align. "
        "Unlike animal subjects, Flora DM rewards the photographer's choice of "
        "angle, light, and timing rather than reaction speed.\n\n"
        "WF: Score what the photograph reveals that the eye cannot see unaided — "
        "structural geometry, translucency, colour relationships, or environmental "
        "context that elevates the subject from record to revelation. Rare species, "
        "unusual growth conditions, or scientific novelty all count."
    ),
    'marine': (
        "This is Wildlife photography — sub-type: MARINE / UNDERWATER.\n"
        "Aquatic or underwater subjects. The technical challenges of the medium — "
        "colour shift, refraction, buoyancy — are inherent DoD signals.\n\n"
        "DoD: Score colour correction in an inherently colour-shifting medium, "
        "focus accuracy through water (refraction, particulates), correct exposure "
        "without strobes washing the subject or ambient losing detail, and the "
        "physical access challenge of the marine environment itself.\n\n"
        "DM: Score the peak of animal behaviour or the ideal environmental "
        "alignment — the frame where subject, light shaft, and background reef "
        "or water column are all optimally placed. For surface/near-surface "
        "subjects, apply the same behavioural identification test as bird_behaviour: "
        "IDENTIFY the act (feeding, breach, social interaction) before scoring.\n\n"
        "WF: Score access rarity and environmental revelation. Healthy reef "
        "ecosystems, deep-water species, bioluminescence, or environmental "
        "storytelling about marine habitat condition score highest. The wonder "
        "is in showing the viewer a world they cannot physically access."
    ),
    'macro_wildlife': (
        "This is Wildlife photography — sub-type: MACRO WILDLIFE.\n"
        "Insects, arachnids, small reptiles, and micro-fauna at extreme "
        "magnification. Precision focus and depth of field management are the "
        "primary technical criteria.\n\n"
        "DoD: Score focus accuracy at high magnification (eye or primary feature "
        "sharp), depth of field control that renders the critical structure while "
        "separating from the background, and lighting that reveals surface texture "
        "without harsh specular reflections. Handheld macro in field conditions "
        "scores higher DoD than studio macro.\n\n"
        "DM: Score the behavioural or structural peak — the moment of eye contact, "
        "the feeding posture, the mating display, the emergence from the chrysalis. "
        "Macro Wildlife DM rewards the frame where behaviour and optimal focus "
        "alignment coincide. A technically sharp macro of a static subject scores "
        "lower DM than a slightly more challenging capture of a live behavioural moment.\n\n"
        "WF: Score subject rarity, structural revelation, and the sense of entering "
        "a hidden world. The best macro wildlife images show the viewer a face, "
        "a structure, or a moment that is invisible without the photograph. "
        "Common species in extraordinary detail score higher than rare species "
        "in poor light."
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

    calibration_block = get_calibration_examples(genre)
    correction_block  = get_calibration_notes(genre)

    prompt = SCORE_PROMPT.format(
        genre                = genre,
        photographer         = photographer,
        title                = title,
        subject              = subject or "Not specified",
        location             = location or "Not specified",
        genre_context        = get_genre_context(genre, sub_genre=sub_genre),
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
