"""
Shutter League — Reportlab Scorecard PDF
SL-VERSION: 237.2 (Session 237, 2026-10-06 — naming fix only: "Dimension observations" section's
dim_obs_aq row was labelled "Authentic Quality", which conflicted with the canonical public
definition at shutterleague.com/science ("Emotion" / "The Emotion It Creates") — a contradiction
SOURCE_REGISTER_S235.md had already flagged as unresolved. Founder decision: relabel to
"Emotion (AQ)". Internal dict key (dim_obs_aq) unchanged — display label only. Companion edits in
app.py (182.99) and auto_score.py (171.48) make the same relabel elsewhere it was hardcoded.
NOT YET CONFIRMED LIVE. RETAINS 237.1.)
SL-VERSION: 237.1 (Session 237, 2026-10-05 — founder-reported: "Save Card" PDF was
missing roughly half of what the web evaluation page shows, and not matching its
"quality". Root cause was NOT this file — build_scorecard_pdf() already accepted and
rendered impression/what_next/body_of_work/master_name/master_why/dim_obs_*/tech_read/
visual_flow/imagine/species_note; app.py's download_card_pdf() route simply never put
them in the data dict it handed to this function. That data-wiring fix lives in app.py,
not here. This file's own changes, this version:
  (1) NEW page-1 "certificate" treatment, founder-approved direction (logo stays small/
      header-sized, NOT full-page — explicit founder instruction): thin double-rule gold
      frame around page 1 only; photographer credit promoted from a small line into its
      own larger serif-styled name block beside the score, so the page reads as "this
      person's accomplishment" rather than a data table with a byline.
  (2) NEW _TrustBadgeRow flowable — renders the same three fixed trust marks the web
      page shows (AI verified / Calibrated · 312 images / Expert calibrated). These are
      static labels on the web template too (confirmed — not computed from live data),
      so they are passed in as a plain list, not computed here.
  (3) NEW _DistBar flowable — horizontal 0–10 distribution bar with the score position
      and the fixed 8.5 awards threshold marked, matching the web's score/10*100 bar
      (clamped 2–98%), not a real cross-platform statistical distribution.
  (4) NEW _SparkFlowable + "How you're developing" section — per-dimension trend
      sparkline, current value and trend pill (Climbing/Steady/Dipped), fed by the same
      portfolio_data structure app.py's public_card() route already builds elsewhere.
  (5) NEW "A pattern in your work" box — renders whatever pre-selected canned message
      app.py passes in (the selection logic / message text itself lives in app.py,
      mirrored from image_detail.html's existing Jinja logic — nothing AI-generated).
  (6) NEW percentile line and awards-progress line under the score block.
  All additions are purely additive — every section only renders if its data key is
  present and non-empty, so a caller that still doesn't pass the new keys gets the old
  PDF exactly as before. NOT YET CONFIRMED LIVE — per Rules 3/16, needs the founder's
  push + Railway output + a real PDF download test before this counts as working.
  RETAINS 214.1.
)

SL-VERSION: 214.1 (Session 214, 2026-09-06 — Full rewrite: raw canvas → Platypus
flowables. Eliminates truncation on all long-text sections. Auto-paginates.
Adds missing fields: impression, what_next, body_of_work, master_name/why,
dim_obs per dimension, visual_flow, tech_read, imagine, species_note.
Fixes _clean(): bullets now split to paragraphs not collapsed to spaces.
Applies to Sonnet scorecard PDF (build_scorecard_pdf).
Haiku PDF already uses Platypus — no change needed there.
)

Entry point: build_scorecard_pdf(data: dict) -> bytes
"""

import io, re, textwrap

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, Image as RLImage, PageBreak, KeepTogether,
    CondPageBreak,
)
from reportlab.platypus.flowables import Flowable
import requests

# ── Palette ───────────────────────────────────────────────────────────────────
NAVY_DK   = colors.HexColor('#1A2A3A')
GOLD      = colors.HexColor('#B8860B')
GOLD_DK   = colors.HexColor('#8B6508')
GOLD_LT   = colors.HexColor('#FFF8EC')
GOLD_BD   = colors.HexColor('#EDD89A')
CREAM     = colors.HexColor('#F6F2E9')
DARK      = colors.HexColor('#1A1A18')
DARK2     = colors.HexColor('#3A3A38')
MUTED     = colors.HexColor('#555555')
BORDER    = colors.HexColor('#D0CAB8')
SKY       = colors.HexColor('#D6EAF8')
SKY_LT    = colors.HexColor('#EBF5FB')
BLUE_DK   = colors.HexColor('#1A6A9A')
GREEN_DK  = colors.HexColor('#1A6A3A')
GREEN_LT  = colors.HexColor('#E8F2EC')
GREEN_BD  = colors.HexColor('#A8CEB0')
GREEN_TXT = colors.HexColor('#1A3A2A')
GREEN_LBL = colors.HexColor('#2A6A3A')
ROSE_DK   = colors.HexColor('#8A3A6A')
PURPLE_LT = colors.HexColor('#F5F0FF')
PURPLE_BD = colors.HexColor('#C4B8EE')
PURPLE_TXT= colors.HexColor('#2a1060')
PURPLE_LBL= colors.HexColor('#4a3280')
BLUE_LT   = colors.HexColor('#F6F8FF')
BLUE_BD   = colors.HexColor('#C5D0EE')
BLUE_LBL  = colors.HexColor('#185FA5')
PINK_LT   = colors.HexColor('#FFF0F5')
PINK_BD   = colors.HexColor('#F5C0D0')
PINK_LBL  = colors.HexColor('#A0304A')
PISTA_LT  = colors.HexColor('#E8F5E2')
PISTA_BD  = colors.HexColor('#C5E0BB')
PISTA_TXT = colors.HexColor('#1a3a1a')
WHITE     = colors.white

