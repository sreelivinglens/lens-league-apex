"""
Apex Rating Cards — v23
Two landscape cards at A4 300dpi (2480x1754px).
Card 1: Photo + Score + Modules  
Card 2: Full Analysis (2 columns)
Site palette: cream bg, slate blue accents, dark text, gold for highlights only.
No shield badge. No bars under module scores.
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
CREAM   = (253, 252, 248)   # site bg #FDFCF8
SURFACE = (241, 239, 232)   # surface-3 #F1EFE8
BORDER  = (210, 208, 200)   # border #D3D1C7
SLATE   = ( 44,  62, 107)   # #2C3E6B — slate blue
T1      = ( 26,  26,  24)   # dark text #1A1A18
T2      = ( 74,  72,  64)   # muted text #4A4840
T3      = (136, 135, 128)   # hint text #888780
GOLD    = (200, 168,  75)   # gold accent — scores/highlights only
GOLD_D  = (139, 105,  20)   # dark gold
GREEN   = ( 59, 109,  17)   # #3B6D11
RED     = (160,  45,  45)   # #A02D2D
WHITE   = (255, 255, 255)

# ── Watermark config ─────────────────────────────────────────────────────────
# WATERMARK_MODE: 'diagonal' | 'corner' | 'none'
# WATERMARK_OPACITY: 0-255 (18 = ~7%, sweet spot for JPEG survival + invisibility)
WATERMARK_MODE    = 'corner'     # corner watermark — confirmed
WATERMARK_OPACITY = 18           # ~7% opacity
WATERMARK_TEXT    = '© SHUTTERLEAGUE.COM'

CW, CH   = 2480, 1754
PAD      = 80
HEADER_H = 100
FOOTER_H = 80

SITE_URL   = 'shutterleague.com'
LOGO_PATH  = os.path.join(FONT_DIR, 'shutterleague-logo-cropped.png')
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

def draw_header(canvas, draw, left, right):
    draw.rectangle([0,0,CW,HEADER_H], fill=SLATE)
    draw.text((PAD,28), left, font=fnt(36,bold=True,mono=True), fill=WHITE)
    rw = tw(draw,right,fnt(26,mono=True))
    draw.text((CW-PAD-rw,34), right, font=fnt(26,mono=True), fill=(180,190,210))

def draw_footer(canvas, draw, stamp, canvas_h=None):
    h = canvas_h or CH
    draw.rectangle([0,h-FOOTER_H,CW,h], fill=SLATE)
    draw.rectangle([0,h-FOOTER_H,CW,h-FOOTER_H+1], fill=(60,75,115))
    left = f'SHUTTER LEAGUE  ·  APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.  ·  {SITE_URL}'
    draw.text((PAD, h-FOOTER_H+26), left, font=fnt(26,mono=True), fill=(160,175,200))
    sw = tw(draw, stamp, fnt(28,bold=True,mono=True))
    draw.text((CW-PAD-sw, h-FOOTER_H+26), stamp, font=fnt(28,bold=True,mono=True), fill=GOLD)


def apply_watermark(canvas, x, y, w, h):
    """Apply watermark to the photo region of the card."""
    if WATERMARK_MODE == 'none':
        return

    wm_layer = PilImage.new('RGBA', (w, h), (0, 0, 0, 0))
    wm_draw  = ImageDraw.Draw(wm_layer)

    if WATERMARK_MODE == 'diagonal':
        # Diagonal repeating text across the full photo area
        wm_font = fnt(48, bold=True, mono=True)
        text    = f'{WATERMARK_TEXT} · EVALUATED · '
        # Rotate the whole layer by drawing diagonally
        import math
        angle   = -35
        # Draw rows of text across a larger canvas then crop
        big = PilImage.new('RGBA', (w * 3, h * 3), (0, 0, 0, 0))
        bd  = ImageDraw.Draw(big)
        step_y = 120
        for row in range(-h, h * 3, step_y):
            bd.text((-w, row), text * 6, font=wm_font,
                    fill=(255, 255, 255, WATERMARK_OPACITY))
        big = big.rotate(angle, expand=False)
        # Crop back to photo size, centred
        cx = (big.width  - w) // 2
        cy = (big.height - h) // 2
        wm_layer = big.crop((cx, cy, cx + w, cy + h))

    elif WATERMARK_MODE == 'corner':
        # Bottom-right corner badge
        wm_font  = fnt(40, bold=True, mono=True)
        text     = WATERMARK_TEXT
        tw_val   = wm_draw.textbbox((0, 0), text, font=wm_font)[2]
        th_val   = wm_draw.textbbox((0, 0), text, font=wm_font)[3]
        pad      = 20
        bx       = w - tw_val - pad * 2 - 10
        by       = h - th_val - pad * 2 - 10
        # Semi-transparent dark pill
        wm_draw.rectangle([bx - pad, by - pad, bx + tw_val + pad, by + th_val + pad],
                          fill=(44, 62, 107, int(WATERMARK_OPACITY * 4)))
        wm_draw.text((bx, by), text, font=wm_font,
                     fill=(255, 255, 255, min(255, WATERMARK_OPACITY * 5)))

    # Paste watermark onto canvas at photo position
    canvas.paste(wm_layer, (x, y), wm_layer)


def build_card1(photo_path, data, out_path):
    """Card 1 — Full-width photo top 60%, score/meta/modules band below (v35 magazine layout)"""
    canvas = PilImage.new('RGB',(CW,CH),CREAM)
    draw   = ImageDraw.Draw(canvas)

    INNER_H  = CH - HEADER_H - FOOTER_H
    PHOTO_H  = int(INNER_H * 0.60)
    BAND_Y   = HEADER_H + PHOTO_H
    BAND_H   = INNER_H - PHOTO_H

    try:
        ph = PilImage.open(photo_path).convert('RGB')
        pw, phh = ph.size
        # Scale to FIT (contain) — whole image visible, dark fill for letterbox/pillarbox
        scale = min(CW / pw, PHOTO_H / phh)
        nw, nh = int(pw * scale), int(phh * scale)
        ph = ph.resize((nw, nh), PilImage.LANCZOS)
        # Dark background behind image
        draw.rectangle([0, HEADER_H, CW, HEADER_H + PHOTO_H], fill=(20, 20, 18))
        # Centre the fitted image
        ox = (CW - nw) // 2
        oy = HEADER_H + (PHOTO_H - nh) // 2
        canvas.paste(ph, (ox, oy))
        apply_watermark(canvas, ox, oy, nw, nh)
    except:
        draw.rectangle([0, HEADER_H, CW, HEADER_H + PHOTO_H], fill=BORDER)

    score = str(data.get('score', '—'))
    tier  = data.get('tier', '').upper()

    # Module layout — calculated upfront so SW can reference MOD_X
    modules  = data.get('modules', [])
    n        = max(len(modules), 1)
    MOD_W    = int(CW * 0.55)
    MOD_X    = CW - MOD_W
    draw.rectangle([MOD_X, BAND_Y, CW, BAND_Y + BAND_H], fill=SURFACE)
    draw.rectangle([MOD_X, BAND_Y, MOD_X + 1, BAND_Y + BAND_H], fill=BORDER)
    MW     = (MOD_W - PAD) // n
    max_sc = max((float(s) for _, s in modules if s), default=0)
    _lbl_map = {
        'DoD':        ('DEPTH OF',   'DETAIL (DOD)'),
        'VD':         ('VISUAL',     'DISRUPTION'),
        'Disruption': ('VISUAL',     'DISRUPTION'),
        'DM':         ('DECISIVE',   'MOMENT (DM)'),
        'WF':         ('WONDER',     'FACTOR'),
        'Wonder':     ('WONDER',     'FACTOR'),
        'AQ':         ('AESTHETIC',  'QUALITY (AQ)'),
    }
    SX = PAD
    SW = MOD_X - PAD * 2
    SY = BAND_Y + 32

    draw.text((SX, SY), score, font=fnt(130, bold=True), fill=T1)
    score_w = tw(draw, score, fnt(130, bold=True))
    draw.text((SX + score_w + 24, SY + 20), tier, font=fnt(52, bold=True, mono=True), fill=SLATE)

    tier_map = {
        'ROOKIE':1, 'SHOOTER':1,
        'CONTENDER':2, 'CRAFTSMAN':2,
        'MAVERICK':3, 'MASTER':3,
        'GRANDMASTER':4, 'LEGEND':5,
    }
    active = tier_map.get(tier, 1)
    pip_y  = SY + lh(fnt(130, bold=True)) + 8
    for i in range(5):
        px = SX + i * 40
        draw.rectangle([px, pip_y, px+28, pip_y+14], fill=GOLD if i < active else BORDER)
    pip_y += 30

    draw.rectangle([SX, pip_y, SX+SW, pip_y+1], fill=BORDER)
    pip_y += 16

    # Title — smaller (fnt 36), half the previous size
    pip_y = draw_text(draw, data.get('asset', 'Untitled'), fnt(36, bold=True), T1, SX, pip_y, SW, 4)

    # Photographer line — "Photography · Name"
    credit = data.get('credit', '').strip()
    photographer_y = pip_y  # capture Y before drawing — modules align here
    if credit:
        pip_y = draw_text(draw, 'Photography · ' + credit, fnt(44, bold=True), T1, SX, pip_y, SW, 4)
    pip_y = draw_text(draw, data.get('meta', ''), fnt(34), T2, SX, pip_y, SW, 4)
    arch = "Affective State: " + data.get('dec', '')
    pip_y = draw_text(draw, arch, fnt(30, mono=True), T3, SX, pip_y, SW, 4)

    if data.get('soul_bonus'):
        pip_y += 10
        draw_text(draw, '★  SOUL BONUS ACTIVE  —  AQ ≥ 8.0', fnt(30, mono=True), GOLD, SX, pip_y, SW)

    # Module scores — labels align to photographer name line
    # LBL_Y is set to photographer_y so scores sit beside the name, not the top of the band
    LBL_Y = photographer_y

    for i, (name, mscore) in enumerate(modules):
        # Centre each module within its column
        mx  = MOD_X + PAD//2 + i * MW
        col_cx = mx + MW // 2
        top = float(mscore) == max_sc
        col = GOLD if top else T1
        # No vertical dividers — removed (were jarring)
        l1, l2 = _lbl_map.get(name, (name.upper(), ''))
        l1w = tw(draw, l1, fnt(30, mono=True))
        l2w = tw(draw, l2, fnt(30, mono=True))
        scw = tw(draw, str(mscore), fnt(76, bold=True))
        draw.text((col_cx - l1w//2, LBL_Y),                              l1, font=fnt(30, mono=True), fill=T2)
        draw.text((col_cx - l2w//2, LBL_Y+lh(fnt(30, mono=True))+4),    l2, font=fnt(30, mono=True), fill=T2)
        draw.text((col_cx - scw//2, LBL_Y+lh(fnt(30, mono=True))*2+14), str(mscore), font=fnt(76, bold=True), fill=col)

    draw_header(canvas, draw, 'SHUTTER LEAGUE', 'APEX DDI ENGINE  ·  FULL EVALUATION')
    draw_footer(canvas, draw, "SL · " + score + " · " + tier)
    canvas.save(out_path, 'JPEG', quality=96)
    return out_path
def build_card2(data, out_path):
    """Card 2 — Full Analysis, 2 columns, DYNAMIC height based on content."""

    COL_GAP = 80
    COL_W   = (CW - PAD*2 - COL_GAP)//2
    LX      = PAD
    RX      = PAD + COL_W + COL_GAP

    rows = data.get('rows',[])
    b1   = data.get('byline_1','').strip()
    b2   = data.get('byline_2_body','').strip()
    bg   = [b for b in data.get('badges_g',[]) if b.strip()]
    bw   = [b for b in data.get('badges_w',[]) if b.strip()]
    hard_truth    = data.get('hard_truth','').strip()
    edit_purist   = data.get('edit_purist','').strip()
    edit_standard = (data.get('edit_standard','') or data.get('edit_base','')).strip()
    edit_creative = data.get('edit_creative','').strip()

    def measure_section(dummy_draw, body, w):
        h  = lh(fnt(38,bold=True,mono=True)) + 20
        h += sum(lh(fnt(44))+12 for _ in wrap_lines(dummy_draw,body,fnt(44),w))
        h += 28 + 1
        return h

    dummy = ImageDraw.Draw(PilImage.new('RGB',(CW,100),CREAM))

    left_h = sum(measure_section(dummy,body,COL_W) for _,body in rows[:3])
    left_h += 10
    if bg:
        left_h += lh(fnt(38,bold=True,mono=True))+20
        left_h += sum(lh(fnt(44))+10 for _ in wrap_lines(dummy,', '.join(bg),fnt(44),COL_W))
        left_h += 24
    if bw:
        left_h += lh(fnt(38,bold=True,mono=True))+20
        left_h += sum(lh(fnt(44))+10 for _ in wrap_lines(dummy,', '.join(bw),fnt(44),COL_W))

    right_h = sum(measure_section(dummy,body,COL_W) for _,body in rows[3:])
    # Hard Truth callout box
    if hard_truth:
        HT_PAD = 24
        right_h += lh(fnt(38,bold=True,mono=True)) + 20
        right_h += sum(lh(fnt(44,bold=True))+12 for _ in wrap_lines(dummy,hard_truth,fnt(44,bold=True),COL_W-HT_PAD*2))
        right_h += HT_PAD*2 + 24
    right_h += lh(fnt(38,bold=True,mono=True))+20
    right_h += sum(lh(fnt(44))+12 for _ in wrap_lines(dummy,b1,fnt(44),COL_W))
    right_h += 28
    right_h += lh(fnt(38,bold=True,mono=True))+20
    right_h += sum(lh(fnt(44,bold=True))+12 for _ in wrap_lines(dummy,b2,fnt(44,bold=True),COL_W))
    # Edit tiers
    EDIT_PAD = 20
    edit_inner_w = COL_W - EDIT_PAD*2
    if edit_purist or edit_standard or edit_creative:
        right_h += 32  # spacer
        right_h += lh(fnt(38,bold=True,mono=True)) + 16  # EDIT GUIDE header
        for label, body in [('PURIST', edit_purist), ('STANDARD', edit_standard), ('CREATIVE', edit_creative)]:
            if body:
                right_h += lh(fnt(32,bold=True,mono=True)) + 8
                right_h += sum(lh(fnt(40))+10 for _ in wrap_lines(dummy,body,fnt(40),edit_inner_w))
                right_h += EDIT_PAD

    content_h = max(left_h, right_h)
    DYN_H = HEADER_H + PAD + content_h + PAD*4 + FOOTER_H

    canvas = PilImage.new('RGB',(CW, DYN_H), CREAM)
    draw   = ImageDraw.Draw(canvas)

    INNER_Y = HEADER_H + PAD
    LY = INNER_Y
    RY = INNER_Y

    def section(x, y, label, body, w, body_color=T2):
        draw.text((x,y), label.upper(), font=fnt(38,bold=True,mono=True), fill=SLATE)
        y += lh(fnt(38,bold=True,mono=True)) + 20
        y = draw_text(draw, body, fnt(44), body_color, x, y, w, 12)
        y += 28
        draw.rectangle([x, y-14, x+w, y-13], fill=BORDER)
        return y

    for label,body in rows[:3]:
        LY = section(LX, LY, label, body, COL_W)

    LY += 10
    if bg:
        draw.text((LX,LY), 'STRENGTHS', font=fnt(38,bold=True,mono=True), fill=GREEN)
        LY += lh(fnt(38,bold=True,mono=True)) + 20
        LY = draw_text(draw, ', '.join(bg), fnt(44), GREEN, LX, LY, COL_W, 10)
        LY += 24
    if bw:
        draw.text((LX,LY), 'AREAS TO DEVELOP', font=fnt(38,bold=True,mono=True), fill=RED)
        LY += lh(fnt(38,bold=True,mono=True)) + 20
        LY = draw_text(draw, ', '.join(bw), fnt(44), RED, LX, LY, COL_W, 10)

    for label,body in rows[3:]:
        RY = section(RX, RY, label, body, COL_W)

    # Hard Truth — gold-bordered callout box above gap analysis
    if hard_truth:
        HT_PAD = 24
        ht_lines = wrap_lines(draw, hard_truth, fnt(44,bold=True), COL_W - HT_PAD*2)
        ht_h = lh(fnt(38,bold=True,mono=True)) + 20 + sum(lh(fnt(44,bold=True))+12 for _ in ht_lines) + HT_PAD*2
        draw.rectangle([RX-8, RY, RX+COL_W+8, RY+ht_h], fill=SURFACE)
        draw.rectangle([RX-8, RY, RX-4, RY+ht_h], fill=GOLD)  # gold left border
        hy = RY + HT_PAD
        draw.text((RX+HT_PAD, hy), 'HARD TRUTH', font=fnt(38,bold=True,mono=True), fill=GOLD_D)
        hy += lh(fnt(38,bold=True,mono=True)) + 20
        draw_text(draw, hard_truth, fnt(44,bold=True), T1, RX+HT_PAD, hy, COL_W-HT_PAD*2, 12)
        RY += ht_h + 24

    # The One Improvement section — slate blue panel
    byline_top = RY
    # Apex Byline (gap analysis) — label + body
    draw.text((RX,RY), 'GAP ANALYSIS', font=fnt(38,bold=True,mono=True), fill=SLATE)
    RY += lh(fnt(38,bold=True,mono=True)) + 20
    RY = draw_text(draw, b1, fnt(44), T2, RX, RY, COL_W, 12)
    RY += 28

    # The One Improvement — slate blue box
    IMPROVE_PAD = 24
    improve_lines = wrap_lines(draw, b2, fnt(44,bold=True), COL_W - IMPROVE_PAD*2)
    improve_h = lh(fnt(38,bold=True,mono=True)) + 20 + sum(lh(fnt(44,bold=True))+12 for _ in improve_lines) + IMPROVE_PAD*2
    draw.rectangle([RX-8, RY, RX+COL_W+8, RY+improve_h], fill=SLATE)
    iy = RY + IMPROVE_PAD
    draw.text((RX+IMPROVE_PAD, iy), 'THE ONE IMPROVEMENT', font=fnt(38,bold=True,mono=True), fill=(180,190,210))
    iy += lh(fnt(38,bold=True,mono=True)) + 20
    draw_text(draw, b2, fnt(44,bold=True), WHITE, RX+IMPROVE_PAD, iy, COL_W-IMPROVE_PAD*2, 12)
    RY += improve_h + 20

    # Left border accent
    draw.rectangle([RX-24, byline_top, RX-16, RY], fill=GOLD_D)

    # Edit Guide — Purist / Standard / Creative tiers
    EDIT_PAD = 20
    edit_inner_w = COL_W - EDIT_PAD*2
    edit_entries = [
        ('PURIST',   (180,190,210), edit_purist),
        ('STANDARD', GOLD,          edit_standard),
        ('CREATIVE', (160,180,140), edit_creative),
    ]
    has_edits = any(body for _,_,body in edit_entries)
    if has_edits:
        RY += 12
        # Section header
        draw.text((RX, RY), 'EDIT GUIDE', font=fnt(38,bold=True,mono=True), fill=SLATE)
        RY += lh(fnt(38,bold=True,mono=True)) + 16
        draw.rectangle([RX, RY, RX+COL_W, RY+1], fill=BORDER)
        RY += 16
        for tier_label, tier_col, body in edit_entries:
            if not body:
                continue
            # Tier pill label
            draw.text((RX, RY), tier_label, font=fnt(32,bold=True,mono=True), fill=tier_col)
            sub_label = {'PURIST': 'Capture only. No editing.',
                         'STANDARD': 'Balanced. Light editing.',
                         'CREATIVE': 'Artistic. Heavy editing.'}[tier_label]
            sub_x = RX + tw(draw, tier_label, fnt(32,bold=True,mono=True)) + 16
            draw.text((sub_x, RY+4), f'· {sub_label}', font=fnt(28,mono=True), fill=T3)
            RY += lh(fnt(32,bold=True,mono=True)) + 8
            RY = draw_text(draw, body, fnt(40), T2, RX+EDIT_PAD, RY, edit_inner_w, 10)
            RY += EDIT_PAD

    draw_footer(canvas, draw, f"SL · {data.get('score','')} · {data.get('tier','').upper()}", DYN_H)
    draw_header(canvas, draw,
                f"FULL EVALUATION  ·  {data.get('asset','')}",
                'APEX DDI ENGINE  ·  RATED BY SCIENCE')
    canvas.save(out_path,'JPEG',quality=96)
    return out_path


def build_card(photo_path, data, out_path):
    card2_path = out_path.replace('.jpg','_analysis.jpg').replace('.jpeg','_analysis.jpg')
    build_card1(photo_path, data, out_path)
    build_card2(data, card2_path)
    return out_path, card2_path
