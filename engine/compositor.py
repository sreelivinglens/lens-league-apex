"""
Shutter League — Share Card Compositor
Session 149 FINAL — all changes locked

WHAT CHANGED IN SESSION 149:
1. Photo rotation: rotated to match frame tilt (-2.23° CW, measured from Rectangle 1 PSD layer)
   instead of old -6° crop rotation. Photo centred on polaroid opening centre.
2. Photo scaling: fit to opening WIDTH (not cover), top-aligned, full photo visible.
   Scale = PH_W / photo_width. Portrait photos will show white space below — by design.
3. Clip mask: Rectangle_1.png built at 2x resolution then Gaussian-blurred (radius 1.5)
   before downsampling to 1080px — eliminates serrated/jagged photo edges.
4. Clip mask also rotated -2.23° to match frame tilt.
5. Group 1 composited with force=True (PSD has Group 1 visibility=False in v2 PSD).
6. Footer: composited from PSD layer 'Screenshot 2026-07-17...' at correct PSD position.
7. Copy changes:
   - "Every frame has a story" → "Photograph by [first_name]" (Felt Tip Roman, teal, 50pt)
   - "What's yours?" → "An independent photography evaluation by Shutter League"
     (Felt Tip Roman, slate blue #2C3E6B, 28pt)
   - Photographer name REMOVED from below GRANDMASTER
   - "Making Images Matter" red subtitle REMOVED from header
   - "Keep Clicking / Keep Growing" REMOVED
   - "Heart icon" SUPPRESSED
   - Interest area: now "INTEREST AREA : [area]" in DIN Condensed Bold, dark (#1A1A18)
8. PSD structure: Group 1 is now invisible in v2 PSD — use force=True.
   Rectangle 1 inside Group 1 must be suppressed (it's the magenta clip shape).

LOCKED PARAMETERS (do not change without founder approval):
  FRAME_ANGLE  = -2.23   # degrees CW — measured from Rectangle 1 PSD layer corners
  PHOTO_BY_Y   = 713     # PSD coordinate (1254px canvas) for "Photograph by" line
  EVAL_LINE_Y  = 744     # PSD coordinate for evaluation line

FILE DEPENDENCIES:
  Score_card_share.psd        — master PSD (v2: Group 1 invisible, footer screenshot layer present)
  Rectangle_1.png             — tilted magenta clip mask 1254x1254
  Optima.ttc                  — face 1=Bold (GRANDMASTER), face 2=Italic
  Papyrus.ttc                 — face 1=Regular (score)
  Bebas-Regular.ttf           — dimension scores/labels
  DIN_Condensed_Bold.ttf      — INTEREST AREA label, SHUTTER LEAGUE wordmark
  Felt_Tip_Roman_Regular.ttf  — "Photograph by" and evaluation copy lines

AUDIT: sl_audit.py does not apply Flask/route checks to this file (PIL renderer, not Flask app).
Known gap logged — to be addressed in a dedicated audit improvement session.
"""

from psd_tools import PSDImage
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np
import os

# ── Paths ─────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))

PSD_PATH  = os.path.join(_HERE, 'Score_card_share.psd')
RECT_PATH = os.path.join(_HERE, 'Rectangle_1.png')
OPTIMA    = os.path.join(_HERE, 'Optima.ttc')
PAPYRUS   = os.path.join(_HERE, 'Papyrus.ttc')
BEBAS     = os.path.join(_HERE, 'Bebas-Regular.ttf')
DIN       = os.path.join(_HERE, 'DIN_Condensed_Bold.ttf')
FELT      = os.path.join(_HERE, 'Felt_Tip_Roman_Regular.ttf')

# ── Scale ─────────────────────────────────────────────────────────────────────
SCALE = 1080 / 1254
def sc(v): return int(round(v * SCALE))

# ── Colours ───────────────────────────────────────────────────────────────────
GOLD        = (204, 153,  51)   # Optima GRANDMASTER
RED         = (204,  51,   0)   # Papyrus score
NAVY        = ( 10,  35,  85)   # dimension scores / /10
DARK        = ( 26,  26,  24)   # #1A1A18 — body text
TEAL        = (  0,  77,  77)   # "Photograph by" — matches PSD "Every frame" colour
SLATE_BLUE  = ( 44,  62, 107)   # #2C3E6B — evaluation line, brand primary

