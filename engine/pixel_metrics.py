# SL-VERSION: pixel_metrics-1.0 (Session 235, 2026-10-03 -- NEW: measuring layer, REPORT ONLY. Reads the pixels of a picture and reports plain facts (brightness, clipping, sharpness, edges, horizon tilt, thirds, colour, entropy, negative space). It does NOT change any score. Same file in = same numbers out. Thresholds are the founder's to set later.)
"""
Shutter League - pixel measuring layer (report only).

Design rules (founder decisions, S235):
  * Measured facts are REPORTED. They do not change any score in this version.
  * Silhouette and high-key pictures are expected to clip; the tonal type is
    reported so a later rule can judge against it. Never used for blur.
  * Deterministic: the picture is first reduced to a fixed analysis size
    (longest side 1024 px, LANCZOS), converted to 8-bit RGB, and every number
    is computed with plain numpy arithmetic. No randomness, no model calls.
  * Cost: 0 rupees per image (runs on our server).

Usage:
    from pixel_metrics import measure_file, METRICS_VERSION
    facts = measure_file('/path/to/picture.jpg')   # dict of plain numbers
"""
import hashlib
import math

import numpy as np
from PIL import Image

METRICS_VERSION = "pixel_metrics-1.0"
ANALYSIS_LONG_SIDE = 1024

# PROVISIONAL tonal-type cut-offs. They only LABEL the picture in the report.
# They are not applied to any score. The founder sets real ones after seeing numbers.
TONAL_PROVISIONAL = {
    "silhouette_shadow_clip_pct": 40.0,
    "high_key_highlight_clip_pct": 25.0,
    "high_key_mean_luma": 170.0,
    "low_key_mean_luma": 70.0,
}


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_analysis_rgb(path):
    im = Image.open(path)
    im.load()
    if im.mode != "RGB":
        im = im.convert("RGB")
    w, h = im.size
    long_side = max(w, h)
    if long_side != ANALYSIS_LONG_SIDE:
        scale = ANALYSIS_LONG_SIDE / float(long_side)
        nw = max(8, int(round(w * scale)))
        nh = max(8, int(round(h * scale)))
        im = im.resize((nw, nh), Image.LANCZOS)
    return np.asarray(im, dtype=np.uint8), (w, h)


