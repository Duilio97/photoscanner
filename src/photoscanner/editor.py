# editor.py - photo with draggable sheet corners, or the finished scan
#
# SPDX-License-Identifier: GPL-3.0-or-later
import numpy as np
from gi.repository import Gdk, GObject, Graphene, Gsk, Gtk


def rgba(r, g, b, a=1.0):
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


WHITE = rgba(1, 1, 1, 0.95)
VEIL = rgba(0, 0, 0, 0.45)


# Note: build the struct first and then init it. The chained form
# "Gsk.RoundedRect().init_from_rect(...)" returns a copy with a wrong position in PyGObject.
def point(x, y):
    p = Graphene.Point()
    p.init(x, y)
    return p


def rect(x, y, w, h):
    r = Graphene.Rect()
    r.init(x, y, w, h)
    return r


def rounded(r, radius):
    rr = Gsk.RoundedRect()
    rr.init_from_rect(r, radius)
    return rr


def polygon(builder, pts):
    builder.move_to(*pts[0])
    for p in pts[1:]:
        builder.line_to(*p)
    builder.close()


class Editor(Gtk.Widget):
    """Shows the photo with the outline of the sheet (handles to drag) or the result.

    Handles 0-3 are the corners; 4-7 the middle of the sides (they move the whole side).
    """

    __gtype_name__ = "PhotoScannerEditor"
    __gsignals__ = {"corners-changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.page = None
        self.mode = "corners"
        self.active = None
        self.hover = None
        self.start = None
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_size_request(300, 300)
        self.set_focusable(True)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.add_controller(drag)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        motion.connect("leave", lambda *a: self._set_hover(None))
        self.add_controller(motion)

    def show_page(self, page, mode=None):
        self.page = page
        if mode:
            self.mode = mode
        self.active = self.hover = None
        self.set_cursor(None)
        self.queue_draw()

    def _accent(self):
        # the system accent colour (blue by default), as used for selections
        try:
            from gi.repository import Adw
            return Adw.StyleManager.get_default().get_accent_color_rgba()
        except (AttributeError, ImportError):
            return rgba(0.208, 0.518, 0.894)

    # geometry
    def _texture(self):
        if not self.page:
            return None
        if self.mode == "result" and self.page.result_texture:
            return self.page.result_texture
        return self.page.photo_texture

    def _frame(self, tex):
        W, H = self.get_width(), self.get_height()
        m = 34 if self.mode == "corners" else 20
        tw, th = tex.get_width(), tex.get_height()
        s = max(0.01, min((W - 2 * m) / tw, (H - 2 * m) / th))
        return (W - tw * s) / 2, (H - th * s) / 2, tw * s, th * s

    def _screen_corners(self):
        x, y, w, h = self._frame(self.page.photo_texture)
        return [(x + u * w, y + v * h) for u, v in self.page.corners]

    def _handles(self):
        c = self._screen_corners()
        sides = [((c[i][0] + c[(i + 1) % 4][0]) / 2, (c[i][1] + c[(i + 1) % 4][1]) / 2) for i in range(4)]
        return c + sides

    def _nearest(self, x, y):
        if not self.page or self.mode != "corners":
            return None
        best, dmin = None, 30.0
        for i, (px, py) in enumerate(self._handles()):
            d = ((px - x) ** 2 + (py - y) ** 2) ** 0.5 - (4 if i < 4 else 0)   # corners win
            if d < dmin:
                best, dmin = i, d
        return best

    # drawing
    def do_snapshot(self, snap):
        tex = self._texture()
        if tex is None:
            return
        x, y, w, h = self._frame(tex)
        r = rect(x, y, w, h)
        if self.mode == "result":
            snap.append_outset_shadow(rounded(r, 0), rgba(0, 0, 0, 0.18), 0, 2, 0, 12)
        snap.append_scaled_texture(tex, Gsk.ScalingFilter.TRILINEAR, r)
        if self.mode != "corners":
            return
        accent = self._accent()
        c = self._screen_corners()
        b = Gsk.PathBuilder.new()                # dark veil outside the sheet
        b.add_rect(r)
        polygon(b, c)
        snap.append_fill(b.to_path(), Gsk.FillRule.EVEN_ODD, VEIL)
        b = Gsk.PathBuilder.new()
        polygon(b, c)
        snap.append_stroke(b.to_path(), Gsk.Stroke.new(2.0), accent)
        for i, (px, py) in enumerate(self._handles()):
            big = i in (self.active, self.hover)
            radius = (12 if big else 10) if i < 4 else (8 if big else 6)
            b = Gsk.PathBuilder.new()
            b.add_circle(point(px, py), radius)
            path = b.to_path()
            snap.append_fill(path, Gsk.FillRule.WINDING, accent if big else WHITE)
            snap.append_stroke(path, Gsk.Stroke.new(2.5), WHITE if big else accent)
        if self.active is not None:
            self._loupe(snap, tex, (x, y, w, h), self._handles()[self.active], accent)

    def _loupe(self, snap, tex, frame, centre, accent):
        """Magnified view of the point being moved, in a corner away from the pointer."""
        x, y, w, h = frame
        R, Z = 64, 3.0
        px, py = centre
        cx = self.get_width() - R - 14 if px < self.get_width() / 2 else R + 14
        cy = R + 14
        circle = rect(cx - R, cy - R, 2 * R, 2 * R)
        snap.append_outset_shadow(rounded(circle, R), rgba(0, 0, 0, 0.35), 0, 2, 0, 10)
        snap.push_rounded_clip(rounded(circle, R))
        snap.append_color(rgba(0.3, 0.3, 0.3), circle)
        snap.append_scaled_texture(tex, Gsk.ScalingFilter.LINEAR, rect(cx - (px - x) * Z, cy - (py - y) * Z, w * Z, h * Z))
        b = Gsk.PathBuilder.new()
        polygon(b, [(cx + (qx - px) * Z, cy + (qy - py) * Z) for qx, qy in self._screen_corners()])
        snap.append_stroke(b.to_path(), Gsk.Stroke.new(1.5), accent)
        b = Gsk.PathBuilder.new()
        b.move_to(cx - 9, cy)
        b.line_to(cx + 9, cy)
        b.move_to(cx, cy - 9)
        b.line_to(cx, cy + 9)
        snap.append_stroke(b.to_path(), Gsk.Stroke.new(1.5), WHITE)
        snap.pop()
        b = Gsk.PathBuilder.new()
        b.add_circle(point(cx, cy), R)
        snap.append_stroke(b.to_path(), Gsk.Stroke.new(3), WHITE)

    # pointer
    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.set_cursor(Gdk.Cursor.new_from_name("grab" if i is not None else "default"))
            self.queue_draw()

    def _motion(self, ctrl, x, y):
        if self.active is None:
            self._set_hover(self._nearest(x, y))

    def _drag_begin(self, gesture, x, y):
        self.grab_focus()
        self.active = self._nearest(x, y)
        if self.active is None:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        self.start = self.page.corners.copy()
        self.set_cursor(Gdk.Cursor.new_from_name("grabbing"))
        self.queue_draw()

    def _drag_update(self, gesture, dx, dy):
        if self.active is None:
            return
        _, _, w, h = self._frame(self.page.photo_texture)
        delta = np.array([dx / w, dy / h])
        new = self.start.copy()
        if self.active < 4:
            new[self.active] = self.start[self.active] + delta
        else:                                      # side: both its corners move together
            i = self.active - 4
            for j in (i, (i + 1) % 4):
                new[j] = self.start[j] + delta
        self.page.corners = np.clip(new, 0, 1)
        self.queue_draw()

    def _drag_end(self, gesture, dx, dy):
        if self.active is None:
            return
        self.active = None
        self.set_cursor(Gdk.Cursor.new_from_name("grab"))
        self.queue_draw()
        self.emit("corners-changed")
