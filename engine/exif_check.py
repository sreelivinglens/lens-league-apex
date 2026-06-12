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
TAG_FOCAL_35MM  = 41989 # FocalLengthIn35mmFormat — critical for device tier detection
TAG_APERTURE    = 33437 # F-number
TAG_ISO         = 34855 # ISO
TAG_SHUTTER     = 33434 # Exposure time
TAG_LENS_MODEL  = 42036 # Lens model
TAG_EXP_PROG    = 34850 # ExposureProgram (Manual=1, Auto=2 etc.)
TAG_WB          = 41987 # WhiteBalance (0=Auto, 1=Manual)
TAG_FLASH       = 37385 # Flash fired/not fired
TAG_METERING    = 37383 # MeteringMode


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

    # ── GPS coordinates (decimal degrees) — Item B, location-change detection ──
    # GPSInfo value is itself a small dict of GPS tag id -> value (DMS rationals).
    if gps:
        try:
            gps_ifd = gps.get('value', {})
            if isinstance(gps_ifd, dict):
                def _dms_to_decimal(dms, ref):
                    """Convert ((d_num,d_den),(m_num,m_den),(s_num,s_den)) + ref to decimal degrees."""
                    def _r(v):
                        return float(v[0]) / float(v[1]) if isinstance(v, tuple) else float(v)
                    deg, minute, sec = (_r(dms[0]), _r(dms[1]), _r(dms[2]))
                    decimal = deg + (minute / 60.0) + (sec / 3600.0)
                    if ref in ('S', 'W'):
                        decimal = -decimal
                    return decimal

                lat_dms = gps_ifd.get(2)   # GPSLatitude
                lat_ref = gps_ifd.get(1)   # GPSLatitudeRef
                lon_dms = gps_ifd.get(4)   # GPSLongitude
                lon_ref = gps_ifd.get(3)   # GPSLongitudeRef

                if lat_dms and lon_dms and lat_ref and lon_ref:
                    if isinstance(lat_ref, bytes):
                        lat_ref = lat_ref.decode('ascii', errors='ignore')
                    if isinstance(lon_ref, bytes):
                        lon_ref = lon_ref.decode('ascii', errors='ignore')
                    result['gps_lat'] = round(_dms_to_decimal(lat_dms, lat_ref), 6)
                    result['gps_lon'] = round(_dms_to_decimal(lon_dms, lon_ref), 6)
        except Exception:
            # Malformed/partial GPS IFD — has_gps stays True but no coordinates.
            pass

    # ── Extended fields for device-aware DDI ──────────────────────────────────
    # Raw make/model stored separately for device tier detection
    result['make']  = str(make).strip()  if make  else ''
    result['model'] = str(model).strip() if model else ''

    # FocalLengthIn35mmFormat — key for telephoto detection on mobile devices
    fl35 = exif_data.get(TAG_FOCAL_35MM, {}).get('value', '')
    if fl35:
        try:
            fl35_val = float(fl35[0]) / float(fl35[1]) if isinstance(fl35, tuple) else float(fl35)
            result['focal_length_35mm'] = round(fl35_val, 1)
        except Exception:
            pass

    # Raw numeric values for DDI context (used by build_exif_context)
    aperture_raw = exif_data.get(TAG_APERTURE, {}).get('value', '')
    if aperture_raw:
        try:
            result['aperture_raw'] = round(
                float(aperture_raw[0]) / float(aperture_raw[1])
                if isinstance(aperture_raw, tuple) else float(aperture_raw), 1
            )
        except Exception:
            pass

    iso_raw = exif_data.get(TAG_ISO, {}).get('value', '')
    if iso_raw:
        try:
            result['iso_raw'] = int(iso_raw)
        except Exception:
            pass

    shutter_raw = exif_data.get(TAG_SHUTTER, {}).get('value', '')
    if shutter_raw:
        try:
            s = (float(shutter_raw[0]) / float(shutter_raw[1])
                 if isinstance(shutter_raw, tuple) else float(shutter_raw))
            result['shutter_raw'] = round(s, 6)  # seconds as float
        except Exception:
            pass

    focal_raw = exif_data.get(TAG_FOCAL, {}).get('value', '')
    if focal_raw:
        try:
            result['focal_length_raw'] = round(
                float(focal_raw[0]) / float(focal_raw[1])
                if isinstance(focal_raw, tuple) else float(focal_raw), 1
            )
        except Exception:
            pass

    # Exposure program, white balance, flash, metering
    exp_prog = exif_data.get(TAG_EXP_PROG, {}).get('value', '')
    if exp_prog is not None and exp_prog != '':
        result['exposure_program'] = int(exp_prog) if str(exp_prog).isdigit() else str(exp_prog)

    wb = exif_data.get(TAG_WB, {}).get('value', '')
    if wb is not None and wb != '':
        result['white_balance'] = int(wb) if str(wb).isdigit() else str(wb)

    flash = exif_data.get(TAG_FLASH, {}).get('value', '')
    if flash is not None and flash != '':
        try:
            result['flash_fired'] = bool(int(flash) & 0x1)  # bit 0 = flash fired
        except Exception:
            pass

    metering = exif_data.get(TAG_METERING, {}).get('value', '')
    if metering is not None and metering != '':
        result['metering_mode'] = int(metering) if str(metering).isdigit() else str(metering)

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
