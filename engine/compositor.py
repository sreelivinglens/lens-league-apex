"""
Apex Rating Card — v18
Single column layout. Everything stacked top to bottom.
Large fonts. Generous spacing. Readable for everyone.
Canvas: 1000px wide, dynamic height.
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

CW  = 1000
PAD = 48

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

def mh(text, font, max_w, draw, sp=8):
    ls = wrap(text,font,max_w,draw)
    return len(ls)*fh(font)+max(0,len(ls)-1)*sp if ls else 0

def dw(draw, text, font, color, x, y, max_w, sp=8):
    for line in wrap(text,font,max_w,draw):
        draw.text((x,y),line,font=font,fill=color)
        y += fh(font)+sp
    return y

def divider(draw, y, color=None):
    draw.rectangle([0, y, CW, y+1], fill=color or BORDER_MD)
    return y+1

def build_card(photo_path, data, out_path):

    # ── Fonts — generous sizes for single column ──────────────────────────────
    fBrand   = fnt(F_MONO,   16)
    fEngine  = fnt(F_MONO_R, 13)
    fScore   = fnt(F_BOLD,   80)   # huge — dominant
    fTier    = fnt(F_MONO,   18)
    fTitle   = fnt(F_BOLD,   26)
    fMeta    = fnt(F_REG,    16)
    fTag     = fnt(F_MONO_R, 14)
    fModLbl  = fnt(F_MONO_R, 14)
    fModVal  = fnt(F_BOLD,   32)   # large module numbers
    fSecHdr  = fnt(F_MONO,   14)   # section header
    fSecBody = fnt(F_REG,    17)   # generous body text
    fByHdr   = fnt(F_MONO,   14)
    fByBody  = fnt(F_REG,    17)
    fByImp   = fnt(F_BOLD,   17)
    fBadgeH  = fnt(F_MONO,   13)
    fBadge   = fnt(F_REG,    16)
    fFooter  = fnt(F_MONO_R, 13)

    INNER_W = CW - PAD*2  # full width content area
    dummy   = ImageDraw.Draw(Image.new('RGB',(CW,10)))

    # ── Measure total height ──────────────────────────────────────────────────
    HEADER_H   = 56
    PHOTO_H    = 560   # tall photo — portrait friendly
    SCORE_BL_H = 160   # score + tier + pips block
    MOD_H      = PAD + fh(fModLbl)+8+fh(fModVal)+12+6+PAD  # module row

    # Measure analysis sections
    rows   = data.get('rows',[])
    b1     = data.get('byline_1','').strip()
    b2     = data.get('byline_2_body','').strip()
    bg     = [b for b in data.get('badges_g',[]) if b.strip()]
    bw_lst = [b for b in data.get('badges_w',[]) if b.strip()]

    body_h = 0
    for label,body in rows:
        body_h += PAD//2 + fh(fSecHdr)+6
        body_h += mh(body, fSecBody, INNER_W, dummy, 8) if body.strip() else 0
        body_h += PAD

    # Byline
    byline_h  = PAD//2 + fh(fByHdr)+6 + mh(b1,fByBody,INNER_W,dummy,8) + PAD
    byline_h += PAD//2 + fh(fByHdr)+6 + mh(b2,fByImp,INNER_W,dummy,8) + PAD

    # Badges
    badge_h = 0
    if bg:
        badge_h += PAD//2 + fh(fBadgeH)+6 + mh(', '.join(bg),fBadge,INNER_W,dummy,6) + PAD//2
    if bw_lst:
        badge_h += PAD//2 + fh(fBadgeH)+6 + mh(', '.join(bw_lst),fBadge,INNER_W,dummy,6) + PAD//2

    FOOTER_H = 56

    CH = (HEADER_H + PHOTO_H + SCORE_BL_H + 1 +
          MOD_H + 1 +
          body_h + 1 +
          byline_h + 1 +
          (badge_h + 1 if badge_h else 0) +
          FOOTER_H)

    canvas = Image.new('RGB',(CW,CH),BG)
    draw   = ImageDraw.Draw(canvas)

    # ── GOLD HEADER ───────────────────────────────────────────────────────────
    draw.rectangle([0,0,CW,HEADER_H], fill=GOLD)
    draw.text((PAD,17), 'THE LENS LEAGUE', font=fBrand, fill=BG)
    et  = 'APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.'
    etw = draw.textbbox((0,0),et,font=fEngine)[2]
    draw.text((CW-PAD-etw,20), et, font=fEngine, fill=(40,30,5))

    # ── PHOTO — full width ────────────────────────────────────────────────────
    PH_Y = HEADER_H
    try:
        ph = Image.open(photo_path).convert('RGB')
        pw,phh = ph.size
        scale = max(CW/pw, PHOTO_H/phh)
        nw,nh = int(pw*scale), int(phh*scale)
        ph = ph.resize((nw,nh),Image.LANCZOS)
        cx,cy = (nw-CW)//2, (nh-PHOTO_H)//2
        ph = ph.crop((cx,cy,cx+CW,cy+PHOTO_H))
        canvas.paste(ph,(0,PH_Y))
    except:
        draw.rectangle([0,PH_Y,CW,PH_Y+PHOTO_H],fill=S3)

    # ── SCORE BLOCK — dark overlay style ─────────────────────────────────────
    SB_Y = HEADER_H + PHOTO_H
    draw.rectangle([0,SB_Y,CW,SB_Y+SCORE_BL_H],fill=S1)

    # Score number — left side
    sc  = str(data.get('score','0.0'))
    scb = draw.textbbox((0,0),sc,font=fScore)
    scw = scb[2]-scb[0]
    draw.text((PAD, SB_Y+(SCORE_BL_H-fh(fScore))//2-4), sc, font=fScore, fill=GOLD)

    # Tier + pips — right side of score
    tier = data.get('tier','').upper()
    tx   = PAD + scw + 32
    ty   = SB_Y + (SCORE_BL_H-fh(fTier))//2 - 16
    draw.text((tx,ty), tier, font=fTier, fill=GOLD)

    # Tier pips
    tier_map = {'APPRENTICE':1,'PRACTITIONER':2,'MASTER':3,'GRANDMASTER':4,'LEGEND':5}
    active = tier_map.get(tier,1)
    pip_y = ty + fh(fTier) + 10
    for i in range(5):
        px = tx + i*22
        draw.rectangle([px,pip_y,px+14,pip_y+8],
                       fill=GOLD if i<active else BORDER_MD)

    # Image title + meta — right aligned
    title  = data.get('asset','Untitled')
    meta   = data.get('meta','')
    gtag   = data.get('genre_tag','')
    twid   = draw.textbbox((0,0),title,font=fTitle)[2]
    mwid   = draw.textbbox((0,0),meta, font=fMeta)[2]
    draw.text((CW-PAD-twid, SB_Y+24),             title, font=fTitle, fill=T1)
    draw.text((CW-PAD-mwid, SB_Y+24+fh(fTitle)+4),meta,  font=fMeta,  fill=T2)

    # Soul bonus
    soul_y = SB_Y + SCORE_BL_H - fh(fTag) - 18
    if data.get('soul_bonus'):
        draw.text((PAD,soul_y),'★  SOUL BONUS ACTIVE  —  AQ ≥ 8.0',font=fTag,fill=GOLD)
    if data.get('iucn_tag'):
        iucn = data['iucn_tag']
        iu   = iucn.upper()
        ic   = RED if any(x in iu for x in ['CRITICAL','ENDANGERED','VULNERABLE']) \
               else AMBER if 'NEAR' in iu else GREEN
        draw.text((PAD,soul_y), iucn, font=fTag, fill=ic)

    # Affective state + photographer — bottom of score block
    arch_line = f"Affective State: {data.get('dec','')}   ·   Photographer: {data.get('credit','')}"
    alw = draw.textbbox((0,0),arch_line,font=fTag)[2]
    draw.text((CW-PAD-alw, SB_Y+SCORE_BL_H-fh(fTag)-18), arch_line, font=fTag, fill=T3)

    # ── DIVIDER ───────────────────────────────────────────────────────────────
    y = divider(draw, SB_Y+SCORE_BL_H)

    # ── MODULE SCORES — full width ────────────────────────────────────────────
    draw.rectangle([0,y,CW,y+MOD_H],fill=S2)
    modules = data.get('modules',[])
    n       = max(len(modules),1)
    MW      = (CW-PAD*2)//n
    max_sc  = max((float(s) for _,s in modules if s),default=0)
    MY      = y+PAD

    for i,(name,score) in enumerate(modules):
        mx  = PAD+i*MW
        top = float(score)==max_sc
        col = GOLD if top else T2
        if i>0:
            draw.rectangle([mx-1,MY-6,mx,MY+fh(fModLbl)+8+fh(fModVal)+14],fill=BORDER)
        draw.text((mx+14,MY), name.upper(), font=fModLbl, fill=T3)
        draw.text((mx+14,MY+fh(fModLbl)+8), str(score), font=fModVal, fill=col)
        by2 = MY+fh(fModLbl)+8+fh(fModVal)+10
        bw2 = MW-32
        draw.rectangle([mx+14,by2,mx+14+bw2,by2+6],fill=S3)
        fw  = int(bw2*float(score)/10)
        draw.rectangle([mx+14,by2,mx+14+fw,by2+6],fill=GOLD if top else GOLD_D)

    y = divider(draw, y+MOD_H)

    # ── ANALYSIS SECTIONS — single column, full width ─────────────────────────
    y += PAD//2
    for label,body in rows:
        lbl = label.replace('\\n',' ').replace('\n',' ').upper()
        # Gold label
        draw.text((PAD,y), lbl, font=fSecHdr, fill=GOLD)
        y += fh(fSecHdr)+6
        # Body text
        if body and body.strip():
            y = dw(draw,body,fSecBody,T2,PAD,y,INNER_W,8)
        y += PAD
        # Subtle rule between sections
        if label != rows[-1][0]:
            draw.rectangle([PAD,y-PAD//2,CW-PAD,y-PAD//2+1],fill=BORDER)

    y = divider(draw, y)

    # ── APEX BYLINE — full width ──────────────────────────────────────────────
    # Left gold accent bar
    draw.rectangle([0,y,5,y+byline_h-1],fill=GOLD_D)
    y += PAD//2

    draw.text((PAD,y), 'APEX BYLINE', font=fByHdr, fill=GOLD)
    y += fh(fByHdr)+6
    if b1: y = dw(draw,b1,fByBody,T2,PAD,y,INNER_W,8)
    y += PAD

    draw.text((PAD,y), 'THE ONE IMPROVEMENT', font=fByHdr, fill=GOLD)
    y += fh(fByHdr)+6
    if b2: y = dw(draw,b2,fByImp,T1,PAD,y,INNER_W,8)
    y += PAD

    # ── BADGES — full width ───────────────────────────────────────────────────
    if bg or bw_lst:
        y = divider(draw,y)
        y += PAD//2
        if bg:
            draw.text((PAD,y), 'STRENGTHS', font=fBadgeH, fill=GREEN)
            y += fh(fBadgeH)+6
            y = dw(draw,', '.join(bg),fBadge,GREEN,PAD,y,INNER_W,6)
            y += PAD//2
        if bw_lst:
            draw.text((PAD,y), 'AREAS TO DEVELOP', font=fBadgeH, fill=RED)
            y += fh(fBadgeH)+6
            y = dw(draw,', '.join(bw_lst),fBadge,RED,PAD,y,INNER_W,6)
            y += PAD//2
        y = divider(draw,y)

    # ── FOOTER ────────────────────────────────────────────────────────────────
    FY = CH-FOOTER_H
    draw.rectangle([0,FY,CW,CH],fill=S1)
    draw.rectangle([0,FY,CW,FY+1],fill=BORDER_MD)
    draw.text((PAD,FY+20),
              'APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.  ·  LENS LEAGUE APEX',
              font=fFooter,fill=T3)
    stamp = f"LL · {data.get('score','')} · {tier}"
    sw    = draw.textbbox((0,0),stamp,font=fFooter)[2]
    draw.text((CW-PAD-sw,FY+20), stamp, font=fFooter, fill=GOLD)

    canvas.save(out_path,'JPEG',quality=96,optimize=True)
    return out_path
