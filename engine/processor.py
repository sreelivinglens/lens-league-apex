"""
Image ingestion pipeline
- Accepts JPEG and PNG
- Rejects rating card images
- Generates perceptual hash (pHash) for duplicate detection
"""

import os
import uuid
import struct
import hashlib
from PIL import Image
from datetime import date

RAW_EXTENSIONS = {'.cr2', '.cr3', '.nef', '.arw', '.dng', '.raf', '.rw2'}
IMG_EXTENSIONS  = {'.jpg', '.jpeg', '.png'}

THUMB_W = 1500
JPEG_Q  = 88


def allowed_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in RAW_EXTENSIONS | IMG_EXTENSIONS


def compute_phash(img: Image.Image, hash_size: int = 16) -> str:
    """
    Compute a perceptual hash (pHash) of a PIL image.
    Returns a 64-character hex string.
    Uses DCT-based algorithm — robust to resize, minor colour shifts,
    slight crops, and JPEG re-compression.
    hash_size=16 gives a 256-bit hash with good collision resistance.
    """
    # Convert to greyscale and resize to hash_size x hash_size
    small = img.convert('L').resize((hash_size, hash_size), Image.LANCZOS)
    pixels = list(small.getdata())

    # Compute mean and build binary hash
    mean = sum(pixels) / len(pixels)
    bits = [1 if p > mean else 0 for p in pixels]

    # Pack bits into hex string
    hex_hash = ''
    for i in range(0, len(bits), 4):
        chunk = bits[i:i+4]
        hex_hash += format(sum(b << (3 - j) for j, b in enumerate(chunk)), 'x')
    return hex_hash


def hamming_distance(hash1: str, hash2: str) -> int:
    """
    Compute Hamming distance between two hex hash strings.
    Lower = more similar. 0 = identical. >20 = likely different images.
    """
    if len(hash1) != len(hash2):
        return 999
    # Convert hex to binary and count differing bits
    dist = 0
    for c1, c2 in zip(hash1, hash2):
        b1 = bin(int(c1, 16))[2:].zfill(4)
        b2 = bin(int(c2, 16))[2:].zfill(4)
        dist += sum(x != y for x, y in zip(b1, b2))
    return dist


def hash_similarity_pct(hash1: str, hash2: str) -> float:
    """Return similarity as a percentage (100 = identical)."""
    total_bits = len(hash1) * 4
    dist = hamming_distance(hash1, hash2)
    return round((1 - dist / total_bits) * 100, 1)


def ingest_image(file_path, upload_folder):
    ext = os.path.splitext(file_path)[1].lower()
    uid = str(uuid.uuid4())

    thumb_name = f"{uid}_thumb.jpg"
    thumb_path = os.path.join(upload_folder, 'thumbs', thumb_name)
    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)

    exif_bytes = b''
    if ext in RAW_EXTENSIONS:
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
        img = Image.open(file_path)
        exif_bytes = img.info.get('exif', b'')   # capture before convert strips it
        fmt = img.format or 'JPEG'
        img = img.convert('RGB')

    # Reject rating card images (tall aspect ratio)
    w, h = img.size
    if (h / w) > 1.8:
        raise ValueError(
            "This looks like a rating card, not a source photo. "
            "Please upload your original photograph."
        )

    # Minimum resolution enforcement
    short_side = min(w, h)
    if short_side < 1500:
        raise ValueError(
            f'Image resolution too low ({w}\u00d7{h}px). '
            'The shorter side must be at least 1500px. '
            'Please upload a higher resolution file.'
        )

    # Compute perceptual hash BEFORE resize (more accurate on full res)
    phash = compute_phash(img)

    # Resize to thumb width
    if w > THUMB_W:
        ratio = THUMB_W / w
        img   = img.resize((THUMB_W, int(h * ratio)), Image.LANCZOS)
        w, h  = img.size

    img.save(thumb_path, 'JPEG', quality=JPEG_Q, optimize=True, exif=exif_bytes)
    return thumb_path, w, h, fmt, phash


def build_rating_card(thumb_path, data, upload_folder):
    from engine.compositor import build_card
    uid       = str(uuid.uuid4())
    today_str = date.today().strftime("%Y%m%d")
    card_name = f"{today_str}_{uid}_card.jpg"
    card_path = os.path.join(upload_folder, 'cards', card_name)
    os.makedirs(os.path.dirname(card_path), exist_ok=True)
    build_card(thumb_path, data, card_path)
    return card_path
