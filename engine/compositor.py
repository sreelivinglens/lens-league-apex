"""
Apex Rating Card — v17
Larger everything. Matches share page visual weight.
Canvas: 1200px wide for better resolution and readability.
"""

from PIL import Image, ImageDraw, ImageFont
import os

FONT_DIR = os.path.dirname(os.path.abspath(__file__))
F_BOLD   = os.path.join(FONT_DIR, 'LiberationSans-Bold.ttf')
F_REG    = os.path.join(FONT_DIR, 'LiberationSans-Regular.ttf')
F_MONO   = os.path.join(FONT_DIR, 'DejaVuSansMono-Bold.ttf')
F_MONO_R = os.path.join(FONT_DIR, 'DejaVuSansMono.ttf')

def fnt(path, size):
    for p in [path,
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    ]:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

# ── Palette ───────────────────────────────────────────────────────────────────
BG        = (13,  13,  11)
S1        = (20,  20,  18)
S2        = (28,  28,  26)
S3        = (36,  36,  34)
BORDER    = (42,  42,  40)
BORDER_MD = (56,  56,  54)
T1        = (240, 239, 232)
T2        = (184, 182, 174)
T3        = (122, 120, 112)
GOLD      = (200, 168,  75)
GOLD_D    = (139, 105,  20)
GOLD_BG   = (22,  19,   8)
GREEN     = (76,  175, 115)
RED       = (224,  85,  85)
AMBER     = (224, 153,  64)

CW  = 1200
PAD = 40

def fh(font):
    d = ImageDraw.Draw(Image.new('RGB',(1,1)))
    return d.textbbox((0,0),'Ag',font=font)[3] + 4

def wrap(text, font, max_w, draw):
    if not text or not text.strip(): return []
    words, lines, cur = text.split(), [], []
    for w in words:
        test = ' '.join(cur+[w])
        if draw.textbbox((0,0),test,font=font)[2] > max_w and cur:
            lines.append(' '.join(cur)); cur=[w]
        else: cur.append(w)
    if cur: lines.append(' '.join(cur))
    return lines

def mh(text, font, max_w, draw, sp=6):
    ls = wrap(text,font,max_w,draw)
    return len(ls)*fh(font)+max(0,len(ls)-1)*sp if ls else 0

def dw(draw, text, font, color, x, y, max_w, sp=6):
    for line in wrap(text,font,max_w,draw):
        draw.text((x,y),line,font=font,fill=color); y+=fh(font)+sp
    return y