TIER_ORDER = ['Rookie','Shooter','Contender','Craftsman',
              'Maverick','Master','Grandmaster','Legend']

ROW_ACCENTS = [GOLD, BLUE_DK, GREEN_DK, ROSE_DK]

# ── Text cleaning ─────────────────────────────────────────────────────────────
def _clean(text):
    """Strip audit JSON artifacts. Bullets → paragraph breaks (not spaces)."""
    if not text:
        return ''
    # Drop truncated preview (everything up to first '…' when near start)
    ell = text.find('…')
    if 0 < ell < 250:
        text = text[ell + 1:].lstrip('\n ')
    # ■ / ▪ / • bullets → paragraph separator
    text = re.sub(r'\s*[■▪•]\s*', '\n', text)
    # Strip **bold** markdown (PDF renders Paragraph XML — use <b> instead)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    # Collapse blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Collapse horizontal whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()

def _paras(text, style):
    """Split cleaned text on newlines → list of Paragraphs."""
    if not text:
        return []
    out = []
    for blk in text.split('\n'):
        blk = blk.strip()
        if blk:
            try:
                out.append(Paragraph(blk, style))
            except Exception:
                out.append(Paragraph(re.sub(r'<[^>]+>', '', blk), style))
    return out

# ── Style factory ─────────────────────────────────────────────────────────────
def _sty(name, font='Helvetica', size=10, leading=None,
         colour=DARK, align=TA_LEFT, bold=False,
         space_before=0, space_after=4,
         left_indent=0, first_indent=0):
    return ParagraphStyle(
        name,
        fontName='Helvetica-Bold' if bold else font,
        fontSize=size,
        leading=leading or round(size * 1.5),
        textColor=colour,
        alignment=align,
        spaceBefore=space_before,
        spaceAfter=space_after,
        leftIndent=left_indent,
        firstLineIndent=first_indent,
    )

# ── Tinted box flowable ───────────────────────────────────────────────────────
class _TintBox(Flowable):
    """Draws a tinted rounded-rect card around child flowables."""
    def __init__(self, contents, bg, border_color, pad=8):
        super().__init__()
        self._contents = contents
        self._bg       = bg
        self._bd       = border_color
        self._pad      = pad

    def wrap(self, avail_w, avail_h):
        self._avail_w = avail_w
        inner_w = avail_w - 2 * self._pad
        self._inner_h = sum(
            f.wrap(inner_w, avail_h)[1] + (f.style.spaceAfter if hasattr(f, 'style') else 0)
            for f in self._contents
        )
        self._h = self._inner_h + 2 * self._pad
        return avail_w, self._h

    def draw(self):
        c = self.canv
        c.setFillColor(self._bg)
        c.setStrokeColor(self._bd)
        c.setLineWidth(0.5)
        c.roundRect(0, 0, self._avail_w, self._h, 4, fill=1, stroke=1)
        inner_w = self._avail_w - 2 * self._pad
        y = self._h - self._pad
        for f in self._contents:
            fw, fh = f.wrap(inner_w, y)
            sa = f.style.spaceAfter if hasattr(f, 'style') else 0
            y -= fh
            f.drawOn(c, self._pad, y)
            y -= sa
        c.setFillColor(DARK)  # reset

class _AccentBar(Flowable):
    """Left accent bar for section headers — matches web scorecard style."""
    def __init__(self, label, accent_color, width):
        super().__init__()
        self._label  = label
        self._accent = accent_color
        self._width  = width
        self._h      = 6 * mm

    def wrap(self, avail_w, avail_h):
        return avail_w, self._h

    def draw(self):
        c = self.canv
        c.setFillColor(self._accent)
        c.rect(0, 1*mm, 2.5, self._h - 2*mm, fill=1, stroke=0)
        c.setFont('Helvetica-Bold', 8)
        c.setFillColor(self._accent)
        c.drawString(5*mm, 2*mm, self._label.upper())


def _draw_page1_frame(canvas, doc, page_w=None, page_h=None, margin=None, inset=4*mm):
    """Thin double-rule gold frame drawn on page 1 only — the 'certificate'
    cue the founder asked for. Logo/header stay their normal small size;
    this is the only new visual element on page 1, and it is a border, not
    new printed text or a bigger logo.

    SL-VERSION fix (post-render QA, Session 237): the original version of
    this was a zero-footprint Flowable placed first in the story. That is
    wrong — a Flowable's draw() canvas is already translated to wherever
    Platypus placed it in the text flow, NOT the page origin, so "absolute"
    coordinates inside a Flowable.draw() land in the wrong place (only a
    sliver near the top of the page rendered). A SimpleDocTemplate onPage
    callback's canvas is the real, untranslated page canvas, so this now
    runs as doc.build(story, onFirstPage=...) instead. Caught by rendering
    and visually inspecting a real test PDF before this went anywhere near
    the founder — exactly what Session 189's incident report says must
    happen before a visual claim is made."""
    pw = page_w if page_w is not None else canvas._pagesize[0]
    ph = page_h if page_h is not None else canvas._pagesize[1]
    m  = margin if margin is not None else 14 * mm
    x0 = m - inset
    y0 = m - inset
    w  = pw - 2 * (m - inset)
    h  = ph - 2 * (m - inset)
    canvas.saveState()
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(1.1)
    canvas.rect(x0, y0, w, h, fill=0, stroke=1)
    canvas.setStrokeColor(GOLD_BD)
    canvas.setLineWidth(0.4)
    canvas.rect(x0 + 2.2*mm, y0 + 2.2*mm, w - 4.4*mm, h - 4.4*mm, fill=0, stroke=1)
    canvas.restoreState()