# ── Locked parameters ─────────────────────────────────────────────────────────
FRAME_ANGLE = -2.23   # degrees CW — frame tilt measured from Rectangle 1 PSD layer
PHOTO_BY_Y  = 713     # PSD y-coordinate for "Photograph by [name]"
EVAL_LINE_Y = 744     # PSD y-coordinate for evaluation copy line

# ── Layers to suppress in Group 1 composite ───────────────────────────────────
# Data layers replaced by dynamic text + copy/design decisions from Session 149
_SUPPRESS = {
    'GRAND MASTER', 'Sreekumar krishnan', '9.12', '/10',
    'Depth Score', 'Display Score', 'Decisive Moment Score',
    'Wonder Factor Score', 'Affective Quotient Score ',
    'DEPTH text', 'DISPLAY text', 'Decisive  moment text',
    'WONDER  FACTOR', 'AFFECTIVE QUOTIENT',
    'Heart icon ',
    'Every frame has a story', ' What\u2019s yours?',   # replaced with new copy
    'MAKING IMAGES MATTER', 'Line 1', 'Line 1 copy',   # removed from header
    'Keep  Clicking', ' Keep Growing',                  # removed
    'Layer 1', 'LIne separator',                        # footer replaced by PSD screenshot layer
    'Rectangle 1',                                      # magenta clip shape — suppress in group
}

# ── Font helpers ──────────────────────────────────────────────────────────────
def fnt(path, size, index=0):
    return ImageFont.truetype(path, size, index=index)

def tw(d, t, f):
    return d.textbbox((0, 0), t, font=f)[2]

def rotate_paste(canvas, text, font, colour, x, y, angle_deg):
    """Render text to a temp image, rotate, and paste onto canvas with alpha."""
    tmp  = Image.new('RGBA', (1, 1))
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=font)
    tw_  = bbox[2] - bbox[0] + 20
    th_  = bbox[3] - bbox[1] + 20
    txt  = Image.new('RGBA', (tw_, th_), (0, 0, 0, 0))
    ImageDraw.Draw(txt).text((10, 10 - bbox[1]), text, font=font, fill=(*colour, 255))
    rot  = txt.rotate(angle_deg, expand=True, resample=Image.BICUBIC)
    canvas.paste(rot, (x, y), rot)