def build_card(photo_path, data, out_path):

    # ── Fonts — all larger for 1200px canvas ─────────────────────────────────
    fBrand   = fnt(F_MONO,   15)
    fEngine  = fnt(F_MONO_R, 12)
    fScore   = fnt(F_BOLD,   72)   # dominant — must be seen across a room
    fTier    = fnt(F_MONO,   16)
    fTitle   = fnt(F_BOLD,   24)
    fMeta    = fnt(F_REG,    15)
    fTag     = fnt(F_MONO_R, 13)
    fModLbl  = fnt(F_MONO_R, 13)
    fModVal  = fnt(F_BOLD,   30)   # large module scores
    fSecHdr  = fnt(F_MONO,   12)
    fSecBody = fnt(F_REG,    15)   # readable body text
    fByHdr   = fnt(F_MONO,   12)
    fByBody  = fnt(F_REG,    15)
    fByImp   = fnt(F_BOLD,   15)
    fBadgeH  = fnt(F_MONO,   12)
    fBadge   = fnt(F_REG,    14)
    fFooter  = fnt(F_MONO_R, 12)

    dummy = ImageDraw.Draw(Image.new('RGB',(CW,10)))

    # ── Layout ────────────────────────────────────────────────────────────────
    HEADER_H = 52

    # Photo block
    PHOTO_W  = 420
    PHOTO_H  = 280
    PHOTO_X  = PAD
    PHOTO_PAD = 24

    # Score panel
    SP_W = 150
    SP_X = PHOTO_X + PHOTO_W + 24
    SP_H = PHOTO_H

    # Info panel
    INFO_X = SP_X + SP_W + 24
    INFO_W = CW - INFO_X - PAD

    PHOTO_BLOCK_H = PHOTO_H + PHOTO_PAD * 2

    # Module row
    MOD_H = PAD + fh(fModLbl) + 8 + fh(fModVal) + 12 + 5 + PAD

    # Two columns
    COL_GAP = 40
    COL_W   = (CW - PAD*2 - COL_GAP) // 2
    LC_X    = PAD
    RC_X    = PAD + COL_W + COL_GAP

    b1 = data.get('byline_1','').strip()
    b2 = data.get('byline_2_body','').strip()
    bg = [b for b in data.get('badges_g',[]) if b.strip()]
    bw = [b for b in data.get('badges_w',[]) if b.strip()]

    # Measure column heights
    lh = 0
    for _, body in data.get('rows',[]):
        lh += fh(fSecHdr) + 6
        lh += mh(body, fSecBody, COL_W, dummy, 6) if body.strip() else 0
        lh += 18

    rh  = fh(fByHdr)+6 + mh(b1,fByBody,COL_W,dummy,6) + 18
    rh += fh(fByHdr)+6 + mh(b2,fByImp,COL_W,dummy,6) + 20
    if bg: rh += fh(fBadgeH)+6 + mh(', '.join(bg),fBadge,COL_W,dummy,5) + 14
    if bw: rh += fh(fBadgeH)+6 + mh(', '.join(bw),fBadge,COL_W,dummy,5) + 14

    TWO_COL_H = max(lh, rh)
    FOOTER_H  = 52

    CH = HEADER_H + PHOTO_BLOCK_H + 1 + MOD_H + 1 + PAD + TWO_COL_H + PAD + FOOTER_H

    canvas = Image.new('RGB',(CW,CH),BG)
    draw   = ImageDraw.Draw(canvas)

    # ── GOLD HEADER ───────────────────────────────────────────────────────────
    draw.rectangle([0,0,CW,HEADER_H], fill=GOLD)
    draw.text((PAD,16), 'THE LENS LEAGUE', font=fBrand, fill=BG)
    et  = 'APEX DDI ENGINE  ·  FULL EVALUATION  ·  RATED BY SCIENCE. NOT OPINION.'
    etw = draw.textbbox((0,0),et,font=fEngine)[2]
    draw.text((CW-PAD-etw, 19), et, font=fEngine, fill=(40,30,5))

    # ── PHOTO BLOCK ───────────────────────────────────────────────────────────
    PB_Y = HEADER_H
    draw.rectangle([0,PB_Y,CW,PB_Y+PHOTO_BLOCK_H], fill=S1)

    PH_Y = PB_Y + PHOTO_PAD
    try:
        ph = Image.open(photo_path).convert('RGB')
        pw, phh = ph.size
        scale = max(PHOTO_W/pw, PHOTO_H/phh)
        nw, nh = int(pw*scale), int(phh*scale)
        ph = ph.resize((nw,nh), Image.LANCZOS)
        cx,cy = (nw-PHOTO_W)//2, (nh-PHOTO_H)//2
        ph = ph.crop((cx,cy,cx+PHOTO_W,cy+PHOTO_H))
        canvas.paste(ph,(PHOTO_X,PH_Y))
        draw.rectangle([PHOTO_X-1,PH_Y-1,PHOTO_X+PHOTO_W,PH_Y+PHOTO_H],
                       outline=BORDER_MD,width=1)
    except:
        draw.rectangle([PHOTO_X,PH_Y,PHOTO_X+PHOTO_W,PH_Y+PHOTO_H],fill=S3)

    # ── SCORE PANEL ───────────────────────────────────────────────────────────
    draw.rectangle([SP_X,PH_Y,SP_X+SP_W,PH_Y+SP_H],
                   fill=GOLD_BG, outline=GOLD_D, width=2)

    # Score number — centred, dominant
    sc  = str(data.get('score','0.0'))
    scb = draw.textbbox((0,0),sc,font=fScore)
    scw = scb[2]-scb[0]
    draw.text((SP_X+(SP_W-scw)//2, PH_Y+22), sc, font=fScore, fill=GOLD)

    # Tier
    tier = data.get('tier','').upper()
    tw   = draw.textbbox((0,0),tier,font=fTier)[2]
    draw.text((SP_X+(SP_W-tw)//2, PH_Y+SP_H-fh(fTier)-34), tier, font=fTier, fill=GOLD)

    # Tier pips
    tier_map = {'APPRENTICE':1,'PRACTITIONER':2,'MASTER':3,'GRANDMASTER':4,'LEGEND':5}
    active = tier_map.get(tier,1)
    pip_total = 5*14+4*5
    pip_x0 = SP_X+(SP_W-pip_total)//2
    pip_y  = PH_Y+SP_H-16
    for i in range(5):
        px = pip_x0+i*19
        draw.rectangle([px,pip_y,px+12,pip_y+6],
                       fill=GOLD if i<active else BORDER_MD)

    # ── IMAGE INFO ────────────────────────────────────────────────────────────
    IY = PH_Y + 12
    draw.text((INFO_X,IY), data.get('asset','Untitled'), font=fTitle, fill=T1)
    IY += fh(fTitle)+6

    draw.text((INFO_X,IY), data.get('meta',''), font=fMeta, fill=T2)
    IY += fh(fMeta)+5

    draw.text((INFO_X,IY), data.get('genre_tag',''), font=fTag, fill=T3)
    IY += fh(fTag)+8

    if data.get('soul_bonus'):
        draw.text((INFO_X,IY), '★  SOUL BONUS ACTIVE  —  AQ ≥ 8.0', font=fTag, fill=GOLD)
        IY += fh(fTag)+6

    iucn = data.get('iucn_tag','')
    if iucn:
        # Colour by IUCN status word
        iucn_up = iucn.upper()
        ic = RED if any(x in iucn_up for x in ['CRITICAL','ENDANGERED','VULNERABLE']) else \
             AMBER if 'CONCERN' in iucn_up else GREEN
        draw.text((INFO_X,IY), iucn, font=fTag, fill=ic)
        IY += fh(fTag)+6

    IY += 6
    archline = f"Affective State: {data.get('dec','')}   ·   Photographer: {data.get('credit','')}"
    dw(draw, archline, fMeta, T3, INFO_X, IY, INFO_W, 4)

    # ── DIVIDER 1 ─────────────────────────────────────────────────────────────
    D1 = PB_Y + PHOTO_BLOCK_H
    draw.rectangle([0,D1,CW,D1+1],fill=BORDER_MD)

    # ── MODULE SCORES ─────────────────────────────────────────────────────────
    draw.rectangle([0,D1+1,CW,D1+1+MOD_H],fill=S2)
    modules = data.get('modules',[])
    n  = max(len(modules),1)
    MW = (CW-PAD*2)//n
    max_sc = max((float(s) for _,s in modules if s), default=0)
    MY = D1+1+PAD

    for i,(name,score) in enumerate(modules):
        mx  = PAD+i*MW
        top = float(score)==max_sc
        col = GOLD if top else T2

        # Separator
        if i>0:
            sep_y1 = MY-6
            sep_y2 = MY+fh(fModLbl)+8+fh(fModVal)+14
            draw.rectangle([mx-1,sep_y1,mx,sep_y2],fill=BORDER)

        draw.text((mx+12,MY), name.upper(), font=fModLbl, fill=T3)
        draw.text((mx+12,MY+fh(fModLbl)+8), str(score), font=fModVal, fill=col)

        # Bar
        by2 = MY+fh(fModLbl)+8+fh(fModVal)+10
        bw2 = MW-28
        draw.rectangle([mx+12,by2,mx+12+bw2,by2+5],fill=S3)
        fw = int(bw2*float(score)/10)
        draw.rectangle([mx+12,by2,mx+12+fw,by2+5],fill=GOLD if top else GOLD_D)

    # ── DIVIDER 2 ─────────────────────────────────────────────────────────────
    D2 = D1+1+MOD_H
    draw.rectangle([0,D2,CW,D2+1],fill=BORDER_MD)

    # Gold left accent bar
    draw.rectangle([0,D2+1,5,CH-FOOTER_H],fill=GOLD_D)

    # ── TWO COLUMNS ───────────────────────────────────────────────────────────
    CYL = D2+1+PAD
    CYR = D2+1+PAD

    # LEFT — five analysis sections
    for label,body in data.get('rows',[]):
        lbl = label.replace('\\n',' ').replace('\n',' ').upper()
        draw.text((LC_X,CYL), lbl, font=fSecHdr, fill=GOLD)
        CYL += fh(fSecHdr)+6
        if body and body.strip():
            CYL = dw(draw,body,fSecBody,T2,LC_X,CYL,COL_W,6)
        CYL += 18

    # RIGHT — byline + badges
    draw.text((RC_X,CYR), 'APEX BYLINE', font=fByHdr, fill=GOLD)
    CYR += fh(fByHdr)+6
    if b1: CYR = dw(draw,b1,fByBody,T2,RC_X,CYR,COL_W,6)
    CYR += 18

    draw.text((RC_X,CYR), 'THE ONE IMPROVEMENT', font=fByHdr, fill=GOLD)
    CYR += fh(fByHdr)+6
    if b2: CYR = dw(draw,b2,fByImp,T1,RC_X,CYR,COL_W,6)
    CYR += 20

    if bg:
        draw.text((RC_X,CYR), 'STRENGTHS', font=fBadgeH, fill=GREEN)
        CYR += fh(fBadgeH)+6
        CYR = dw(draw,', '.join(bg),fBadge,GREEN,RC_X,CYR,COL_W,5)
        CYR += 14

    if bw:
        draw.text((RC_X,CYR), 'AREAS TO DEVELOP', font=fBadgeH, fill=RED)
        CYR += fh(fBadgeH)+6
        CYR = dw(draw,', '.join(bw),fBadge,RED,RC_X,CYR,COL_W,5)

    # ── FOOTER ────────────────────────────────────────────────────────────────
    FY = CH-FOOTER_H
    draw.rectangle([0,FY,CW,CH],fill=S1)
    draw.rectangle([0,FY,CW,FY+1],fill=BORDER_MD)
    draw.text((PAD,FY+17),
              'APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.  ·  LENS LEAGUE APEX',
              font=fFooter, fill=T3)
    stamp = f"LL · {data.get('score','')} · {tier}"
    sw = draw.textbbox((0,0),stamp,font=fFooter)[2]
    draw.text((CW-PAD-sw,FY+17), stamp, font=fFooter, fill=GOLD)

    canvas.save(out_path,'JPEG',quality=96,optimize=True)
    return out_path