def _draw_badge_icon(c, kind, cx, cy, size, color):
    """Draws a small vector icon (no text glyph) at (cx, cy), size = full
    bounding box side length. Used instead of the Unicode symbols ✓ ◉ ★,
    which are outside Helvetica's WinAnsi encoding and rendered as broken
    glyph boxes on real output — confirmed by rasterizing a test PDF, not
    assumed. A drawn shape works on every PDF viewer, with no font/glyph
    dependency, so it's the production-safe fix rather than swapping fonts."""
    r = size / 2.0
    c.saveState()
    if kind == 'check':
        c.setStrokeColor(color)
        c.setLineWidth(1.1)
        c.setLineCap(1)  # round cap
        c.setLineJoin(1)
        p = c.beginPath()
        p.moveTo(cx - r * 0.75, cy - r * 0.05)
        p.lineTo(cx - r * 0.15, cy - r * 0.65)
        p.lineTo(cx + r * 0.8,  cy + r * 0.6)
        c.drawPath(p, stroke=1, fill=0)
    elif kind == 'dot':
        c.setFillColor(color)
        c.circle(cx, cy, r * 0.62, stroke=0, fill=1)
    elif kind == 'star':
        import math
        c.setFillColor(color)
        points = []
        for i in range(10):
            ang = math.pi / 2 + i * math.pi / 5
            rad = r if i % 2 == 0 else r * 0.42
            points.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
        p = c.beginPath()
        p.moveTo(*points[0])
        for pt in points[1:]:
            p.lineTo(*pt)
        p.close()
        c.drawPath(p, stroke=0, fill=1)
    c.restoreState()


class _TrustBadgeRow(Flowable):
    """Three trust-mark pills shown below the photo.

    SL-VERSION fix (Session 237): the middle badge's "Calibrated · 312
    images" was a hardcoded, never-updating number — confirmed stale
    (frozen at 312 while the platform has long since passed that). Founder:
    "the 312 -change that to dynamic state from here on." Now takes
    calibrated_count from the caller (build_scorecard_pdf's data dict,
    itself read live from the DB in app.py) and falls back to 312 only if
    the caller passes nothing, so an old call site never breaks.

    SL-VERSION fix (post-render QA, Session 237): the icon characters were
    originally embedded in the label string itself (✓ ◉ ★). Rendered and
    rasterized a real test PDF before calling this done, per the Session
    189 incident report — the icons came out as broken glyph boxes because
    those Unicode code points aren't in Helvetica's WinAnsi encoding. Now
    each icon is drawn as its own small vector shape via _draw_badge_icon,
    and the label is plain ASCII text — no font/glyph dependency at all."""

    def __init__(self, width, extra_badge=None, calibrated_count=None):
        super().__init__()
        self._width = width
        _count = calibrated_count if calibrated_count else 312
        self._badges = [
            ('check', 'AI verified',                         GREEN_LT, GREEN_BD, GREEN_LBL),
            ('dot',   f'Calibrated · {_count} images',       SKY_LT,   BLUE_BD,  BLUE_LBL),
            ('star',  'Expert calibrated',                   GOLD_LT,  GOLD_BD,  GOLD_DK),
        ]
        if extra_badge:
            self._badges.append(extra_badge)
        self._h = 7.5 * mm

    def wrap(self, avail_w, avail_h):
        return avail_w, self._h

    def draw(self):
        c = self.canv
        c.setFont('Helvetica-Bold', 7.5)
        x = 0
        pad_x, gap, icon_gap = 3.2*mm, 2.5*mm, 1.6*mm
        icon_size = 2.6 * mm
        for kind, label, bg, bd, txt in self._badges:
            tw = c.stringWidth(label, 'Helvetica-Bold', 7.5)
            bw = tw + 2 * pad_x + icon_size + icon_gap
            c.setFillColor(bg)
            c.setStrokeColor(bd)
            c.setLineWidth(0.5)
            c.roundRect(x, 0, bw, self._h, self._h/2, fill=1, stroke=1)
            icon_cx = x + pad_x + icon_size / 2
            _draw_badge_icon(c, kind, icon_cx, self._h / 2, icon_size, txt)
            c.setFillColor(txt)
            text_x = x + pad_x + icon_size + icon_gap
            c.drawString(text_x, self._h/2 - 2.6, label)
            x += bw + gap
        c.setFillColor(DARK)


class _DistBar(Flowable):
    """Score position on a 0-10 bar, with the fixed 8.5 awards threshold marked.
    Matches the web's own math (score/10*100, clamped 2-98%) — not a real
    cross-platform statistical distribution, same as the web page."""
    def __init__(self, score, width, threshold=8.5):
        super().__init__()
        self._score, self._width, self._threshold = score, width, threshold
        self._h = 13 * mm

    def wrap(self, avail_w, avail_h):
        return avail_w, self._h

    def draw(self):
        c = self.canv
        track_y = 7 * mm
        track_w = self._width
        pct = max(2, min(98, (self._score / 10.0) * 100)) / 100.0
        x_score  = track_w * pct
        x_thresh = track_w * (self._threshold / 10.0)

        c.setStrokeColor(BORDER)
        c.setLineWidth(1.4)
        c.line(0, track_y, track_w, track_y)

        c.setStrokeColor(GOLD_DK)
        c.setLineWidth(1)
        c.line(x_thresh, track_y - 2.2*mm, x_thresh, track_y + 2.2*mm)
        c.setFont('Helvetica-Bold', 6.5)
        c.setFillColor(GOLD_DK)
        c.drawCentredString(x_thresh, track_y + 3*mm, f'{self._threshold:.1f} · Awards')

        c.setFillColor(NAVY_DK)
        c.circle(x_score, track_y, 2.8, fill=1, stroke=0)
        c.setFont('Helvetica-Bold', 8.5)
        c.setFillColor(DARK)
        c.drawCentredString(x_score, track_y - 6*mm, f'{self._score:.2f}')

        c.setFont('Helvetica', 6.5)
        c.setFillColor(MUTED)
        c.drawString(0, track_y - 6*mm, '0')
        c.drawRightString(track_w, track_y - 6*mm, '10')
        c.setFillColor(DARK)


