# Tests for the image processing and PDF writing, on synthetic photos.
#
# Run from the project folder:  python3 -m unittest discover -s tests -v
#
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from photoscanner import export, pdf, processing  # noqa: E402


def document(width=1240, height=1754, rng=None):
    """A white page with a title, lines of "text" and a red stamp."""
    page = np.full((height, width, 3), (250, 248, 242), np.uint8)
    cv2.putText(page, "INVOICE 2026/118", (100, 160), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (60, 20, 20), 6)
    for i in range(36):
        y = 260 + i * 38
        cv2.putText(page, f"Line {i + 1:02d}  lorem ipsum dolor sit amet {i * 37 % 1000:4d},00",
                    (100, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 30, 30), 2)
    cv2.rectangle(page, (100, height - 150), (560, height - 60), (30, 30, 200), 5)
    return page


def background(kind, w, h, rng):
    if kind == "wood":
        img = np.ones((h, w, 3), np.float32) * np.array([80, 110, 150], np.float32)
        img += (np.sin(np.linspace(0, 60, w))[None, :, None] * 12).astype(np.float32)
    elif kind == "dark":
        img = np.ones((h, w, 3), np.float32) * np.array([70, 60, 60], np.float32)
    elif kind == "light":
        img = np.ones((h, w, 3), np.float32) * np.array([220, 225, 225], np.float32)
    elif kind == "checks":                              # tablecloth
        yy, xx = np.mgrid[0:h, 0:w]
        cell = ((yy // 90 + xx // 90) % 2).astype(np.float32)[..., None]
        img = np.array([60, 60, 190], np.float32) * cell + np.array([235, 235, 235], np.float32) * (1 - cell)
    else:                                               # stripes
        xx = np.arange(w)[None, :, None]
        img = np.where((xx // 40) % 2 == 0, 40, 200).astype(np.float32) * np.ones((h, w, 3), np.float32)
    noise = cv2.GaussianBlur(rng.normal(0, 20, (h, w)).astype(np.float32), (0, 0), 5)
    return img + noise[..., None]


def photo(kind, corners, size=(2000, 1500), shadow=0.4, seed=0):
    """Synthetic phone photo: the page in perspective on a background, with a shadow."""
    rng = np.random.default_rng(seed)
    w, h = size
    img = background(kind, w, h, rng)
    page = document().astype(np.float32)
    src = np.float32([[0, 0], [1239, 0], [1239, 1753], [0, 1753]])
    m = cv2.getPerspectiveTransform(src, np.float32(corners))
    fg = cv2.warpPerspective(page, m, (w, h))
    mask = cv2.warpPerspective(np.ones(page.shape[:2], np.float32), m, (w, h))[..., None]
    img = img * (1 - mask) + fg * mask
    yy, xx = np.mgrid[0:h, 0:w]
    light = 1 - shadow * np.clip((xx / w - 0.45) * 2.5, 0, 1) * (yy / h)
    img = np.clip(img * light[..., None] + rng.normal(0, 4, img.shape), 0, 255).astype(np.uint8)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB), processing.order_corners(corners) / np.array([w, h])


CASES = [
    ("wood", [[350, 190], [1640, 260], [1720, 1370], [260, 1300]], (2000, 1500)),
    ("dark", [[190, 300], [1320, 225], [1400, 1800], [125, 1725]], (1500, 2000)),
    ("light", [[150, 250], [1350, 350], [1300, 1850], [210, 1775]], (1500, 2000)),
    ("checks", [[300, 200], [1200, 260], [1250, 1800], [240, 1760]], (1500, 2000)),
    ("stripes", [[260, 240], [1260, 200], [1300, 1790], [220, 1830]], (1500, 2000)),
    ("wood", [[420, 120], [1260, 380], [1030, 1880], [120, 1600]], (1500, 2000)),     # strongly rotated
    ("dark", [[500, 500], [1100, 520], [1080, 1350], [480, 1330]], (1500, 2000)),     # small in the frame
    ("light", [[80, 90], [1420, 60], [1450, 1930], [50, 1950]], (1500, 2000)),        # almost the whole photo
    ("checks", [[400, 150], [1650, 180], [1600, 1400], [380, 1350]], (2000, 1500)),
    ("stripes", [[200, 300], [1700, 150], [1800, 1350], [150, 1400]], (2000, 1500)),
    ("dark", [[300, 400], [1250, 250], [1350, 1700], [200, 1850]], (1500, 2000)),
    ("wood", [[180, 220], [1330, 180], [1360, 1780], [160, 1820]], (1500, 2000)),
]


class Detection(unittest.TestCase):
    def test_corners(self):
        for n, (kind, corners, size) in enumerate(CASES):
            with self.subTest(case=n, background=kind):
                rgb, truth = photo(kind, corners, size, seed=n)
                preview = processing.shrink(rgb, processing.PREVIEW_SIZE)
                found_corners, found = processing.detect_corners(preview)
                self.assertTrue(found)
                error = np.abs(found_corners - truth).max() * max(preview.shape[:2])
                self.assertLess(error, 8, f"corner error {error:.1f} px")

    def test_nothing_to_find(self):
        rng = np.random.default_rng(1)
        rgb = np.clip(background("dark", 1600, 1200, rng), 0, 255).astype(np.uint8)
        corners, found = processing.detect_corners(rgb)
        self.assertFalse(found)
        np.testing.assert_array_equal(corners, processing.WHOLE_IMAGE)


class Filters(unittest.TestCase):
    def test_shapes_and_rotation(self):
        rgb, truth = photo(*CASES[0][:2], CASES[0][2])
        for name in processing.FILTERS:
            out = processing.process(rgb, truth, name, 0)
            turned = processing.process(rgb, truth, name, 1)
            self.assertEqual(out.shape[:2], turned.shape[1::-1])
            self.assertEqual(out.ndim, 3 if name in ("enhanced", "original") else 2)
        bw = processing.process(rgb, truth, "bw", 0)
        self.assertTrue(set(np.unique(bw)) <= {0, 255})
        self.assertGreater((bw == 255).mean(), 0.8)             # mostly white paper

    def test_shadow_removed(self):
        rgb, truth = photo("wood", CASES[0][1], CASES[0][2], shadow=0.5)
        out = processing.process(rgb, truth, "grayscale", 0)
        h, w = out.shape
        paper_left = np.percentile(out[h // 2:, : w // 5], 90)
        paper_right = np.percentile(out[h // 2:, -w // 5:], 90)   # in the shadow
        self.assertLess(abs(float(paper_left) - float(paper_right)), 12)


class Pdf(unittest.TestCase):
    def test_write_and_read_back(self):
        rgb, truth = photo(*CASES[1][:2], CASES[1][2])
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "photo è.jpg")
            cv2.imwrite(src, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            for filter_name in processing.FILTERS:
                for page_format in ("a4", "document"):
                    out = os.path.join(tmp, f"{filter_name}-{page_format}.pdf")
                    export.export_pdf([(src, truth, 0), (src, truth, 1)], out, filter_name, page_format,
                                      title="Scansione àè")
                    data = open(out, "rb").read()
                    self.assertTrue(data.startswith(b"%PDF-1.4"))
                    self.assertTrue(data.rstrip().endswith(b"%%EOF"))
                    self.assertEqual(data.count(b"/Type /Page "), 2)
                    # every xref offset points to the start of its object
                    xref = int(data[data.rindex(b"startxref") + 9:].split()[0])
                    table = data[xref:].split(b"trailer")[0].split(b"\n")[3:]
                    for n, line in enumerate(l for l in table if l.strip()):
                        offset = int(line[:10])
                        self.assertTrue(data[offset:].startswith(b"%d 0 obj" % (n + 1)))
            images = export.export_images([(src, truth, 0)], tmp, "scan", "bw")
            self.assertTrue(images[0].endswith(".png") and os.path.getsize(images[0]) > 0)

    def test_a4_layout(self):
        page = pdf.Page.jpeg(b"", 2000, 1000)
        pw, ph, x, y, iw, ih = pdf._page_box(page, "a4")
        self.assertGreater(pw, ph)                              # landscape image, landscape page
        self.assertAlmostEqual(iw / ih, 2.0, places=3)
        self.assertLessEqual(iw, pw)


if __name__ == "__main__":
    unittest.main()
