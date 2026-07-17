"""
Shutter League — Share Card Compositor (Production)
Session 149 FINAL — lightweight, no psd_tools

ARCHITECTURE:
  Static PSD layers pre-rendered to PNGs at build time (offline, once).
  Runtime uses only Pillow + numpy — no PSD loading, no psd_tools.
  Render time: <1 second per card.

STATIC ASSETS (deploy to engine/assets/):
  card_bg.png          — paper background 1080x1080
  card_border.png      — polaroid white border with photo hole, RGBA 1080x1080
  card_decorations.png — group decorations + footer, RGBA 1080x1080
  card_clip_mask.png   — rotated anti-aliased clip mask, grayscale 1080x1080

FONT ASSETS (deploy to engine/assets/):
  Optima.ttc
  Papyrus.ttc
  Bebas-Regular.ttf
  DIN_Condensed_Bold.ttf
  Felt_Tip_Roman_Regular.ttf

REQUIREMENTS (pip):
  Pillow
  numpy
  (psd_tools NOT required at runtime)

LOCKED PARAMETERS (Session 149 — do not change without founder approval):
  FRAME_ANGLE  = -2.23   degrees CW — measured from Rectangle 1 PSD layer corners
  PHOTO_BY_Y   = 713     PSD coordinate (1254px canvas) for "Photograph by" line
  EVAL_LINE_Y  = 744     PSD coordinate for evaluation copy line
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np
import os

# ── Asset paths ───────────────────────────────────────────────────────────────
_HERE    = os.path.dirname(os.path.abspath(__file__))
_ASSETS  = os.path.join(_HERE, 'assets')

BG_PATH          = os.path.join(_ASSETS, 'card_bg.png')
BORDER_PATH      = os.path.join(_ASSETS, 'card_border.png')
DECORATIONS_PATH = os.path.join(_ASSETS, 'card_decorations.png')
CLIP_MASK_PATH   = os.path.join(_ASSETS, 'card_clip_mask.png')

OPTIMA  = os.path.join(_ASSETS, 'Optima.ttc')
PAPYRUS = os.path.join(_ASSETS, 'Papyrus.ttc')
BEBAS   = os.path.join(_ASSETS, 'Bebas-Regular.ttf')
DIN     = os.path.join(_ASSETS, 'DIN_Condensed_Bold.ttf')
FELT    = os.path.join(_ASSETS, 'Felt_Tip_Roman_Regular.ttf')

# ── Scale (PSD is 1254px, output is 1080px) ───────────────────────────────────
SCALE = 1080 / 1254
def sc(v): return int(round(v * SCALE))

# ── Colours ───────────────────────────────────────────────────────────────────
GOLD       = (204, 153,  51)   # GRANDMASTER
RED        = (204,  51,   0)   # score
NAVY       = ( 10,  35,  85)   # /10, dimensions
DARK       = ( 26,  26,  24)   # #1A1A18 body text
TEAL       = (  0,  77,  77)   # "Photograph by"
SLATE_BLUE = ( 44,  62, 107)   # #2C3E6B evaluation line

# ── Locked parameters ─────────────────────────────────────────────────────────
FRAME_ANGLE = -2.23
PHOTO_BY_Y  = 713
EVAL_LINE_Y = 744

# ── Static assets — loaded once at module import ──────────────────────────────
_BG          = None
_BORDER      = None
_DECORATIONS = None
_CLIP_MASK   = None

def _load_assets():
    global _BG, _BORDER, _DECORATIONS, _CLIP_MASK
    if _BG is None:
        if not os.path.exists(BG_PATH):
            raise RuntimeError(
                f'Card assets missing — upload engine/assets/ PNGs to Railway. '
                f'Expected: {BG_PATH}'
            )
        _BG          = Image.open(BG_PATH).convert('RGBA')
        _BORDER      = Image.open(BORDER_PATH).convert('RGBA')
        _DECORATIONS = Image.open(DECORATIONS_PATH).convert('RGBA')
        _CLIP_MASK   = np.array(Image.open(CLIP_MASK_PATH).convert('L'))

# ── Font helpers ──────────────────────────────────────────────────────────────
def fnt(path, size, index=0):
    return ImageFont.truetype(path, size, index=index)

def tw(d, t, f):
    return d.textbbox((0, 0), t, font=f)[2]

def rotate_paste(canvas, text, font, colour, x, y, angle_deg):
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
    **kwargs,
):
    """
    Render a Shutter League share card. Pure Pillow — no psd_tools.

    Args:
        photo_path:         Path to member photograph (JPG/PNG)
        photographer_name:  Member full name — first name used in copy
        tier:               e.g. 'GRANDMASTER'
        score:              e.g. '9.12'
        interest_area:      e.g. 'Street • People'
        labels:             List of 5 dimension label strings
        dimensions:         List of 5 dimension score strings
        out_path:           Output JPEG path
    """
    _load_assets()

    # Photo zone from clip mask bounding box
    rows = np.any(_CLIP_MASK > 10, axis=1)
    cols = np.any(_CLIP_MASK > 10, axis=0)
    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]
    CX   = int((cmin + cmax) // 2)
    CY   = int((rmin + rmax) // 2)
    PH_W = int(cmax - cmin)

    # ── Photo — fit to width, top-aligned, rotate to match frame ─────────────
    photo = Image.open(photo_path).convert('RGBA')
    pw, ph_ = photo.size
    cscale  = PH_W / pw
    nw, nh  = int(pw * cscale), int(ph_ * cscale)
    photo   = photo.resize((nw, nh), Image.LANCZOS)

    photo_full = Image.new('RGBA', (1080, 1080), (0, 0, 0, 0))
    photo_full.paste(photo, (CX - nw // 2, rmin + 4))
    photo_full = photo_full.rotate(FRAME_ANGLE, center=(CX, CY),
                                    resample=Image.BICUBIC, expand=False)
    photo_arr = np.array(photo_full)
    photo_arr[:, :, 3] = np.minimum(photo_arr[:, :, 3], _CLIP_MASK)
    photo_clipped = Image.fromarray(photo_arr)

    # ── Composite ─────────────────────────────────────────────────────────────
    canvas = _BG.copy()
    canvas = Image.alpha_composite(canvas, photo_clipped)
    canvas = Image.alpha_composite(canvas, _BORDER)
    canvas = Image.alpha_composite(canvas, _DECORATIONS)

    # ── Text ──────────────────────────────────────────────────────────────────
    # Tier — Optima Bold, auto-fit, 2.07°
    tier_f = fnt(OPTIMA, sc(78), index=1)
    for size in range(sc(78), sc(28), -2):
        f = fnt(OPTIMA, size, index=1)
        if tw(ImageDraw.Draw(Image.new('RGB', (1,1))), tier.upper(), f) <= sc(500):
            tier_f = f; break
    rotate_paste(canvas, tier.upper(), tier_f, GOLD, sc(208), sc(852), 2.07)

    # Score — Papyrus, auto-fit, 2.27°
    sc_font = fnt(PAPYRUS, sc(90), index=1)
    for size in range(sc(90), sc(40), -2):
        f = fnt(PAPYRUS, size, index=1)
        if tw(ImageDraw.Draw(Image.new('RGB', (1,1))), score, f) <= sc(200):
            sc_font = f; break
    rotate_paste(canvas, score, sc_font, RED,  sc(882), sc(853), 2.27)
    rotate_paste(canvas, '/10', fnt(PAPYRUS, sc(38), index=1), NAVY, sc(1095), sc(900), 2.27)

    # "Photograph by [first name]" — Felt Tip Roman, teal, 50pt
    first_name = photographer_name.split()[0]
    rotate_paste(canvas, f'Photograph by {first_name}',
                 fnt(FELT, sc(50)), TEAL, sc(183), sc(PHOTO_BY_Y), 2.07)

    # Evaluation line — Felt Tip Roman, slate blue, 28pt
    rotate_paste(canvas, 'An independent photography evaluation by Shutter League',
                 fnt(FELT, sc(28)), SLATE_BLUE, sc(183), sc(EVAL_LINE_Y), 2.07)

    # RGB draw calls
    canvas_rgb = canvas.convert('RGB')
    draw = ImageDraw.Draw(canvas_rgb)

    # Interest area
    draw.text((sc(108), sc(987)),
              f'INTEREST AREA :  {interest_area.upper()}',
              font=fnt(DIN, sc(21)), fill=DARK)

    # Dimensions
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

    canvas_rgb.save(out_path, 'JPEG', quality=97)
    return out_path


# ── Backward compatibility alias ──────────────────────────────────────────────
# engine/__init__.py imports build_card — keep this working
def build_card(thumb_path, audit, out_path):
    """
    Adapter for legacy build_card(thumb_path, audit, out_path) call signature.
    Maps audit dict fields to build_card_share() parameters.
    """
    score    = str(audit.get('score', ''))
    tier     = str(audit.get('tier', ''))
    name     = str(audit.get('credit', '') or audit.get('photographer_name', ''))
    # genre_tag is stored as "WILDLIFE  .  PNG" — take only the genre part before any separator
    raw_genre = str(audit.get('genre_tag', '') or audit.get('genre', ''))
    genre = raw_genre.split('·')[0].split('.')[0].split('  ')[0].strip().title()
    labels   = ['DEPTH','DISPLAY','DECISIVE\nMOMENT','WONDER\nFACTOR','AFFECTIVE\nQUOTIENT']
    modules  = audit.get('modules', [])
    dims     = [str(m[1]) for m in modules] if modules else ['','','','','']

    return build_card_share(
        photo_path        = thumb_path,
        photographer_name = name or 'Photographer',
        tier              = tier,
        score             = score,
        interest_area     = genre,
        labels            = labels,
        dimensions        = dims,
        out_path          = out_path,
    )


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys, time
    photo = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_HERE, 'His_Bilt_moment.jpeg')
    out   = sys.argv[2] if len(sys.argv) > 2 else '/tmp/share_card_test.jpg'
    t0 = time.time()
    build_card_share(
        photo_path        = photo,
        photographer_name = 'Deepti Malik',
        tier              = 'GRANDMASTER',
        score             = '9.12',
        interest_area     = 'Street • People',
        labels            = ['DEPTH','DISPLAY','DECISIVE\nMOMENT','WONDER\nFACTOR','AFFECTIVE\nQUOTIENT'],
        dimensions        = ['9.1','9.0','9.2','9.3','9.0'],
        out_path          = out,
    )
    print(f'Rendered: {out} in {time.time()-t0:.2f}s')


# ── Aliases for app.py import compatibility ───────────────────────────────────
# app.py does: from engine.compositor import build_card1
# engine/__init__.py does: from .compositor import build_card
# One place imports build_card2 but never calls it — stub provided
build_card1 = build_card
build_card2 = build_card  # stub — never called, import compatibility only
