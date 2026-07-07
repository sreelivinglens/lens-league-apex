"""
Apex Rating Cards — v24
Sprint 5 — scorecard redesign.
Two landscape cards at A4 300dpi (2480x1754px).
Card 1: Photo hero + Score + Plain-language modules + what_stood_out
Card 2: 4 story cards + Edit guide + Location intelligence
KYC compliant throughout. No jargon labels.
"""

from PIL import Image as PilImage, ImageDraw, ImageFont
import os

FONT_DIR = os.path.dirname(os.path.abspath(__file__))

def fnt(size, bold=False, mono=False):
    if mono and bold:
        candidates = [
            os.path.join(FONT_DIR,'DejaVuSansMono-Bold.ttf'),
            '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf',
        ]
    elif mono:
        candidates = [
            os.path.join(FONT_DIR,'DejaVuSansMono.ttf'),
            '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        ]
    elif bold:
        candidates = [
            os.path.join(FONT_DIR,'LiberationSans-Bold.ttf'),
            '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        ]
    else:
        candidates = [
            os.path.join(FONT_DIR,'LiberationSans-Regular.ttf'),
            '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]
    for p in candidates:
        if p and os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

# ── Site Palette ──────────────────────────────────────────────────────────────
CREAM   = (253, 252, 248)
SURFACE = (241, 239, 232)
BORDER  = (210, 208, 200)
SLATE   = ( 44,  62, 107)
T1      = ( 26,  26,  24)
T2      = ( 74,  72,  64)
T3      = (136, 135, 128)
GOLD    = (200, 168,  75)
GOLD_D  = (139, 105,  20)
GREEN   = ( 59, 109,  17)
DARK_GN = ( 15,  35,  24)   # mentor location dark green bg
AMBER   = (186, 117,  23)
WHITE   = (255, 255, 255)
DARK    = ( 26,  26,  18)

# ── Card palette — light gradients for story cards ───────────────────────────
CARD_ESPRESSO_BG = (253, 243, 227)   # warm amber tint
CARD_NAVY_BG     = (234, 240, 250)   # cool blue tint
CARD_FOREST_BG   = (234, 245, 238)   # sage green tint
CARD_PLUM_BG     = (245, 234, 240)   # dusty rose tint
CARD_ESPRESSO_AC = (133,  79,  11)   # amber accent
CARD_NAVY_AC     = ( 24,  95, 165)   # blue accent
CARD_FOREST_AC   = ( 39,  80,  10)   # forest accent
CARD_PLUM_AC     = (114,  36,  62)   # plum accent

# ── Watermark config ─────────────────────────────────────────────────────────
WATERMARK_OPACITY = 180   # alpha for text (0-255)

CW, CH   = 2480, 1754
PAD      = 80
HEADER_H = 100
FOOTER_H = 80

SITE_URL  = 'shutterleague.com'
LOGO_PATH = os.path.join(FONT_DIR, 'shutterleague-logo-cropped.png')
_LOGO_FALLBACKS = [
    LOGO_PATH,
    os.path.join(os.path.dirname(FONT_DIR), 'engine', 'shutterleague-logo-cropped.png'),
    os.path.join(os.path.dirname(FONT_DIR), 'static', 'img', 'shutterleague-logo-cropped.png'),
    '/app/engine/shutterleague-logo-cropped.png',
]

def _load_logo(h):
    for p in _LOGO_FALLBACKS:
        if p and os.path.exists(p):
            try:
                lg = PilImage.open(p).convert('RGBA')
                w = int(lg.size[0] * h / lg.size[1])
                return lg.resize((w, h), PilImage.LANCZOS), w
            except: continue
    return None, 0

def lh(font):
    d = ImageDraw.Draw(PilImage.new('RGB',(1,1)))
    bb = d.textbbox((0,0),'Ag',font=font)
    return bb[3]-bb[1]+6

def tw(draw, text, font):
    return draw.textbbox((0,0),text,font=font)[2]

def wrap_lines(draw, text, font, max_w):
    if not text or not text.strip(): return []
    words,lines,cur = text.split(),[],[]
    for w in words:
        test = ' '.join(cur+[w])
        if tw(draw,test,font) > max_w and cur:
            lines.append(' '.join(cur)); cur=[w]
        else: cur.append(w)
    if cur: lines.append(' '.join(cur))
    return lines

def draw_text(draw, text, font, color, x, y, max_w, sp=12):
    for line in wrap_lines(draw,text,font,max_w):
        draw.text((x,y),line,font=font,fill=color)
        y += lh(font)+sp
    return y

def text_block_height(draw, text, font, max_w, sp=12):
    """Measure height a text block will take without drawing."""
    lines = wrap_lines(draw, text, font, max_w)
    return len(lines) * (lh(font) + sp) if lines else 0

def draw_header(canvas, draw, left, right):
    draw.rectangle([0,0,CW,HEADER_H], fill=SLATE)
    draw.text((PAD,28), left, font=fnt(36,bold=True,mono=True), fill=WHITE)
    rw = tw(draw,right,fnt(28,mono=True))
    draw.text((CW-PAD-rw,34), right, font=fnt(28,mono=True), fill=(180,190,210))

def draw_footer(canvas, draw, stamp, canvas_h=None):
    h = canvas_h or CH
    draw.rectangle([0,h-FOOTER_H,CW,h], fill=SLATE)
    draw.rectangle([0,h-FOOTER_H,CW,h-FOOTER_H+1], fill=(60,75,115))
    left = 'BETTER LIGHT.  MORE CLARITY.  STRONGER STORY.  YOU, ONE FRAME AT A TIME.'
    draw.text((PAD, h-FOOTER_H+26), left, font=fnt(28,mono=True), fill=(160,175,200))
    sw = tw(draw, stamp, fnt(28,bold=True,mono=True))
    draw.text((CW-PAD-sw, h-FOOTER_H+26), stamp, font=fnt(28,bold=True,mono=True), fill=GOLD)

def apply_watermark(canvas, x, y, w, h, credit=''):
    """
    Draw a single small credit pill at the bottom-right corner of the photo.
    Format: © [First name] [Last initial] — photographer credit only.
    Semi-dark pill background ensures readability on any photo colour.
    """
    if not credit:
        return

    # Format: first name + last initial only (handles long names)
    parts = credit.strip().split()
    if len(parts) >= 2:
        display = f'\u00a9 {parts[0]} {parts[-1][0]}'
    else:
        display = f'\u00a9 {credit.strip()}'

    wm_layer = PilImage.new('RGBA', (w, h), (0, 0, 0, 0))
    wm_draw  = ImageDraw.Draw(wm_layer)
    wm_font  = fnt(24, mono=True)   # small — 9px equivalent at card scale

    bb      = wm_draw.textbbox((0, 0), display, font=wm_font)
    tw, th  = bb[2], bb[3]
    pad_x   = 14
    pad_y   = 10
    pill_x  = w - tw - pad_x * 2
    pill_y  = h - th - pad_y * 2

    # Semi-dark pill — readable on white, yellow, black
    wm_draw.rounded_rectangle(
        [pill_x - pad_x, pill_y - pad_y, w, h],
        radius=8,
        fill=(0, 0, 0, 110)
    )
    wm_draw.text((pill_x, pill_y), display, font=wm_font,
                 fill=(255, 255, 255, 220))

    canvas.paste(wm_layer, (x, y), wm_layer)


def draw_story_card(draw, x, y, w, h, bg_color, accent_color, eyebrow, headline, body, dummy_draw=None):
    """Draw a single story card with light gradient background."""
    # Card background
    draw.rectangle([x, y, x+w, y+h], fill=bg_color)
    draw.rectangle([x, y, x+w, y+1], fill=accent_color)  # top accent line

    cy = y + 28
    # Eyebrow label
    draw.text((x+28, cy), eyebrow.upper(), font=fnt(30, bold=True, mono=True), fill=accent_color)
    cy += lh(fnt(30, bold=True, mono=True)) + 16

    # Headline — bold, near-black
    hl_font = fnt(42, bold=True)
    for line in wrap_lines(draw, headline, hl_font, w-56):
        draw.text((x+28, cy), line, font=hl_font, fill=T1)
        cy += lh(hl_font) + 6
    cy += 14

    # Body — readable size
    draw_text(draw, body, fnt(36), T2, x+28, cy, w-56, sp=10)


def measure_story_card(draw, w, headline, body):
    """Measure height needed for a story card."""
    hl_lines = wrap_lines(draw, headline, fnt(42, bold=True), w-56)
    bd_lines = wrap_lines(draw, body, fnt(36), w-56)
    h  = 28  # top pad
    h += lh(fnt(30, bold=True, mono=True)) + 16  # eyebrow
    h += len(hl_lines) * (lh(fnt(42, bold=True)) + 6) + 14  # headline
    h += len(bd_lines) * (lh(fnt(36)) + 10)  # body
    h += 28  # bottom pad
    return h


def build_card1(photo_path, data, out_path):
    """Card 1 — Full-width photo hero, score/modules band below."""
    canvas = PilImage.new('RGB',(CW,CH),CREAM)
    draw   = ImageDraw.Draw(canvas)

    INNER_H  = CH - HEADER_H - FOOTER_H
    PHOTO_H  = int(INNER_H * 0.60)
    BAND_Y   = HEADER_H + PHOTO_H
    BAND_H   = INNER_H - PHOTO_H

    # ── Photo ─────────────────────────────────────────────────────────────────
    try:
        ph = PilImage.open(photo_path).convert('RGB')
        pw, phh = ph.size
        scale = min(CW / pw, PHOTO_H / phh)
        nw, nh = int(pw * scale), int(phh * scale)
        ph = ph.resize((nw, nh), PilImage.LANCZOS)
        draw.rectangle([0, HEADER_H, CW, HEADER_H + PHOTO_H], fill=(20, 20, 18))
        ox = (CW - nw) // 2
        oy = HEADER_H + (PHOTO_H - nh) // 2
        canvas.paste(ph, (ox, oy))
        apply_watermark(canvas, ox, oy, nw, nh, credit=data.get('credit', ''))
    except:
        draw.rectangle([0, HEADER_H, CW, HEADER_H + PHOTO_H], fill=BORDER)

    score = str(data.get('score', '—'))
    tier  = data.get('tier', '').upper()

    # ── Module panel (right 55%) ───────────────────────────────────────────────
    modules  = data.get('modules', [])
    n        = max(len(modules), 1)
    MOD_W    = int(CW * 0.55)
    MOD_X    = CW - MOD_W
    draw.rectangle([MOD_X, BAND_Y, CW, BAND_Y + BAND_H], fill=SURFACE)
    draw.rectangle([MOD_X, BAND_Y, MOD_X + 1, BAND_Y + BAND_H], fill=BORDER)
    MW     = (MOD_W - PAD) // n
    max_sc = max((float(s) for _, s in modules if s), default=0)

    # Plain-language module labels — KYC compliant
    _lbl_map = {
        'DoD':        ('HOW DIFFICULT', 'IT WAS'),
        'VD':         ('VISUAL',        'DISRUPTION'),
        'Disruption': ('VISUAL',        'DISRUPTION'),
        'DM':         ('WHETHER THE',   'TIMING WAS RIGHT'),
        'WF':         ('WHETHER IT',    'MADE YOU FEEL'),
        'Wonder':     ('WHETHER IT',    'MADE YOU FEEL'),
        'AQ':         ('THE EMOTION',   'IT CREATES'),
    }

    # ── Left meta panel ────────────────────────────────────────────────────────
    SX = PAD
    SW = MOD_X - PAD * 2
    SY = BAND_Y + 32

    # Score + tier
    draw.text((SX, SY), score, font=fnt(130, bold=True), fill=T1)
    score_w = tw(draw, score, fnt(130, bold=True))
    draw.text((SX + score_w + 24, SY + 20), tier, font=fnt(52, bold=True, mono=True), fill=SLATE)

    # Tier pips
    tier_map = {
        'ROOKIE':1,'SHOOTER':1,'CONTENDER':2,'CRAFTSMAN':2,
        'MAVERICK':3,'MASTER':3,'GRANDMASTER':4,'LEGEND':5,
    }
    active = tier_map.get(tier, 1)
    pip_y  = SY + lh(fnt(130, bold=True)) + 8
    for i in range(5):
        px = SX + i * 40
        draw.rectangle([px, pip_y, px+28, pip_y+14], fill=GOLD if i < active else BORDER)
    pip_y += 30

    draw.rectangle([SX, pip_y, SX+SW, pip_y+1], fill=BORDER)
    pip_y += 16

    # Title
    pip_y = draw_text(draw, data.get('asset', 'Untitled'), fnt(36), T1, SX, pip_y, SW, 4)

    # Photographer
    credit = data.get('credit', '').strip()
    photographer_y = pip_y
    if credit:
        pip_y = draw_text(draw, 'PHOTOGRAPHY BY :  ' + credit.upper(),
                          fnt(44, bold=True, mono=True), SLATE, SX, pip_y, SW, 4)
    pip_y = draw_text(draw, data.get('meta', ''), fnt(34), T2, SX, pip_y, SW, 4)
    arch = data.get('dec', '')
    if arch:
        pip_y = draw_text(draw, 'Affective State: ' + arch, fnt(30, mono=True), T3, SX, pip_y, SW, 4)

    if data.get('soul_bonus'):
        pip_y += 8
        pip_y = draw_text(draw, '★  SOUL BONUS ACTIVE', fnt(30, mono=True), GOLD, SX, pip_y, SW)

    # what_stood_out — Option A fallback to hard_truth
    _wso = (data.get('what_stood_out') or data.get('hard_truth') or '').strip()
    if _wso:
        pip_y += 10
        draw.rectangle([SX, pip_y, SX+SW, pip_y+1], fill=BORDER)
        pip_y += 14
        pip_y = draw_text(draw, _wso, fnt(38, bold=True), T1, SX, pip_y, SW, 6)

    # ── Module scores ─────────────────────────────────────────────────────────
    LBL_Y = photographer_y

    for i, (name, mscore) in enumerate(modules):
        mx     = MOD_X + PAD//2 + i * MW
        col_cx = mx + MW // 2
        top    = float(mscore) == max_sc
        col    = GOLD if top else T1
        l1, l2 = _lbl_map.get(name, (name.upper(), ''))
        l1w = tw(draw, l1, fnt(28, mono=True))
        l2w = tw(draw, l2, fnt(28, mono=True))
        scw = tw(draw, str(mscore), fnt(76, bold=True))
        draw.text((col_cx - l1w//2, LBL_Y),
                  l1, font=fnt(28, mono=True), fill=T2)
        draw.text((col_cx - l2w//2, LBL_Y + lh(fnt(28, mono=True)) + 4),
                  l2, font=fnt(28, mono=True), fill=T2)
        draw.text((col_cx - scw//2, LBL_Y + lh(fnt(28, mono=True))*2 + 14),
                  str(mscore), font=fnt(76, bold=True), fill=col)

    # ── Device label + track badge (Session 132 — Mobile DDI) ────────────────
    device_label  = (data.get('device_label') or '').strip()
    camera_track  = (data.get('camera_track') or '').strip()
    track_icon    = '📱' if camera_track == 'mobile' else ('📷' if camera_track == 'camera' else '')
    track_label   = ('MOBILE LEAGUE' if camera_track == 'mobile'
                     else 'CAMERA LEAGUE' if camera_track == 'camera' else '')

    # Device label line below photographer credit (if available)
    if device_label and pip_y < BAND_Y + BAND_H - 40:
        pip_y += 6
        pip_y = draw_text(draw, device_label, fnt(30, mono=True), T3, SX, pip_y, SW, 4)

    # Track badge — small pill in bottom-left of band
    if track_label:
        _badge_text = f'{track_icon}  {track_label}'
        _badge_font = fnt(26, bold=True, mono=True)
        _bw = tw(draw, _badge_text, _badge_font)
        _bx = SX
        _by = BAND_Y + BAND_H - 44
        draw.rounded_rectangle([_bx - 4, _by - 4, _bx + _bw + 12, _by + 30],
                                radius=6,
                                fill=DARK if camera_track == 'mobile' else SURFACE)
        draw.text((_bx + 4, _by),
                  _badge_text, font=_badge_font,
                  fill=GOLD if camera_track == 'mobile' else SLATE)

    # Footer stamp includes device label when present
    _footer_stamp = 'SL  ·  ' + score + '  ·  ' + tier
    if device_label:
        _footer_stamp += '  ·  ' + device_label

    draw_header(canvas, draw, 'SHUTTER LEAGUE', 'APEX DDI ENGINE  ·  FULL EVALUATION')
    draw_footer(canvas, draw, _footer_stamp)
    canvas.save(out_path, 'JPEG', quality=96)
    return out_path


def build_card2(data, out_path):
    """Card 2 — 4 story cards + edit guide + location intelligence. Dynamic height."""

    CARD_GAP = 32
    CARD_COLS = 4
    CARD_W  = (CW - PAD*2 - CARD_GAP*(CARD_COLS-1)) // CARD_COLS

    dummy = ImageDraw.Draw(PilImage.new('RGB',(CW,100),CREAM))

    # ── Option A fallbacks ────────────────────────────────────────────────────
    _wso          = (data.get('what_stood_out') or data.get('hard_truth') or '').strip()
    _transferable = (data.get('transferable_advice') or '').strip()
    _controlled   = (data.get('byline_2_body') or data.get('byline_2') or '').strip()
    _bgcheck      = (data.get('background_check') or data.get('byline_1') or '').strip()
    _edit_std     = (data.get('edit_base') or '').strip()
    _edit_cre     = (data.get('edit_creative') or '').strip()
    _loc1         = (data.get('mentor_location_1') or '').strip()
    _loc2         = (data.get('mentor_location_2') or '').strip()
    _days_lang    = (data.get('days_since_language') or '').strip()

    # Fall back rows for card 2 body when new fields absent
    _rows = {r[0]: r[1] for r in data.get('rows', []) if r[1]}
    if not _transferable: _transferable = _rows.get('Next', '')
    if not _controlled:   _controlled   = _rows.get('Moment', '')
    if not _bgcheck:      _bgcheck      = _rows.get('Technical', '')

    # ── 4 Story card definitions ──────────────────────────────────────────────
    cards = [
        {
            'bg':      CARD_ESPRESSO_BG,
            'accent':  CARD_ESPRESSO_AC,
            'eyebrow': "The photographer's advice",
            'headline': 'Trust the darkness.',
            'body':    _transferable or 'You trusted the light. Carry that decision into every frame.',
        },
        {
            'bg':      CARD_NAVY_BG,
            'accent':  CARD_NAVY_AC,
            'eyebrow': 'What you controlled',
            'headline': _wso or 'You made the harder call.',
            'body':    _controlled or '',
        },
        {
            'bg':      CARD_FOREST_BG,
            'accent':  CARD_FOREST_AC,
            'eyebrow': 'What to watch next',
            'headline': 'One second before you press.',
            'body':    _bgcheck or '',
        },
        {
            'bg':      CARD_PLUM_BG,
            'accent':  CARD_PLUM_AC,
            'eyebrow': 'Keep this in mind',
            'headline': "Don't touch the blacks.",
            'body':    _edit_std or '',
        },
    ]

    # ── Measure content height ────────────────────────────────────────────────
    card_h = max(
        measure_story_card(dummy, CARD_W, c['headline'], c['body'])
        for c in cards
    )

    content_h = card_h + CARD_GAP

    # Edit guide
    edit_h = 0
    if _edit_std or _edit_cre:
        edit_h += 32 + lh(fnt(38, bold=True, mono=True)) + 16  # header
        for body in [_edit_std, _edit_cre]:
            if body:
                edit_h += lh(fnt(32, bold=True, mono=True)) + 8
                edit_h += text_block_height(dummy, body, fnt(40), (CW - PAD*2)//2 - 40, 10)
                edit_h += 24
        content_h += edit_h + CARD_GAP

    # Location intelligence
    loc_h = 0
    if _loc1:
        loc_h += 32 + lh(fnt(36, bold=True, mono=True)) + 16
        loc_h += text_block_height(dummy, _loc1, fnt(40), CW - PAD*2 - 40, 10) + 20
        if _loc2:
            loc_h += text_block_height(dummy, _loc2, fnt(40), CW - PAD*2 - 40, 10) + 16
        if _days_lang:
            loc_h += lh(fnt(38, bold=True)) + 16
        loc_h += 24
        content_h += loc_h + CARD_GAP

    DYN_H = HEADER_H + PAD + content_h + PAD*2 + FOOTER_H

    canvas = PilImage.new('RGB',(CW, DYN_H), CREAM)
    draw   = ImageDraw.Draw(canvas)

    Y = HEADER_H + PAD

    # ── Draw 4 story cards ────────────────────────────────────────────────────
    for i, card in enumerate(cards):
        cx = PAD + i * (CARD_W + CARD_GAP)
        draw_story_card(
            draw, cx, Y, CARD_W, card_h,
            card['bg'], card['accent'],
            card['eyebrow'], card['headline'], card['body']
        )

    Y += card_h + CARD_GAP * 2

    # ── Edit Guide ────────────────────────────────────────────────────────────
    if _edit_std or _edit_cre:
        EW = (CW - PAD*2 - CARD_GAP) // 2

        draw.text((PAD, Y), 'EDIT GUIDE', font=fnt(38, bold=True, mono=True), fill=SLATE)
        Y += lh(fnt(38, bold=True, mono=True)) + 16
        draw.rectangle([PAD, Y, CW-PAD, Y+1], fill=BORDER)
        Y += 16

        EY_L = Y
        EY_R = Y
        EX_R = PAD + EW + CARD_GAP

        if _edit_std:
            draw.text((PAD, EY_L), 'STANDARD EDIT', font=fnt(32, bold=True, mono=True), fill=GOLD)
            sub_x = PAD + tw(draw, 'STANDARD EDIT', fnt(32, bold=True, mono=True)) + 16
            draw.text((sub_x, EY_L+4), '· Balanced. Light editing.', font=fnt(28, mono=True), fill=T3)
            EY_L += lh(fnt(32, bold=True, mono=True)) + 8
            EY_L = draw_text(draw, _edit_std, fnt(40), T2, PAD+20, EY_L, EW-40, 10)
            EY_L += 16

        if _edit_cre:
            draw.text((EX_R, EY_R), 'CREATIVE EDIT', font=fnt(32, bold=True, mono=True), fill=GREEN)
            sub_x = EX_R + tw(draw, 'CREATIVE EDIT', fnt(32, bold=True, mono=True)) + 16
            draw.text((sub_x, EY_R+4), '· Artistic. Heavy editing.', font=fnt(28, mono=True), fill=T3)
            EY_R += lh(fnt(32, bold=True, mono=True)) + 8
            EY_R = draw_text(draw, _edit_cre, fnt(40), T2, EX_R+20, EY_R, EW-40, 10)
            EY_R += 16

        Y = max(EY_L, EY_R) + CARD_GAP

    # ── Mentor Location Intelligence ──────────────────────────────────────────
    if _loc1:
        LOC_X    = PAD
        LOC_W    = CW - PAD*2
        BOX_PAD  = 32

        # Dark green background box
        box_y1 = Y
        # Measure box height first
        _loc1_lines = wrap_lines(draw, _loc1, fnt(40), LOC_W - BOX_PAD*2)
        _loc2_lines = wrap_lines(draw, _loc2, fnt(40), LOC_W - BOX_PAD*2) if _loc2 else []
        box_h = BOX_PAD
        box_h += lh(fnt(36, bold=True, mono=True)) + 16  # header
        box_h += len(_loc1_lines) * (lh(fnt(40)) + 10) + 20
        if _loc2_lines:
            box_h += len(_loc2_lines) * (lh(fnt(40)) + 10) + 16
        if _days_lang:
            box_h += lh(fnt(38, bold=True)) + 16
        box_h += BOX_PAD

        draw.rectangle([LOC_X, box_y1, LOC_X+LOC_W, box_y1+box_h], fill=DARK_GN)

        iy = box_y1 + BOX_PAD
        # Header label
        header_text = 'WHERE TO SHOOT NEXT'
        draw.text((LOC_X+BOX_PAD, iy), header_text,
                  font=fnt(36, bold=True, mono=True), fill=(126, 200, 160))
        iy += lh(fnt(36, bold=True, mono=True)) + 16

        # Location 1
        iy = draw_text(draw, _loc1, fnt(40), (230, 240, 235),
                       LOC_X+BOX_PAD, iy, LOC_W-BOX_PAD*2, 10)
        iy += 20

        # Location 2
        if _loc2:
            draw.rectangle([LOC_X+BOX_PAD, iy, LOC_X+LOC_W-BOX_PAD, iy+1],
                           fill=(60, 100, 70))
            iy += 16
            iy = draw_text(draw, _loc2, fnt(40), (200, 220, 210),
                           LOC_X+BOX_PAD, iy, LOC_W-BOX_PAD*2, 10)
            iy += 16

        # Days since language
        if _days_lang:
            draw.rectangle([LOC_X+BOX_PAD, iy, LOC_X+LOC_W-BOX_PAD, iy+1],
                           fill=(60, 100, 70))
            iy += 16
            draw_text(draw, _days_lang, fnt(38, bold=True),
                      GOLD, LOC_X+BOX_PAD, iy, LOC_W-BOX_PAD*2)

        Y = box_y1 + box_h + CARD_GAP

    # ── Quote ─────────────────────────────────────────────────────────────────
    quote = '"To photograph is to hold one\'s breath when all faculties converge to capture fleeting reality."'
    attr  = '— Henri Cartier-Bresson'
    draw.rectangle([PAD, Y, PAD+6, Y + text_block_height(dummy, quote, fnt(38), CW-PAD*2-40, 10) + lh(fnt(32,mono=True)) + 24], fill=GOLD)
    Y += 8
    Y = draw_text(draw, quote, fnt(38), T1, PAD+28, Y, CW-PAD*2-40, 10)
    Y += 8
    draw_text(draw, attr, fnt(32, mono=True), T3, PAD+28, Y, CW-PAD*2-40)

    draw_footer(canvas, draw,
                f"SL  ·  {data.get('score','')}  ·  {data.get('tier','').upper()}",
                DYN_H)
    draw_header(canvas, draw,
                f"FULL EVALUATION  ·  {data.get('asset','')}",
                'APEX DDI ENGINE  ·  RATED BY SCIENCE')
    canvas.save(out_path, 'JPEG', quality=96)
    return out_path


def build_card(photo_path, data, out_path):
    card2_path = out_path.replace('.jpg','_analysis.jpg').replace('.jpeg','_analysis.jpg')
    build_card1(photo_path, data, out_path)
    build_card2(data, card2_path)
    return out_path, card2_path
