# export.py - full resolution pages to PDF or image files
#
# SPDX-License-Identifier: GPL-3.0-or-later
import os

from . import imageio, pdf, processing


def _final_pages(pages, filter_name, progress=None):
    """pages = [(path, corners, rotation), ...] -> processed full resolution arrays."""
    for i, (path, corners, rotation) in enumerate(pages):
        if progress:
            progress(i, len(pages))
        img = processing.process(imageio.load(path), corners, filter_name, rotation)
        yield processing.shrink(img, processing.EXPORT_MAX_SIZE)


def export_pdf(pages, destination, filter_name, page_format="a4", title=None, progress=None):
    """page_format "a4": every page on an A4 sheet; "document": page as large as the document."""
    out = []
    for img in _final_pages(pages, filter_name, progress):
        h, w = img.shape[:2]
        if filter_name == "bw":
            out.append(pdf.Page.bilevel(img))
        else:
            out.append(pdf.Page.jpeg(imageio.encode_jpeg(img), w, h, gray=img.ndim == 2))
    tmp = destination + ".part"
    pdf.write(tmp, out, page_format, title=title)
    os.replace(tmp, destination)


def export_images(pages, folder, base_name, filter_name, progress=None):
    """One file per page: PNG for black and white, JPEG otherwise. Returns the paths."""
    paths = []
    for i, img in enumerate(_final_pages(pages, filter_name, progress), start=1):
        if filter_name == "bw":
            data, ext = imageio.encode_png(img), ".png"
        else:
            data, ext = imageio.encode_jpeg(img, 90), ".jpg"
        path = os.path.join(folder, f"{base_name} - {i:02d}{ext}")
        with open(path, "wb") as f:
            f.write(data)
        paths.append(path)
    return paths