class _SparkFlowable(Flowable):
    """Small trend polyline — same point geometry the web page's inline SVG
    polyline uses (0-300 x, 0-30 y coordinate space), just drawn on canvas."""
    def __init__(self, points, color, width=40*mm, height=9*mm):
        super().__init__()
        self._points, self._color = points, color
        self._w, self._h = width, height

    def wrap(self, avail_w, avail_h):
        return self._w, self._h

    def draw(self):
        if not self._points or len(self._points) < 2:
            return
        c = self.canv
        sx, sy = self._w / 300.0, self._h / 30.0
        c.setStrokeColor(self._color)
        c.setLineWidth(1.3)
        p = c.beginPath()
        first = self._points[0]
        p.moveTo(first['x']*sx, self._h - first['y']*sy)
        for pt in self._points[1:]:
            p.lineTo(pt['x']*sx, self._h - pt['y']*sy)
        c.drawPath(p, stroke=1, fill=0)


def _dim_history_row(dim, avail_w):
    """One row of the 'How you're developing' section: label+current value,
    trend pill text, sparkline. Returns a Table flowable."""
    lbl_sty  = _sty('dhl', size=9,  leading=12, colour=DARK,  bold=True,  space_after=0)
    cur_sty  = _sty('dhc', size=13, leading=15, colour=DARK,  bold=True,  space_after=0)
    pill_sty = _sty('dhp', size=7.5,leading=10, colour=colors.HexColor(dim.get('pill_color') or '#854F0B'),
                     bold=True, space_after=0)
    label_cell = [Paragraph(dim.get('label',''), lbl_sty),
                  Paragraph(f"{dim.get('current',0):.1f}", cur_sty)]
    spark_cell = [_SparkFlowable(dim.get('points') or [],
                                  colors.HexColor(dim.get('color') or '#D6A428'))]
    pill_cell  = [Paragraph(dim.get('pill') or '', pill_sty)] if dim.get('pill') else [Spacer(1,1)]
    row = Table([[label_cell, spark_cell, pill_cell]],
                colWidths=[avail_w*0.22, avail_w*0.46, avail_w*0.32])
    row.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('BOX', (0,0), (-1,-1), 0.3, BORDER),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    return row

# ── Logo fetch ────────────────────────────────────────────────────────────────────────────────
_LOGO_CACHE = None

def _fetch_logo():
    """Fetch SL logo once, cache in module scope. Falls back silently."""
    global _LOGO_CACHE
    if _LOGO_CACHE is not None:
        return _LOGO_CACHE
    import os as _os
    _site = _os.getenv('SITE_URL', 'https://shutterleague.com')
    _url  = f"{_site.rstrip('/')}/static/img/shutterleague-logo-cropped.png"
    try:
        r = requests.get(_url, timeout=6, headers={'User-Agent': 'ShutterLeague-PDF/2.0'})
        r.raise_for_status()
        _LOGO_CACHE = io.BytesIO(r.content)
        return _LOGO_CACHE
    except Exception as e:
        print(f'[reportlab_card] logo fetch: {e}')
        _LOGO_CACHE = False
        return None


# ── Photo fetch ───────────────────────────────────────────────────────────────
def _fetch_photo(url):
    if not url:
        return None
    try:
        r = requests.get(url, timeout=10, headers={'User-Agent': 'ShutterLeague-PDF/2.0'})
        r.raise_for_status()
        return io.BytesIO(r.content)
    except Exception as e:
        print(f'[reportlab_card] photo fetch: {e}')
        return None

