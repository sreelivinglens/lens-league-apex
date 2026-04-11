"""
EXIF Metadata Extractor + Authenticity Checker
Extracts camera data from uploaded images.
Returns verification status and metadata dict.
"""

from PIL import Image, ExifTags
import os

# EXIF tag IDs we care about
TAG_MAKE        = 271   # Camera Make (Canon, Nikon etc)
TAG_MODEL       = 272   # Camera Model
TAG_DATETIME    = 306   # Date/Time
TAG_DATETIME_O  = 36867 # DateTimeOriginal
TAG_SOFTWARE    = 305   # Software (Photoshop, Instagram etc)
TAG_GPS_INFO    = 34853 # GPS data present
TAG_FOCAL       = 37386 # Focal length
TAG_APERTURE    = 33437 # F-number
TAG_ISO         = 34855 # ISO
TAG_SHUTTER     = 33434 # Exposure time
TAG_LENS_MODEL  = 42036 # Lens model


def extract_exif(image_path):
    """
    Extract EXIF data from image.
    Returns (status, exif_dict, warning_message)

    status: 'verified' | 'unverified' | 'suspicious'
    """
    exif_data = {}
    warnings  = []

    try:
        img  = Image.open(image_path)
        raw  = img._getexif()

        if not raw:
            return 'unverified', {}, 'No camera EXIF data found — image may be a screenshot or download.'

        # Map tag IDs to names
        for tag_id, value in raw.items():
            tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
            if isinstance(value, bytes):
                try:    value = value.decode('utf-8', errors='ignore').strip()
                except: value = str(value)
            exif_data[tag_id] = {'tag': tag_name, 'value': value}

    except Exception as e:
        return 'unverified', {}, f'Could not read image metadata: {str(e)}'

    # ── Extract key fields ────────────────────────────────────────────────────
    result = {}

    make  = exif_data.get(TAG_MAKE,  {}).get('value', '')
    model = exif_data.get(TAG_MODEL, {}).get('value', '')
    if make or model:
        result['camera'] = f"{make} {model}".strip()

    dt = (exif_data.get(TAG_DATETIME_O, {}).get('value') or
          exif_data.get(TAG_DATETIME,   {}).get('value', ''))
    if dt:
        result['date_taken'] = str(dt)

    software = exif_data.get(TAG_SOFTWARE, {}).get('value', '')
    if software:
        result['software'] = str(software)

    focal = exif_data.get(TAG_FOCAL, {}).get('value', '')
    if focal:
        try:
            result['focal_length'] = f"{float(focal[0])/float(focal[1]):.0f}mm" if isinstance(focal, tuple) else f"{focal}mm"
        except: pass

    aperture = exif_data.get(TAG_APERTURE, {}).get('value', '')
    if aperture:
        try:
            result['aperture'] = f"f/{float(aperture[0])/float(aperture[1]):.1f}" if isinstance(aperture, tuple) else f"f/{aperture}"
        except: pass

    iso = exif_data.get(TAG_ISO, {}).get('value', '')
    if iso:
        result['iso'] = f"ISO {iso}"

    shutter = exif_data.get(TAG_SHUTTER, {}).get('value', '')
    if shutter:
        try:
            s = float(shutter[0])/float(shutter[1]) if isinstance(shutter, tuple) else float(shutter)
            result['shutter'] = f"1/{int(1/s)}s" if s < 1 else f"{s}s"
        except: pass

    lens = exif_data.get(TAG_LENS_MODEL, {}).get('value', '')
    if lens:
        result['lens'] = str(lens)

    gps = exif_data.get(TAG_GPS_INFO, {})
    result['has_gps'] = bool(gps)

    # ── Determine verification status ─────────────────────────────────────────
    has_camera  = bool(result.get('camera'))
    has_date    = bool(result.get('date_taken'))
    has_settings = bool(result.get('focal_length') or result.get('aperture') or result.get('iso'))

    # Suspicious software signatures
    suspicious_software = ['instagram', 'facebook', 'whatsapp', 'twitter',
                           'snapseed', 'vsco', 'screen', 'grab', 'screenshot']
    sw_lower = software.lower() if software else ''
    is_suspicious_software = any(s in sw_lower for s in suspicious_software)

    if is_suspicious_software:
        status  = 'suspicious'
        warnings.append(f'Image processed by {software} — may not be an original camera file.')
    elif has_camera and has_date and has_settings:
        status = 'verified'
    elif has_camera or has_date:
        status = 'unverified'
        warnings.append('Partial camera data found — some metadata missing.')
    else:
        status = 'unverified'
        warnings.append('No camera EXIF data — image may be a web download or screenshot.')

    warning_msg = ' '.join(warnings)
    return status, result, warning_msg
