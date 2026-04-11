"""
Image ingestion pipeline
- Accepts RAW (CR2, CR3, NEF, ARW, DNG) and JPEG/PNG
- Strips RAW to compressed JPG thumbnail
- Rejects rating card images (tall portrait ratio ~1:2.5+)
"""

import os
import uuid
from PIL import Image
from datetime import date

RAW_EXTENSIONS = {'.cr2', '.cr3', '.nef', '.arw', '.dng', '.raf', '.rw2'}
IMG_EXTENSIONS  = {'.jpg', '.jpeg', '.png'}

THUMB_W = 2000   # match CARD_W
JPEG_Q  = 88


def allowed_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in RAW_EXTENSIONS | IMG_EXTENSIONS


def ingest_image(file_path, upload_folder):
    """
    Takes a file path, converts to compressed JPG thumbnail.
    Returns (thumb_path, width, height, format_str)
    Raises ValueError if the image looks like a rating card.
    """
    ext = os.path.splitext(file_path)[1].lower()
    uid = str(uuid.uuid4())

    thumb_name = f"{uid}_thumb.jpg"
    thumb_path = os.path.join(upload_folder, 'thumbs', thumb_name)
    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)

    if ext in RAW_EXTENSIONS:
        try:
            import rawpy
            with rawpy.imread(file_path) as raw:
                rgb = raw.postprocess(
                    use_camera_wb=True,
                    half_size=False,
                    no_auto_bright=False,
                    output_bps=8
                )
            img = Image.fromarray(rgb)
            fmt = 'RAW'
        except Exception as e:
            raise ValueError(f"RAW processing failed: {e}")
    else:
        img = Image.open(file_path).convert('RGB')
        fmt = img.format or 'JPEG'

    # ── Guard: reject rating card images ─────────────────────────────────────
    # Rating cards are tall portrait images with aspect ratio > 1.8 (h/w)
    w, h = img.size
    aspect = h / w if w > 0 else 0
    if aspect > 1.8:
        raise ValueError(
            "This looks like a rating card image, not a source photo. "
            "Please upload your original photograph (landscape or square orientation)."
        )

    # Resize preserving aspect
    if w > THUMB_W:
        ratio = THUMB_W / w
        new_h = int(h * ratio)
        img   = img.resize((THUMB_W, new_h), Image.LANCZOS)
        w, h  = THUMB_W, new_h

    img.save(thumb_path, 'JPEG', quality=JPEG_Q, optimize=True)
    return thumb_path, w, h, fmt


def build_rating_card(thumb_path, data, upload_folder):
    """
    Composites the full rating card JPG from thumbnail + scoring data.
    Returns path to the card JPG.
    """
    from engine.compositor import build_card

    uid       = str(uuid.uuid4())
    today_str = date.today().strftime("%Y%m%d")
    card_name = f"{today_str}_{uid}_card.jpg"
    card_path = os.path.join(upload_folder, 'cards', card_name)
    os.makedirs(os.path.dirname(card_path), exist_ok=True)

    build_card(thumb_path, data, card_path)
    return card_path