# ── Tier dots table ───────────────────────────────────────────────────────────
def _tier_table(tier, avail_w):
    idx  = TIER_ORDER.index(tier) if tier in TIER_ORDER else -1
    cells = []
    styles = [
        ('FONTSIZE',    (0,0), (-1,-1), 6.5),
        ('ALIGN',       (0,0), (-1,-1), 'CENTER'),
        ('VALIGN',      (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',  (0,0), (-1,-1), 3),
        ('BOTTOMPADDING',(0,0), (-1,-1), 3),
        ('BOX',         (0,0), (-1,-1), 0.3, BORDER),
        ('INNERGRID',   (0,0), (-1,-1), 0.3, BORDER),
        ('TEXTCOLOR',   (0,0), (-1,-1), MUTED),
        ('BACKGROUND',  (0,0), (-1,-1), CREAM),
    ]
    for i, t in enumerate(TIER_ORDER):
        cells.append(t)
        if i == idx:
            styles += [
                ('BACKGROUND', (i,0), (i,0), GOLD),
                ('TEXTCOLOR',  (i,0), (i,0), WHITE),
                ('FONTNAME',   (i,0), (i,0), 'Helvetica-Bold'),
            ]
        elif i < idx:
            styles.append(('TEXTCOLOR', (i,0), (i,0), GOLD_DK))
    col_w = avail_w / len(TIER_ORDER)
    tbl = Table([cells], colWidths=[col_w]*len(TIER_ORDER))
    tbl.setStyle(TableStyle(styles))
    return tbl

# ── Dimension strip table ─────────────────────────────────────────────────────
def _dim_table(dim_breakdown, avail_w):
    if not dim_breakdown:
        return None
    n     = len(dim_breakdown)
    col_w = avail_w / n
    max_sc = max(d['score'] for d in dim_breakdown)

    label_row = []
    score_row = []
    for d in dim_breakdown:
        is_top = (d['score'] == max_sc)
        lbl_sty = _sty('dl', size=7, leading=9, colour=DARK2, align=TA_CENTER, bold=False)
        sc_sty  = _sty('ds', size=18, leading=22, colour=GOLD_DK if is_top else DARK,
                        align=TA_CENTER, bold=True)
        label_row.append(Paragraph(f"{d['l1']}<br/>{d['l2']}", lbl_sty))
        score_row.append(Paragraph(f"{d['score']:.1f}", sc_sty))

    tbl = Table([label_row, score_row], colWidths=[col_w]*n)
    styles = [
        ('ALIGN',         (0,0), (-1,-1), 'CENTER'),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('BOX',           (0,0), (-1,-1), 0.4, BORDER),
        ('INNERGRID',     (0,0), (-1,-1), 0.4, BORDER),
        ('BACKGROUND',    (0,0), (-1,-1), SKY_LT),
    ]
    # Highlight strongest
    for i, d in enumerate(dim_breakdown):
        if d['score'] == max_sc:
            styles.append(('BACKGROUND', (i,0), (i,1), GOLD_LT))
    tbl.setStyle(TableStyle(styles))
    return tbl

# ════════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINT
# ════════════════════════════════════════════════════════════════════════
def build_scorecard_pdf(data: dict) -> bytes:
    """
    Multi-page A4 Platypus PDF. Auto-paginates — no truncation possible.
    data keys (all optional, gracefully absent):
      score, tier, asset, credit, genre, format, location, evaluated_on
      photo_url
      affective_state, wso
      impression, what_next
      c1_body (transferable_advice), c2_body (wso/hard_truth),
      c3_body (background_check), c4_body (byline_2)
      body_of_work
      edit_base, edit_creative
      mentor_location_1, mentor_location_2
      master_name, master_why
      dim_breakdown  [{'score':float,'l1':str,'l2':str}, ...]
      dim_obs_dod, dim_obs_vd, dim_obs_dm, dim_obs_wf, dim_obs_aq
      tech_read, visual_flow, imagine, species_note
    """

    buf   = io.BytesIO()
    W, H  = A4
    M     = 14 * mm
    avail = W - 2 * M

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=M, rightMargin=M,
        topMargin=M,  bottomMargin=M,
        title=f"Shutter League Evaluation — {data.get('asset','')}",
        author='Shutter League',
    )

    # ── Styles ──────────────────────────────────────────────────────────────
    S = {
        'page_title': _sty('ptitle', size=9,  leading=11, colour=GOLD_DK,    bold=True,  space_after=1),
        'page_sub':   _sty('psub',   size=7,  leading=9,  colour=MUTED,       bold=False, space_after=6, align=TA_RIGHT),
        'score':      _sty('score',  size=52, leading=58, colour=DARK,        bold=True,  space_after=0),
        'denom':      _sty('denom',  size=18, leading=22, colour=MUTED,       bold=False, space_after=0),
        'tier':       _sty('tier',   size=11, leading=14, colour=GOLD_DK,     bold=True,  space_after=4),
        'meta':       _sty('meta',   size=8,  leading=11, colour=DARK2,       bold=False, space_after=2),
        'credit':     _sty('credit', size=9,  leading=12, colour=GOLD_DK,     bold=True,  space_after=2),
        'sec_label':  _sty('slbl',   size=8,  leading=10, colour=MUTED,       bold=True,  space_after=4, space_before=10),
        'body':       _sty('body',   size=11, leading=17, colour=DARK,        bold=False, space_after=5),
        'body_indent':_sty('bindi',  size=11, leading=17, colour=DARK,        bold=False, space_after=5, left_indent=8*mm),
        'body_it':    _sty('bodyi',  size=11, leading=17, colour=DARK2,       bold=False, space_after=5),
        'opening':    _sty('open',   size=13, leading=20, colour=DARK,        bold=True,  space_after=8),
        'impression': _sty('impr',   size=12, leading=18, colour=DARK,        bold=False, space_after=6),
        'master_name':_sty('mname',  size=14, leading=18, colour=GOLD_DK,     bold=True,  space_after=3),
        'master_why': _sty('mwhy',   size=11, leading=17, colour=DARK,        bold=False, space_after=6),
        'dim_obs_lbl':_sty('dolbl',  size=9,  leading=12, colour=GOLD_DK,     bold=True,  space_after=2, space_before=6),
        'dim_obs':    _sty('dobs',   size=11, leading=17, colour=DARK,        bold=False, space_after=4),
        'spec':       _sty('spec',   size=10, leading=15, colour=PISTA_TXT,   bold=False, space_after=4),
        'tech_lbl':   _sty('tlbl',   size=8,  leading=10, colour=BLUE_LBL,    bold=True,  space_after=3, space_before=8),
        'tech':       _sty('tech',   size=11, leading=17, colour=DARK,        bold=False, space_after=5),
        'vf_lbl':     _sty('vflbl',  size=8,  leading=10, colour=PURPLE_LBL,  bold=True,  space_after=3, space_before=8),
        'vf':         _sty('vf',     size=11, leading=17, colour=DARK,        bold=False, space_after=5),
        'imagine_lbl':_sty('imlbl',  size=8,  leading=10, colour=PURPLE_LBL,  bold=True,  space_after=3, space_before=8),
        'imagine':    _sty('imag',   size=11, leading=17, colour=PURPLE_TXT,  bold=False, space_after=5),
        'path9_lbl':  _sty('p9lbl',  size=8,  leading=10, colour=PINK_LBL,    bold=True,  space_after=3, space_before=8),
        'path9':      _sty('p9',     size=11, leading=17, colour=colors.HexColor('#3a1020'), bold=False, space_after=5),
        'edit_lbl':   _sty('elbl',   size=9,  leading=11, colour=GOLD_DK,     bold=True,  space_after=3, space_before=8),
        'edit':       _sty('edit',   size=11, leading=17, colour=DARK2,       bold=False, space_after=5),
        'loc_lbl':    _sty('lloc',   size=8,  leading=10, colour=GREEN_LBL,   bold=True,  space_after=3, space_before=8),
        'loc':        _sty('loc',    size=11, leading=17, colour=GREEN_TXT,   bold=False, space_after=5),
        'foot':       _sty('foot',   size=7,  leading=9,  colour=MUTED,       bold=False, space_after=0, align=TA_CENTER),
        'quote':      _sty('quote',  size=10, leading=15, colour=MUTED,       bold=False, space_after=3),
        'quote_attr': _sty('qattr',  size=8,  leading=10, colour=colors.HexColor('#AAAAAA'), bold=False, space_after=0),
    }

    def HR(space_before=4, space_after=6):
        return HRFlowable(width='100%', thickness=0.4, color=BORDER,
                          spaceBefore=space_before, spaceAfter=space_after)

    story = []

    score_str = f"{float(data.get('score', 0)):.2f}"
    tier_str  = data.get('tier', '')
    asset     = data.get('asset', 'Untitled')
    credit    = (data.get('credit') or '').strip()

    # ════════════════════════════════
    # PAGE 1 — Photo · Score · Dims · Opening · Content rows
    # ════════════════════════════════

    # Certificate frame — border only, logo/header stay their normal small
    # size per founder instruction ("logo keep small readable not full page").
    # Drawn via onFirstPage below (see _draw_page1_frame), not as a story
    # flowable — a Flowable's draw() is translated to its flow position, not
    # the page origin, so it cannot draw a true page-edge border.

    # Header line — logo + brand text + right label
    _logo_bytes = _fetch_logo()
    _logo_buf   = io.BytesIO(_logo_bytes.getvalue()) if _logo_bytes else None
    _logo_flowable = None
    if _logo_buf:
        try:
            _logo_flowable = RLImage(_logo_buf, width=7*mm, height=7*mm, kind='proportional')
        except Exception:
            _logo_flowable = None

    if _logo_flowable:
        hdr_tbl = Table(
            [[_logo_flowable,
              Paragraph('SHUTTER LEAGUE', S['page_title']),
              Paragraph('APEX DDI ENGINE  ·  FULL EVALUATION', S['page_sub'])]],
            colWidths=[9*mm, avail * 0.45, avail - 9*mm - avail * 0.45],
        )
    else:
        hdr_tbl = Table(
            [[Paragraph('SHUTTER LEAGUE', S['page_title']),
              Paragraph('APEX DDI ENGINE  ·  FULL EVALUATION', S['page_sub'])]],
            colWidths=[avail * 0.5, avail * 0.5],
        )
    hdr_tbl.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(hdr_tbl)
    story.append(HR(space_before=2, space_after=8))

    # Trust marks — same three badges the web page shows. Middle one's count
    # is live (SL-237.2) — see _TrustBadgeRow's docstring.
    story.append(_TrustBadgeRow(avail, calibrated_count=data.get('calibrated_count')))
    story.append(Spacer(1, 8))

    # Photograph
    photo_bytes = _fetch_photo(data.get('photo_url'))
    if photo_bytes:
        try:
            img = RLImage(photo_bytes, width=avail, height=72*mm, kind='proportional')
            story.append(img)
            story.append(Spacer(1, 4))
        except Exception as e:
            print(f'[reportlab_card] photo embed: {e}')

    # Certificate name block — the photographer's name entered at upload,
    # promoted out of the small credit line into its own serif display,
    # so the page reads as this person's accomplishment first.
    if credit:
        name_sty = _sty('certname', size=20, leading=24, colour=NAVY_DK, bold=True, space_after=2)
        story.append(Paragraph(credit, name_sty))
        story.append(Paragraph('EVALUATED BY SHUTTER LEAGUE', _sty('certsub', size=7.5, leading=10,
                                 colour=MUTED, bold=True, space_after=6)))

    # Score + tier + meta — two-column
    score_block = [
        Paragraph(f'{score_str}<font size="16" color="#888888">/10</font>', S['score']),
        Paragraph(tier_str.upper(), S['tier']),
        _tier_table(tier_str, avail * 0.44),
    ]
    meta_lines = []
    meta_str = '  ·  '.join(filter(None, [
        data.get('genre',''), data.get('format',''),
        data.get('location',''), data.get('evaluated_on','')
    ]))
    if meta_str:
        meta_lines.append(Paragraph(meta_str, S['meta']))
    aff = _clean(data.get('affective_state', ''))
    if aff:
        meta_lines.append(Paragraph(aff, S['body_it']))
    percentile_text = (data.get('percentile_text') or '').strip()
    if percentile_text:
        meta_lines.append(Paragraph(percentile_text, _sty('pctl', size=9.5, leading=13,
                                      colour=GOLD_DK, bold=True, space_after=2)))
    award_text = (data.get('award_progress_text') or '').strip()
    if award_text:
        meta_lines.append(Paragraph(award_text, _sty('awdp', size=8.5, leading=12,
                                      colour=MUTED, bold=False, space_after=0)))

    lft = score_block
    rgt = meta_lines or [Spacer(1, 1)]

    score_meta = Table(
        [[lft, rgt]],
        colWidths=[avail * 0.46, avail * 0.54],
    )
    score_meta.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(score_meta)
    story.append(Spacer(1, 6))

    # Distribution bar — score position vs fixed 8.5 awards threshold
    try:
        _score_f = float(data.get('score', 0) or 0)
        story.append(_DistBar(_score_f, avail))
        story.append(Spacer(1, 4))
    except (TypeError, ValueError):
        pass

    # Dimensions
    dim_tbl = _dim_table(data.get('dim_breakdown', []), avail)
    if dim_tbl:
        story.append(dim_tbl)
        story.append(Spacer(1, 8))

    # Opening bold sentence (wso)
    wso = _clean(data.get('wso', ''))
    if wso:
        story.append(HR())
        for p in _paras(wso, S['opening']):
            story.append(p)

    # Impression
    impression = _clean(data.get('impression', ''))
    if impression:
        story.append(HR())
        for p in _paras(impression, S['impression']):
            story.append(p)

    # Section rows — use KeepTogether so label+body stay on same page
    def _section(label, raw, accent, body_style=None):
        body = _clean(raw)
        if not body:
            return
        bs = body_style or S['body']
        block = [_AccentBar(label, accent, avail)] + _paras(body, bs)
        story.append(KeepTogether(block[:4]))  # first 4 flowables together
        # remaining paragraphs flow freely (no truncation)
        for p in block[4:]:
            story.append(p)
        story.append(HR(space_before=2, space_after=4))

    _section("The photographer's advice",  data.get('c1_body',''), ROW_ACCENTS[0])
    _section("What you controlled",        data.get('c2_body',''), ROW_ACCENTS[1])
    _section("What to watch next",         data.get('c3_body',''), ROW_ACCENTS[2])
    _section("Keep this in mind",          data.get('c4_body',''), ROW_ACCENTS[3])

    # Body of work
    bow = _clean(data.get('body_of_work', ''))
    if bow:
        _section("Your next body of work", bow, GOLD_DK)

    # What next / path to 9
    what_next = _clean(data.get('what_next', ''))
    if what_next:
        story.append(Paragraph('Path to 9', S['path9_lbl']))
        for p in _paras(what_next, S['path9']):
            story.append(p)
        story.append(HR())

    # ────────────────────────────────
    # PAGE 2 — Deep analysis
    # ────────────────────────────────
    story.append(PageBreak())

    _logo_buf2 = io.BytesIO(_logo_bytes.getvalue()) if _logo_bytes else None
    _logo2 = None
    if _logo_buf2:
        try:
            _logo2 = RLImage(_logo_buf2, width=7*mm, height=7*mm, kind='proportional')
        except Exception:
            pass
    if _logo2:
        hdr2 = Table(
            [[_logo2,
              Paragraph('SHUTTER LEAGUE', S['page_title']),
              Paragraph(f'FULL EVALUATION  ·  {asset}', S['page_sub'])]],
            colWidths=[9*mm, avail * 0.45, avail - 9*mm - avail * 0.45],
        )
    else:
        hdr2 = Table(
            [[Paragraph('SHUTTER LEAGUE', S['page_title']),
              Paragraph(f'FULL EVALUATION  ·  {asset}', S['page_sub'])]],
            colWidths=[avail * 0.5, avail * 0.5],
        )
    hdr2.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(hdr2)
    story.append(HR(space_before=2, space_after=8))

    # Master reference
    master_name = (data.get('master_name') or '').strip()
    master_why  = _clean(data.get('master_why', ''))
    if master_name:
        box_contents = [
            Paragraph('Master reference', S['dim_obs_lbl']),
            Paragraph(master_name, S['master_name']),
        ]
        if master_why:
            box_contents += _paras(master_why, S['master_why'])
        story.append(KeepTogether(box_contents))
        story.append(HR())

    # Dimension observations
    # Session 237: 'Authentic Quality' relabelled to 'Emotion (AQ)' per founder
    # decision, reconciling against the canonical public definition at
    # shutterleague.com/science (dimension 5 = "Emotion" / "The Emotion It
    # Creates" — no "Aesthetic"/"Affective"/"Authentic Quality" anywhere on
    # that page). This was a real, live inconsistency: the PDF said "Authentic
    # Quality" while the public science page says "Emotion" for the same
    # number. Internal field key (dim_obs_aq / 'aq') is UNCHANGED — only this
    # display label moved, so nothing downstream that reads the 'aq' key
    # breaks. 'Wonder Factor' (science page calls it "The WOW Factor") is a
    # same-category mismatch, flagged separately, NOT changed here pending
    # its own founder decision.
    dim_obs_map = [
        ('dim_obs_dod', 'Depth of Difficulty'),
        ('dim_obs_vd',  'Visual Disruption'),
        ('dim_obs_dm',  'Decisive Moment'),
        ('dim_obs_wf',  'Wonder Factor'),
        ('dim_obs_aq',  'Emotion (AQ)'),
    ]
    has_dim_obs = any(_clean(data.get(k,'')) for k, _ in dim_obs_map)
    if has_dim_obs:
        story.append(Paragraph('Dimension observations', S['sec_label']))
        for key, label in dim_obs_map:
            obs = _clean(data.get(key, ''))
            if obs:
                block = [Paragraph(label, S['dim_obs_lbl'])] + _paras(obs, S['dim_obs'])
                story.append(KeepTogether(block[:3]))
                for p in block[3:]:
                    story.append(p)
        story.append(HR())

    # Technical read
    tech_read = _clean(data.get('tech_read', ''))
    if tech_read:
        story.append(Paragraph('Technical read', S['tech_lbl']))
        for p in _paras(tech_read, S['tech']):
            story.append(p)
        story.append(HR())

    # Visual flow
    visual_flow = _clean(data.get('visual_flow', ''))
    if visual_flow:
        story.append(Paragraph('Visual flow', S['vf_lbl']))
        for p in _paras(visual_flow, S['vf']):
            story.append(p)
        story.append(HR())

    # Imagine
    imagine = _clean(data.get('imagine', ''))
    if imagine:
        story.append(Paragraph('Imagine', S['imagine_lbl']))
        for p in _paras(imagine, S['imagine']):
            story.append(p)
        story.append(HR())

    # Species note (wildlife only)
    species_note = _clean(data.get('species_note', ''))
    if species_note:
        story.append(Paragraph('Species', S['tech_lbl']))
        for p in _paras(species_note, S['spec']):
            story.append(p)
        story.append(HR())

    # A pattern in your work — app.py selects the message (mirrors
    # image_detail.html's existing canned-message logic); this file just
    # renders whatever text it's given.
    pattern_text = (data.get('pattern_in_work_text') or '').strip()
    if pattern_text:
        box = _TintBox(
            [Paragraph('A pattern in your work', _sty('patlbl', size=8, leading=10,
                        colour=GOLD_DK, bold=True, space_after=4)),
             Paragraph(pattern_text, _sty('pattxt', size=10, leading=15, colour=DARK, space_after=0))],
            bg=GOLD_LT, border_color=GOLD_BD, pad=8,
        )
        story.append(box)
        story.append(HR())

    # How you're developing — per-dimension sparkline/trend history
    portfolio = data.get('portfolio_data') or {}
    if portfolio.get('has_trends') and portfolio.get('dimensions'):
        plotted = portfolio.get('plotted_count', '')
        story.append(Paragraph(
            f"How you're developing  "
            f'<font size="8" color="#555555">(last {plotted} photographs evaluated)</font>',
            S['sec_label']
        ))
        for dim in portfolio['dimensions']:
            if dim.get('points'):
                story.append(_dim_history_row(dim, avail))
                story.append(Spacer(1, 4))
        story.append(HR())

    # ────────────────────────────────
    # PAGE 3 — Edit Guide + Location
    # ────────────────────────────────
    story.append(PageBreak())

    _logo_buf3 = io.BytesIO(_logo_bytes.getvalue()) if _logo_bytes else None
    _logo3 = None
    if _logo_buf3:
        try:
            _logo3 = RLImage(_logo_buf3, width=7*mm, height=7*mm, kind='proportional')
        except Exception:
            pass
    if _logo3:
        hdr3 = Table(
            [[_logo3,
              Paragraph('SHUTTER LEAGUE', S['page_title']),
              Paragraph(f'EDIT GUIDE  ·  {asset}', S['page_sub'])]],
            colWidths=[9*mm, avail * 0.45, avail - 9*mm - avail * 0.45],
        )
    else:
        hdr3 = Table(
            [[Paragraph('SHUTTER LEAGUE', S['page_title']),
              Paragraph(f'EDIT GUIDE  ·  {asset}', S['page_sub'])]],
            colWidths=[avail * 0.5, avail * 0.5],
        )
    hdr3.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(hdr3)
    story.append(HR(space_before=2, space_after=8))

    edit_base     = _clean(data.get('edit_base', ''))
    edit_creative = _clean(data.get('edit_creative', ''))

    if edit_base or edit_creative:
        story.append(Paragraph('Edit guide', S['sec_label']))

        # Two-column edit if both present, single column if only one
        if edit_base and edit_creative:
            hw = (avail - 8*mm) / 2
            lft_edit = [Paragraph('Standard edit  ·  Balanced. Light editing.', S['edit_lbl'])] + \
                       _paras(edit_base, S['edit'])
            rgt_edit = [Paragraph('Creative edit  ·  Artistic. Heavy editing.', _sty('ce', size=9, leading=11, colour=GREEN_DK, bold=True, space_after=3, space_before=8))] + \
                       _paras(edit_creative, S['edit'])
            edit_tbl = Table([[lft_edit, rgt_edit]], colWidths=[hw, hw])
            edit_tbl.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('TOPPADDING', (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ]))
            story.append(edit_tbl)
        elif edit_base:
            story.append(Paragraph('Standard edit  ·  Balanced. Light editing.', S['edit_lbl']))
            for p in _paras(edit_base, S['edit']):
                story.append(p)
        else:
            story.append(Paragraph('Creative edit  ·  Artistic. Heavy editing.', S['edit_lbl']))
            for p in _paras(edit_creative, S['edit']):
                story.append(p)
        story.append(HR())

    # Where to shoot next
    loc1 = _clean(data.get('mentor_location_1', ''))
    loc2 = _clean(data.get('mentor_location_2', ''))

    if loc1:
        story.append(Paragraph('Where to shoot next', S['loc_lbl']))
        if loc2:
            hw = (avail - 8*mm) / 2
            l1_block = [Paragraph('Now open', _sty('lnow', size=8, leading=10, colour=GREEN_LBL, bold=True, space_after=3))] + \
                       _paras(loc1, S['loc'])
            l2_block = [Paragraph('Coming up', _sty('lcup', size=8, leading=10, colour=GREEN_LBL, bold=True, space_after=3))] + \
                       _paras(loc2, S['loc'])
            loc_tbl = Table([[l1_block, l2_block]], colWidths=[hw, hw])
            loc_tbl.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('TOPPADDING', (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ]))
            story.append(loc_tbl)
        else:
            for p in _paras(loc1, S['loc']):
                story.append(p)
        story.append(HR())

    # HCB quote
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        '\u201cTo photograph is to hold one\u2019s breath when all faculties '
        'converge to capture fleeting reality.\u201d',
        S['quote']
    ))
    story.append(Paragraph('\u2014 Henri Cartier-Bresson', S['quote_attr']))
    story.append(Spacer(1, 12))
    story.append(HR(space_before=0, space_after=4))
    story.append(Paragraph(
        'BETTER LIGHT.  MORE CLARITY.  STRONGER STORY.  YOU, ONE FRAME AT A TIME.',
        S['foot']
    ))
    story.append(Paragraph(
        f'SL  ·  {score_str}  ·  {tier_str.upper()}  ·  shutter.league',
        S['foot']
    ))

    def _on_first_page(canvas, doc_):
        _draw_page1_frame(canvas, doc_, page_w=W, page_h=H, margin=M)

    doc.build(story, onFirstPage=_on_first_page)
    return buf.getvalue()
