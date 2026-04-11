"""
Image ingestion pipeline
- Accepts JPEG and PNG for now (RAW support can be added later)
- Rejects rating card images
"""

import os
import uuid
from PIL import Image
from datetime import date

RAW_EXTENSIONS = {'.cr2', '.cr3', '.nef', '.arw', '.dng', '.raf', '.rw2'}
IMG_EXTENSIONS  = {'.jpg', '.jpeg', '.png'}

THUMB_W = 960
JPEG_Q  = 88


def allowed_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in RAW_EXTENSIONS | IMG_EXTENSIONS


def ingest_image(file_path, upload_folder):
    ext = os.path.splitext(file_path)[1].lower()
    uid = str(uuid.uuid4())

    thumb_name = f"{uid}_thumb.jpg"
    thumb_path = os.path.join(upload_folder, 'thumbs', thumb_name)
    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)

    if ext in RAW_EXTENSIONS:
        # RAW support — try rawpy if available, otherwise reject
        try:
            import rawpy
            with rawpy.imread(file_path) as raw:
                rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
            img = Image.fromarray(rgb)
            fmt = 'RAW'
        except ImportError:
            raise ValueError(
                "RAW files are not supported on this server. "
                "Please convert to JPEG before uploading."
            )
        except Exception as e:
            raise ValueError(f"RAW processing failed: {e}")
    else:
        img = Image.open(file_path).convert('RGB')
        fmt = img.format or 'JPEG'

    # Reject rating card images (tall aspect ratio)
    w, h = img.size
    if (h / w) > 1.8:
        raise ValueError(
            "This looks like a rating card, not a source photo. "
            "Please upload your original photograph."
        )

    # Resize to thumb width
    if w > THUMB_W:
        ratio = THUMB_W / w
        img   = img.resize((THUMB_W, int(h * ratio)), Image.LANCZOS)
        w, h  = img.size

    img.save(thumb_path, 'JPEG', quality=JPEG_Q, optimize=True)
    return thumb_path, w, h, fmt


def build_rating_card(thumb_path, data, upload_folder):
    from engine.compositor import build_card
    uid       = str(uuid.uuid4())
    today_str = date.today().strftime("%Y%m%d")
    card_name = f"{today_str}_{uid}_card.jpg"
    card_path = os.path.join(upload_folder, 'cards', card_name)
    os.makedirs(os.path.dirname(card_path), exist_ok=True)
    build_card(thumb_path, data, card_path)
    return card_path
