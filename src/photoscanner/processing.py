# processing.py - find the sheet in a photo, straighten it, clean it up
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Image processing, independent from the user interface.

Steps, like a phone scanner app:
  1. find the 4 corners of the sheet of paper;
  2. straighten it (perspective correction);
  3. apply a filter: remove shadows, whiten the paper, darken the writing.

Corners are stored as fractions of the image size (0..1), so the same corners
work for the small preview and for the full resolution photo used on export.
"""
import cv2
import numpy as np

PREVIEW_SIZE = 1600        # longest side, in pixels, of the on-screen preview
EXPORT_MAX_SIZE = 3508     # A4 at 300 dpi: larger pages only make heavier files
WHOLE_IMAGE = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64)

FILTERS = ("enhanced", "grayscale", "bw", "original")


def shrink(img, max_side):
    h, w = img.shape[:2]
    s = max_side / max(h, w)
    if s >= 1:
        return img
    return cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)


# ------------------------------------------------------------------ corners
def order_corners(points):
    """Corners in order: top-left, top-right, bottom-right, bottom-left."""
    p = np.asarray(points, dtype=np.float64).reshape(4, 2)
    c = p.mean(axis=0)
    p = p[np.argsort(np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0]))]
    return np.roll(p, -int(np.argmin(p.sum(axis=1))), axis=0)


def _quads(binary, image_area):
    """Large 4-sided shapes (at least 15% of the photo) in a black and white image."""
    h, w = binary.shape[:2]
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:8]
    found = []
    for c in contours:
        hull = cv2.convexHull(c)
        a = cv2.contourArea(hull)
        if a < 0.15 * image_area or a > 0.985 * image_area:
            continue
        perimeter = cv2.arcLength(hull, True)
        for eps in (0.01, 0.02, 0.03, 0.05, 0.08):
            approx = cv2.approxPolyDP(hull, eps * perimeter, True)
            if len(approx) < 4:
                break
            if len(approx) == 4:
                if cv2.isContourConvex(approx):
                    qa = cv2.contourArea(approx)
                    fit = min(a, qa) / max(a, qa)
                    q = approx.reshape(4, 2)
                    # corners lying on the photo border are usually a shadow, not the sheet
                    on_border = int(np.sum((q[:, 0] <= 2) | (q[:, 0] >= w - 3) | (q[:, 1] <= 2) | (q[:, 1] >= h - 3)))
                    penalty = (1.0, 0.6, 0.2, 0.1, 0.05)[on_border]
                    found.append((qa * fit ** 2 * penalty, q))
                break
    return found


def _local_contrast(gray):
    return cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)


def _refine(rgb, quad):
    """Move each side onto the real edge of the sheet, searching the larger image.

    Each side is split in short pieces; for each piece we look, moving a little
    perpendicularly, for the line where brightness changes the most (the edge of
    the sheet is much sharper than wood grain or paper texture). Then a line is
    fitted through those points and neighbouring lines are intersected.
    """
    h, w = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    # "closing" wipes out writing and thin printed lines (tables, stamps) near the edge,
    # which would otherwise be sharper than the edge of the sheet itself
    k = max(3, int(max(h, w) / 100) | 1)
    gray = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    gray = cv2.GaussianBlur(gray, (5, 5), 0).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    # the rough outline is within ~1% of the right place: search close to it, and prefer
    # nearby edges (a patterned tablecloth has sharp edges parallel to the sheet too)
    band = max(6, int(0.012 * max(h, w)))
    offsets = np.arange(-band, band + 1, dtype=np.float64)
    closeness = np.exp(-0.5 * (offsets / (0.6 * band)) ** 2)
    pieces, samples = 16, 10
    lines = []
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        length = np.linalg.norm(b - a)
        u = (b - a) / length
        n = np.array([-u[1], u[0]])
        points, strengths = [], []
        for k in range(pieces):
            t = (0.08 + 0.84 * (k + np.arange(samples) / samples) / pieces) * length
            centres = a + t[:, None] * u
            pts = centres[None, :, :] + offsets[:, None, None] * n
            x = np.clip(np.rint(pts[..., 0]).astype(int), 0, w - 1)
            y = np.clip(np.rint(pts[..., 1]).astype(int), 0, h - 1)
            response = np.abs(gx[y, x] * n[0] + gy[y, x] * n[1]).mean(axis=1)
            weighted = response * closeness
            # n points inside the sheet: among the strong edges take the innermost one
            # (inside the sheet, after the closing, there are no edges left)
            peaks = np.flatnonzero((weighted >= 0.25 * weighted.max())
                                   & (weighted >= np.roll(weighted, 1)) & (weighted >= np.roll(weighted, -1)))
            best = int(peaks.max()) if len(peaks) else int(np.argmax(weighted))
            points.append(a + t.mean() * u + offsets[best] * n)
            strengths.append(response[best] / (np.median(response) + 1e-3))
        points, strengths = np.array(points), np.array(strengths)
        good = points[strengths > 2.0]
        if len(good) < 5:
            lines.append(None)
            continue
        vx, vy, x0, y0 = cv2.fitLine(good.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((np.array([x0, y0], dtype=np.float64), np.array([vx, vy], dtype=np.float64)))
    refined = quad.copy()
    for i in range(4):
        l1, l2 = lines[i - 1], lines[i]          # the two sides meeting at corner i
        if l1 is None or l2 is None:
            continue
        (p1, d1), (p2, d2) = l1, l2
        m = np.array([d1, -d2]).T
        if abs(np.linalg.det(m)) < 1e-3:
            continue
        t = np.linalg.solve(m, p2 - p1)
        corner = p1 + t[0] * d1
        if np.linalg.norm(corner - quad[i]) < 5 * band:
            refined[i] = np.clip(corner, [0, 0], [w - 1, h - 1])
    return refined


def _edge_support(quad, gx, gy):
    """How sharp the weakest side is: mean brightness change across the side."""
    h, w = gx.shape
    q = order_corners(quad)
    t = np.linspace(0.1, 0.9, 40)[None, :, None]
    shifts = np.arange(-2, 3)[:, None, None]          # the approximated side can be 1-2 px off
    weakest = np.inf
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        d = b - a
        n = np.array([-d[1], d[0]]) / (np.linalg.norm(d) + 1e-9)
        pts = a + t * d + shifts * n                    # shifts x samples x 2
        x = np.clip(np.rint(pts[..., 0]).astype(int), 0, w - 1)
        y = np.clip(np.rint(pts[..., 1]).astype(int), 0, h - 1)
        side = np.abs(gx[y, x] * n[0] + gy[y, x] * n[1]).mean(axis=1).max()
        weakest = min(weakest, side)
    return weakest


def detect_corners(rgb):
    """Return (corners as fractions 0..1, found?). If no sheet is found: the whole photo."""
    small = shrink(rgb, 700)
    h, w = small.shape[:2]
    area = h * w
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    saturation = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)[:, :, 1]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    candidates = []
    # brightness, brightness with more contrast (light sheet on a light table)
    # and saturation (white sheet on a coloured table)
    for channel in (gray, _local_contrast(gray), saturation):
        # "closing" wipes out the writing, only the edges of the sheet remain
        smooth = cv2.GaussianBlur(cv2.morphologyEx(channel, cv2.MORPH_CLOSE, kernel, iterations=2), (7, 7), 0)
        for low, high in ((10, 30), (20, 60), (40, 120), (75, 200)):
            edges = cv2.dilate(cv2.Canny(smooth, low, high), np.ones((3, 3), np.uint8), iterations=2)
            candidates += _quads(edges, area)
        _, thr = cv2.threshold(smooth, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        candidates += _quads(thr, area)
        candidates += _quads(255 - thr, area)
    if not candidates:
        return WHOLE_IMAGE.copy(), False
    # every side of the sheet must follow a sharp edge: the weakest side decides
    blurred = cv2.GaussianBlur(gray, (3, 3), 0).astype(np.float32)
    gx = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
    unique = {}
    for score, q in candidates:                      # the same shape is found many times
        key = tuple(np.round(order_corners(q) / 3).astype(int).ravel())
        if key not in unique or unique[key][0] < score:
            unique[key] = (score, q)
    _, best = max(((score * _edge_support(q, gx, gy), q) for score, q in unique.values()), key=lambda c: c[0])
    H, W = rgb.shape[:2]
    quad = _refine(rgb, order_corners(best) * np.array([W / w, H / h]))
    return quad / np.array([W, H], dtype=np.float64), True


# ------------------------------------------------------------ straightening
def straighten(rgb, corners):
    h, w = rgb.shape[:2]
    p = order_corners(np.asarray(corners) * np.array([w, h]))
    tl, tr, br, bl = p
    width = max(16, int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))))
    height = max(16, int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))))
    dest = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(p.astype(np.float32), dest)
    out = cv2.warpPerspective(rgb, m, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    # trim 0.4%: avoids a dark line of table right on the edge of the sheet
    if not np.allclose(corners, WHOLE_IMAGE):
        r = max(1, round(0.004 * max(width, height)))
        out = out[r:height - r, r:width - r]
    return out


# ------------------------------------------------------------------ filters
def _background(channel):
    """Estimate of the paper colour at every point (to remove shadows and uneven light)."""
    h, w = channel.shape
    s = 400 / max(h, w)
    p = cv2.resize(channel, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    p = cv2.dilate(p, np.ones((5, 5), np.uint8))   # dark writing disappears
    p = cv2.medianBlur(p, 21)
    p = cv2.GaussianBlur(p, (0, 0), 3)
    return cv2.resize(p, (w, h), interpolation=cv2.INTER_LINEAR)


def _flatten(rgb):
    """Divide every colour by the paper colour: paper = 1, writing darker."""
    channels = [c.astype(np.float32) / np.maximum(_background(c).astype(np.float32), 1) for c in cv2.split(rgb)]
    return np.clip(cv2.merge(channels), 0, 1)


def _levels(x):
    """Clean white paper and bolder writing."""
    return np.clip(x / 0.9, 0, 1) ** 1.6


def apply_filter(rgb, name):
    """Return RGB for "enhanced"/"original", a single channel image for "grayscale"/"bw"."""
    if name == "original":
        return rgb
    flat = _flatten(rgb)
    if name == "enhanced":
        out = (_levels(flat) * 255).astype(np.uint8)
        hsv = cv2.cvtColor(out, cv2.COLOR_RGB2HSV)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1].astype(np.float32) * 1.3, 0, 255).astype(np.uint8)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    gray = cv2.cvtColor((flat * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    if name == "grayscale":
        return (_levels(gray.astype(np.float32) / 255) * 255).astype(np.uint8)
    gray = cv2.medianBlur(gray, 3)
    threshold, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    threshold = float(np.clip(threshold, 140, 215))
    return np.where(gray > threshold, 255, 0).astype(np.uint8)


def process(rgb, corners, filter_name, rotation):
    """rotation = clockwise quarter turns (0..3)."""
    out = apply_filter(straighten(rgb, corners), filter_name)
    return np.ascontiguousarray(np.rot90(out, -(rotation % 4)))
