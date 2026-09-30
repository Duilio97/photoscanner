# imageio.py - read photos, write JPEG/PNG
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading photos as RGB arrays, already turned the right way up.

Glycin (GNOME's sandboxed image loader) is used when available: it reads
JPEG, PNG, WebP, TIFF, HEIC/HEIF, AVIF, JPEG XL... and applies the EXIF
orientation. Fallbacks: OpenCV, then GdkPixbuf.
"""
import cv2
import numpy as np
import gi
from gi.repository import Gio

try:
    gi.require_version("Gly", "2")
    from gi.repository import Gly
except (ValueError, ImportError):
    Gly = None

try:
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
except (ValueError, ImportError):
    GdkPixbuf = None

MIME_TYPES = ("image/jpeg", "image/png", "image/heic", "image/heif", "image/webp", "image/tiff",
              "image/bmp", "image/avif", "image/jxl")


class LoadError(Exception):
    pass


def _rows(buf, width, height, stride, channels):
    a = np.frombuffer(buf, dtype=np.uint8)
    return a[:height * stride].reshape(height, stride)[:, :width * channels].reshape(height, width, channels)


def _load_glycin(path):
    loader = Gly.Loader.new(Gio.File.new_for_path(path))
    loader.set_accepted_memory_formats(Gly.MemoryFormatSelection.R8G8B8)
    frame = loader.load().next_frame()
    if frame.get_memory_format() != Gly.MemoryFormat.R8G8B8:
        raise LoadError("unexpected memory format")
    return _rows(frame.get_buf_bytes().get_data(), frame.get_width(), frame.get_height(), frame.get_stride(), 3).copy()


def _load_opencv(path):
    data = np.fromfile(path, dtype=np.uint8)
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)      # applies the EXIF orientation
    if bgr is None:
        raise LoadError("OpenCV cannot read the file")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _load_pixbuf(path):
    pb = GdkPixbuf.Pixbuf.new_from_file(path).apply_embedded_orientation()
    n = pb.get_n_channels()
    rgb = _rows(pb.read_pixel_bytes().get_data(), pb.get_width(), pb.get_height(), pb.get_rowstride(), n)
    return np.ascontiguousarray(rgb[:, :, :3])


def load(path, max_side=None):
    """Photo as an RGB array (height x width x 3)."""
    from .processing import shrink
    errors = []
    for loader, available in ((_load_glycin, Gly), (_load_opencv, True), (_load_pixbuf, GdkPixbuf)):
        if not available:
            continue
        try:
            rgb = loader(path)
            return shrink(rgb, max_side) if max_side else rgb
        except Exception as e:  # try the next one
            errors.append(f"{loader.__name__}: {e}")
    raise LoadError("; ".join(errors))


def encode_jpeg(img, quality=85):
    """JPEG bytes from an RGB or single channel array."""
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality, cv2.IMWRITE_JPEG_OPTIMIZE, 1])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


def encode_png(img):
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return buf.tobytes()