def _luma(rgb):
    r = rgb[..., 0].astype(np.float64)
    g = rgb[..., 1].astype(np.float64)
    b = rgb[..., 2].astype(np.float64)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _laplacian(gray):
    g = gray
    out = (-4.0 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    return out


def _sobel(gray):
    g = gray
    gx = ((g[:-2, 2:] + 2 * g[1:-1, 2:] + g[2:, 2:]) - (g[:-2, :-2] + 2 * g[1:-1, :-2] + g[2:, :-2]))
    gy = ((g[2:, :-2] + 2 * g[2:, 1:-1] + g[2:, 2:]) - (g[:-2, :-2] + 2 * g[:-2, 1:-1] + g[:-2, 2:]))
    return gx, gy


def _entropy(gray):
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    p = hist.astype(np.float64)
    s = p.sum()
    if s <= 0:
        return 0.0
    p = p[p > 0] / s
    return float(-(p * np.log2(p)).sum())


def _rgb_to_hsv_arrays(rgb):
    x = rgb.astype(np.float64) / 255.0
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    d = mx - mn
    s = np.where(mx > 0, d / np.where(mx == 0, 1, mx), 0.0)
    h = np.zeros_like(mx)
    nz = d > 1e-12
    rc = np.where(nz, (mx - r) / np.where(nz, d, 1), 0)
    gc = np.where(nz, (mx - g) / np.where(nz, d, 1), 0)
    bc = np.where(nz, (mx - b) / np.where(nz, d, 1), 0)
    h = np.where(mx == r, bc - gc, np.where(mx == g, 2.0 + rc - bc, 4.0 + gc - rc))
    h = (h / 6.0) % 1.0
    h = np.where(nz, h, 0.0)
    return h * 360.0, s, mx


def _tonal_type(mean_luma, highlight_pct, shadow_pct):
    t = TONAL_PROVISIONAL
    if shadow_pct >= t["silhouette_shadow_clip_pct"]:
        return "silhouette-or-very-dark"
    if highlight_pct >= t["high_key_highlight_clip_pct"] or mean_luma >= t["high_key_mean_luma"]:
        return "high-key"
    if mean_luma <= t["low_key_mean_luma"]:
        return "low-key"
    return "normal"


def measure_array(rgb, original_size=None):
    """rgb: uint8 array (H, W, 3) already at analysis size. Returns dict of plain numbers."""
    h, w = rgb.shape[:2]
    gray = _luma(rgb)
    n = float(gray.size)

    mean_luma = float(gray.mean())
    std_luma = float(gray.std())
    highlight_pct = float((gray >= 250.0).sum()) / n * 100.0
    shadow_pct = float((gray <= 5.0).sum()) / n * 100.0
    dark_share = float((gray < 64).sum()) / n * 100.0
    mid_share = float(((gray >= 64) & (gray < 192)).sum()) / n * 100.0
    bright_share = float((gray >= 192).sum()) / n * 100.0
    p1, p50, p99 = [float(v) for v in np.percentile(gray, [1, 50, 99])]

    # Sharpness: variance of Laplacian, overall + best and worst tile (3x3 grid)
    lap = _laplacian(gray)
    sharp_all = float(lap.var())
    th, tw = lap.shape[0] // 3, lap.shape[1] // 3
    tiles = []
    for i in range(3):
        for j in range(3):
            t = lap[i * th:(i + 1) * th, j * tw:(j + 1) * tw]
            tiles.append(float(t.var()))
    sharp_best, sharp_worst = max(tiles), min(tiles)

    # Edges
    gx, gy = _sobel(gray)
    mag = np.sqrt(gx * gx + gy * gy)
    edge_strength = float(mag.mean())
    thr = 100.0
    edge_mask = mag > thr
    edge_density = float(edge_mask.sum()) / float(mag.size) * 100.0

    # Dominant edge direction (weighted histogram of gradient angle, 0..180 deg)
    ang = (np.degrees(np.arctan2(gy, gx)) + 180.0) % 180.0
    wts = mag * edge_mask
    hist, edges_ = np.histogram(ang, bins=36, range=(0, 180), weights=wts)
    if hist.sum() > 0:
        k = int(np.argmax(hist))
        dom_angle = float((edges_[k] + edges_[k + 1]) / 2.0)
    else:
        dom_angle = None
    # Gradient angle is perpendicular to the edge line: a perfectly level horizon has gradient 90 deg.
    # Horizon tilt estimate = deviation of the strongest near-level edge direction from level.
    horizon_tilt = None
    dev = ang - 90.0
    near_mask = edge_mask & (np.abs(dev) <= 15.0)
    if near_mask.sum() > 0.01 * max(1, edge_mask.sum()) and near_mask.sum() >= 50:
        wn = mag[near_mask]
        horizon_tilt = float((dev[near_mask] * wn).sum() / wn.sum())

    # Thirds alignment of the edge-energy centroid
    energy = mag * mag
    tot = float(energy.sum())
    if tot > 0:
        ys, xs = np.mgrid[0:mag.shape[0], 0:mag.shape[1]]
        cy = float((energy * ys).sum() / tot) / mag.shape[0]
        cx = float((energy * xs).sum() / tot) / mag.shape[1]
        d_thirds = min(math.hypot(cx - a, cy - b) for a in (1 / 3., 2 / 3.) for b in (1 / 3., 2 / 3.))
    else:
        cx = cy = 0.5
        d_thirds = None

    # Colour
    hue, sat, val = _rgb_to_hsv_arrays(rgb)
    sat_mean = float(sat.mean())
    sat_std = float(sat.std())
    coloured = sat > 0.2
    col_share = float(coloured.sum()) / n * 100.0
    if coloured.sum() > 0:
        hh, _ = np.histogram(hue[coloured], bins=12, range=(0, 360))
        hue_spread = int((hh > 0.02 * coloured.sum()).sum())
        dom_hue = float((np.argmax(hh) + 0.5) * 30.0)
    else:
        hue_spread = 0
        dom_hue = None

    entropy = _entropy(np.clip(gray, 0, 255).astype(np.uint8))

    # Negative space: share of 16x16 blocks with very low local variation
    bh, bw = h // 16, w // 16
    quiet = 0
    total_blocks = 0
    for i in range(16):
        for j in range(16):
            blk = gray[i * bh:(i + 1) * bh, j * bw:(j + 1) * bw]
            total_blocks += 1
            if blk.std() < 6.0:
                quiet += 1
    neg_space = quiet / float(total_blocks) * 100.0

    # Balance: brightness-weighted centroid offset from centre (0 = centred)
    tot_l = float(gray.sum())
    if tot_l > 0:
        ys2, xs2 = np.mgrid[0:h, 0:w]
        bx = float((gray * xs2).sum() / tot_l) / w
        by = float((gray * ys2).sum() / tot_l) / h
        balance_offset = math.hypot(bx - 0.5, by - 0.5)
    else:
        balance_offset = 0.0

    r = lambda v, d=2: None if v is None else round(float(v), d)
    return {
        "metrics_version": METRICS_VERSION,
        "analysis_size": "%dx%d" % (w, h),
        "original_size": ("%dx%d" % original_size) if original_size else "",
        "luma_mean": r(mean_luma), "luma_std": r(std_luma),
        "luma_p1": r(p1), "luma_p50": r(p50), "luma_p99": r(p99),
        "highlight_clipped_pct": r(highlight_pct), "shadow_clipped_pct": r(shadow_pct),
        "dark_share_pct": r(dark_share), "mid_share_pct": r(mid_share), "bright_share_pct": r(bright_share),
        "tonal_type_provisional": _tonal_type(mean_luma, highlight_pct, shadow_pct),
        "sharpness_overall": r(sharp_all), "sharpness_best_tile": r(sharp_best), "sharpness_worst_tile": r(sharp_worst),
        "edge_strength": r(edge_strength), "edge_density_pct": r(edge_density),
        "dominant_edge_angle_deg": r(dom_angle, 1), "horizon_tilt_deg": r(horizon_tilt, 1),
        "edge_centroid_x": r(cx, 3), "edge_centroid_y": r(cy, 3), "distance_to_thirds_point": r(d_thirds, 3),
        "saturation_mean": r(sat_mean, 3), "saturation_std": r(sat_std, 3),
        "coloured_share_pct": r(col_share), "hue_buckets_used_of_12": hue_spread, "dominant_hue_deg": r(dom_hue, 1),
        "entropy_bits": r(entropy, 3), "negative_space_pct": r(neg_space), "balance_offset": r(balance_offset, 3),
    }


def measure_file(path):
    rgb, orig = _load_analysis_rgb(path)
    d = measure_array(rgb, orig)
    d["image_sha256"] = file_sha256(path)
    return d


FIELDS = [
    "image_sha256", "metrics_version", "original_size", "analysis_size", "tonal_type_provisional",
    "luma_mean", "luma_std", "luma_p1", "luma_p50", "luma_p99", "highlight_clipped_pct", "shadow_clipped_pct",
    "dark_share_pct", "mid_share_pct", "bright_share_pct", "sharpness_overall", "sharpness_best_tile",
    "sharpness_worst_tile", "edge_strength", "edge_density_pct", "dominant_edge_angle_deg", "horizon_tilt_deg",
    "edge_centroid_x", "edge_centroid_y", "distance_to_thirds_point", "saturation_mean", "saturation_std",
    "coloured_share_pct", "hue_buckets_used_of_12", "dominant_hue_deg", "entropy_bits", "negative_space_pct",
    "balance_offset",
]
