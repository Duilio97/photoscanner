# pdf.py - a tiny PDF writer for scanned pages
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes a PDF with one image per page.

Colour and grey pages are stored as JPEG (copied as-is, no re-encoding);
black and white pages as 1 bit per pixel, compressed with Flate.
"""
import zlib

import numpy as np

A4 = (595.276, 841.890)     # points (1/72 inch)


class Page:
    def __init__(self, width, height, data, colorspace, bits, filter_name):
        self.width, self.height = width, height
        self.data, self.colorspace, self.bits, self.filter = data, colorspace, bits, filter_name

    @classmethod
    def jpeg(cls, data, width, height, gray=False):
        return cls(width, height, data, "/DeviceGray" if gray else "/DeviceRGB", 8, "/DCTDecode")

    @classmethod
    def bilevel(cls, img):
        """img: single channel array, > 127 = white."""
        packed = np.packbits(img > 127, axis=1)       # 1 = white in DeviceGray
        return cls(img.shape[1], img.shape[0], zlib.compress(packed.tobytes(), 9), "/DeviceGray", 1, "/FlateDecode")


def _page_box(page, page_format):
    """Page size and where the image goes, in points."""
    w, h = page.width, page.height
    if page_format == "a4":
        pw, ph = A4 if h >= w else (A4[1], A4[0])
        s = min(pw / w, ph / h)
        iw, ih = w * s, h * s
        return pw, ph, (pw - iw) / 2, (ph - ih) / 2, iw, ih
    # "document": longest side as long as an A4 sheet, same shape as the scan
    s = A4[1] / max(w, h)
    return w * s, h * s, 0, 0, w * s, h * s


def write(path, pages, page_format="a4", title=None, producer="Photo Scanner"):
    objects = []                                  # object bodies (bytes); object n is objects[n - 1]

    def add(body):
        objects.append(body)
        return len(objects)

    def pdf_string(s):
        """Text string in UTF-16 with byte order mark: any language works."""
        return "<FEFF" + s.encode("utf-16-be").hex().upper() + ">"

    catalog = add(None)
    pages_obj = add(None)
    kids = []
    for n, page in enumerate(pages):
        pw, ph, x, y, iw, ih = _page_box(page, page_format)
        image = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s "
                    b"/BitsPerComponent %d /Filter %s /Length %d >>\nstream\n"
                    % (page.width, page.height, page.colorspace.encode(), page.bits, page.filter.encode(), len(page.data))
                    + page.data + b"\nendstream")
        content = ("q %.3f 0 0 %.3f %.3f %.3f cm /Im0 Do Q" % (iw, ih, x, y)).encode()
        stream = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content))
        kids.append(add(("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.3f %.3f] "
                         "/Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>"
                         % (pages_obj, pw, ph, image, stream)).encode()))
    objects[catalog - 1] = ("<< /Type /Catalog /Pages %d 0 R >>" % pages_obj).encode()
    objects[pages_obj - 1] = ("<< /Type /Pages /Kids [%s] /Count %d >>"
                              % (" ".join("%d 0 R" % k for k in kids), len(kids))).encode()
    info_items = "/Producer " + pdf_string(producer)
    if title:
        info_items += " /Title " + pdf_string(title)
    info = add(("<< %s >>" % info_items).encode())

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for o in offsets:
        out += b"%010d 00000 n \n" % o
    out += (b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, catalog, info, xref))
    with open(path, "wb") as f:
        f.write(out)