def build_card_share(
    photo_path,
    photographer_name,
    tier,
    score,
    interest_area,
    labels,
    dimensions,
    out_path,
    psd_path=None,
    rect_path=None,
    evaluation_date=None,
):
    """
    Render a Shutter League share card.

    Args:
        photo_path:         Path to member photograph (JPG/PNG)
        photographer_name:  Member full name — first name used in "Photograph by" copy
        tier:               e.g. 'GRANDMASTER'
        score:              e.g. '9.12'
        interest_area:      e.g. 'Street • People'
        labels:             List of 5 dimension label strings
        dimensions:         List of 5 dimension score strings
        out_path:           Output JPEG path
        psd_path:           Override PSD path (optional)
        rect_path:          Override Rectangle_1.png path (optional)
        evaluation_date:    Not currently used on card (reserved)
    """
    _psd  = psd_path  or PSD_PATH
    _rect = rect_path or RECT_PATH

    # ── Load PSD layers ───────────────────────────────────────────────────────
    psd = PSDImage.open(_psd)
    bg_layer = bg_copy_layer = group_layer = footer_layer = None
    for layer in psd:
        if layer.name == 'Background':      bg_layer      = layer
        if layer.name == 'Background copy': bg_copy_layer = layer
        if layer.name == 'Group 1':         group_layer   = layer
        if 'Screenshot' in layer.name:      footer_layer  = layer

    # ── Clip mask — 2x supersample + Gaussian blur for anti-aliased edges ─────
    rect_img = Image.open(_rect).convert('RGBA')
    rect_2x  = rect_img.resize((2160, 2160), Image.LANCZOS)
    rect_arr = np.array(rect_2x)
    clip_2x  = np.where(
        (rect_arr[:, :, 0] > 150) &
        (rect_arr[:, :, 1] < 100) &
        (rect_arr[:, :, 2] > 150),
        255, 0
    ).astype(np.uint8)
    # Rotate at 2x to match frame tilt, blur edges, downsample
    mask_2x       = Image.fromarray(clip_2x).rotate(FRAME_ANGLE, center=(1080, 750),
                                                      resample=Image.BICUBIC, expand=False)
    mask_2x_blur  = mask_2x.filter(ImageFilter.GaussianBlur(radius=1.5))
    clip_mask     = np.array(mask_2x_blur.resize((1080, 1080), Image.LANCZOS))
    # Hard version for bg_copy hole punch
    clip_mask_hard = np.array(Image.fromarray(clip_mask).point(lambda x: 255 if x > 128 else 0))

    # Photo zone bounding box from smooth mask
    rows = np.any(clip_mask > 10, axis=1)
    cols = np.any(clip_mask > 10, axis=0)
    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]
    CX   = int((cmin + cmax) // 2)
    CY   = int((rmin + rmax) // 2)
    PH_W = int(cmax - cmin)

    # ── Photo — fit to opening width, top-aligned, rotate to match frame ──────
    photo = Image.open(photo_path).convert('RGBA')
    pw, ph_ = photo.size
    # Scale: fit width. Portrait photos will not fill full height — white space below is correct.
    cscale = PH_W / pw
    nw, nh = int(pw * cscale), int(ph_ * cscale)
    photo  = photo.resize((nw, nh), Image.LANCZOS)

    photo_full = Image.new('RGBA', (1080, 1080), (0, 0, 0, 0))
    photo_full.paste(photo, (CX - nw // 2, rmin + 4))
    # Rotate CW by FRAME_ANGLE (PIL rotate is CCW, so negate)
    photo_full = photo_full.rotate(FRAME_ANGLE, center=(CX, CY),
                                    resample=Image.BICUBIC, expand=False)
    photo_arr = np.array(photo_full)
    photo_arr[:, :, 3] = np.minimum(photo_arr[:, :, 3], clip_mask)
    photo_clipped = Image.fromarray(photo_arr)

    # ── Composite pipeline ────────────────────────────────────────────────────
    # 1. Paper background
    canvas = bg_layer.composite().convert('RGBA').resize((1080, 1080), Image.LANCZOS)

    # 2. Photo clipped to rotated mask
    canvas = Image.alpha_composite(canvas, photo_clipped)

    # 3. Polaroid border — hole punched using eroded hard mask
    bg_copy = bg_copy_layer.composite().convert('RGBA').resize((1080, 1080), Image.LANCZOS)
    bg_arr  = np.array(bg_copy)
    eroded  = np.array(Image.fromarray(clip_mask_hard).filter(ImageFilter.MinFilter(9)))
    bg_arr[:, :, 3] = np.where(eroded > 128, 0, bg_arr[:, :, 3])
    canvas = Image.alpha_composite(canvas, Image.fromarray(bg_arr))

    # 4. Group 1 decorations — force=True because Group 1 visibility=False in v2 PSD
    group_img  = group_layer.composite(
        force=True,
        layer_filter=lambda l: l.name not in _SUPPRESS
    ).convert('RGBA')
    group_full = Image.new('RGBA', (1254, 1254), (0, 0, 0, 0))
    group_full.paste(group_img, (group_layer.left, group_layer.top))
    canvas = Image.alpha_composite(canvas, group_full.resize((1080, 1080), Image.LANCZOS))

    # 5. Footer — from PSD screenshot layer at its correct position
    if footer_layer:
        footer_img  = footer_layer.composite().convert('RGBA')
        footer_full = Image.new('RGBA', (1254, 1254), (0, 0, 0, 0))
        footer_full.paste(footer_img, (footer_layer.left, footer_layer.top))
        canvas = Image.alpha_composite(canvas, footer_full.resize((1080, 1080), Image.LANCZOS))

    # ── Text layers ───────────────────────────────────────────────────────────
    # GRANDMASTER tier — Optima Bold, 2.07° rotation
    tier_f = fnt(OPTIMA, sc(78), index=1)
    for size in range(sc(78), sc(28), -2):
        f = fnt(OPTIMA, size, index=1)
        if tw(ImageDraw.Draw(Image.new('RGB', (1, 1))), tier.upper(), f) <= sc(500):
            tier_f = f; break
    rotate_paste(canvas, tier.upper(), tier_f, GOLD, sc(208), sc(852), 2.07)

    # Score — Papyrus Regular, 2.27°
    sc_font = fnt(PAPYRUS, sc(90), index=1)
    for size in range(sc(90), sc(40), -2):
        f = fnt(PAPYRUS, size, index=1)
        if tw(ImageDraw.Draw(Image.new('RGB', (1, 1))), score, f) <= sc(200):
            sc_font = f; break
    rotate_paste(canvas, score, sc_font, RED,  sc(882), sc(853), 2.27)
    rotate_paste(canvas, '/10', fnt(PAPYRUS, sc(38), index=1), NAVY, sc(1095), sc(900), 2.27)

    # "Photograph by [first name]" — Felt Tip Roman, teal, 50pt
    first_name = photographer_name.split()[0]
    rotate_paste(canvas, f'Photograph by {first_name}',
                 fnt(FELT, sc(50)), TEAL, sc(183), sc(PHOTO_BY_Y), 2.07)

    # "An independent photography evaluation by Shutter League" — Felt Tip Roman, slate blue, 28pt
    rotate_paste(canvas, 'An independent photography evaluation by Shutter League',
                 fnt(FELT, sc(28)), SLATE_BLUE, sc(183), sc(EVAL_LINE_Y), 2.07)

    # ── RGB draw calls ────────────────────────────────────────────────────────
    canvas_rgb = canvas.convert('RGB')
    draw = ImageDraw.Draw(canvas_rgb)

    # Interest area — DIN Condensed Bold, dark, repositioned
    ia_text = f'INTEREST AREA :  {interest_area.upper()}'
    draw.text((sc(108), sc(987)), ia_text, font=fnt(DIN, sc(21)), fill=DARK)

    # Dimension scores and labels — Bebas
    bb_f  = fnt(BEBAS, sc(30))
    lbl_f = fnt(BEBAS, sc(16))
    dim_positions = [
        (sc(187), sc(1055), sc(187), sc(1094)),
        (sc(396), sc(1055), sc(397), sc(1094)),
        (sc(619), sc(1055), sc(620), sc(1092)),
        (sc(828), sc(1055), sc(828), sc(1093)),
        (sc(1038),sc(1054), sc(1038),sc(1090)),
    ]
    for i, (sx, sy, lx, ly) in enumerate(dim_positions):
        if i < len(dimensions):
            draw.text((sx, sy), str(dimensions[i]), font=bb_f, fill=NAVY)
        if i < len(labels):
            for line in labels[i].split('\n'):
                draw.text((lx, ly), line, font=lbl_f, fill=NAVY)
                ly += sc(16)

    # ── Save ──────────────────────────────────────────────────────────────────
    canvas_rgb.save(out_path, 'JPEG', quality=97)
    return out_path


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    photo = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_HERE, 'His_Bilt_moment.jpeg')
    out   = sys.argv[2] if len(sys.argv) > 2 else '/tmp/share_card_test.jpg'

    build_card_share(
        photo_path        = photo,
        photographer_name = 'Deepti Malik',
        tier              = 'GRANDMASTER',
        score             = '9.12',
        interest_area     = 'Street • People',
        labels            = ['DEPTH', 'DISPLAY', 'DECISIVE\nMOMENT', 'WONDER\nFACTOR', 'AFFECTIVE\nQUOTIENT'],
        dimensions        = ['9.1', '9.0', '9.2', '9.3', '9.0'],
        out_path          = out,
    )
    print(f'Rendered: {out}')
