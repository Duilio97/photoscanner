# window.py - main window
#
# SPDX-License-Identifier: GPL-3.0-or-later
import datetime
import threading
from gettext import gettext as _, ngettext
from pathlib import Path

import numpy as np
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from . import export, imageio, processing
from .editor import Editor
from .settings import Settings

FILTER_NAMES = {
    "enhanced": _("Enhanced Color"),
    "grayscale": _("Grayscale"),
    "bw": _("Black and White"),
    "original": _("Original"),
}


def texture(arr):
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    if arr.ndim == 2:
        return Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.G8, GLib.Bytes.new(arr.tobytes()), w)
    return Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.R8G8B8, GLib.Bytes.new(arr.tobytes()), w * 3)


def user_dir(kind):
    return GLib.get_user_special_dir(kind) or GLib.get_home_dir()


class Page:
    def __init__(self, path, preview, corners, found):
        self.path = path
        self.preview = preview
        self.photo_texture = texture(preview)
        self.corners = np.array(corners, dtype=np.float64)
        self.found = found
        self.rotation = 0
        self.version = 0
        self.result_texture = None
        self.thumbnail = None

    def set_result(self, img):
        self.result_texture = texture(img)
        self.thumbnail = texture(processing.shrink(img, 320))


class Window(Adw.ApplicationWindow):
    __gtype_name__ = "PhotoScannerWindow"

    def __init__(self, app):
        super().__init__(application=app, title=_("Photo Scanner"))
        self.settings = Settings()
        self.set_default_size(self.settings.get("width", 1100), self.settings.get("height", 760))
        if self.settings.get("maximized", False):
            self.maximize()
        self.pages = []
        self.current = None
        self.filter = self.settings.get("filter", "enhanced")
        if self.filter not in processing.FILTERS:
            self.filter = "enhanced"
        self.busy = 0
        self.thumbnails = []
        self._rebuilding = False

        self._setup_actions()
        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        # header bar
        header = Adw.HeaderBar()
        header.pack_start(Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Add Photos"),
                                     action_name="win.add"))
        self.spinner = Adw.Spinner() if hasattr(Adw, "Spinner") else Gtk.Spinner(spinning=True)
        self.spinner.set_visible(False)
        self.spinner.set_tooltip_text(_("Working…"))
        header.pack_start(self.spinner)
        menu = Gio.Menu()
        fmt = Gio.Menu()
        fmt.append(_("A4 Pages"), "win.page-format::a4")
        fmt.append(_("Pages the Size of the Document"), "win.page-format::document")
        menu.append_section(_("PDF Page Size"), fmt)
        other = Gio.Menu()
        other.append(_("Save as Images…"), "win.save-images")
        other.append(_("Remove All Pages"), "win.clear")
        menu.append_section(None, other)
        about = Gio.Menu()
        about.append(_("Keyboard Shortcuts"), "win.show-help-overlay")
        about.append(_("About Photo Scanner"), "app.about")
        menu.append_section(None, about)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       tooltip_text=_("Main Menu"), primary=True))
        export_button = Gtk.Button(label=_("Export PDF"), action_name="win.export")
        export_button.add_css_class("suggested-action")
        header.pack_end(export_button)
        view.add_top_bar(header)

        # empty state
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        empty = Adw.StatusPage(icon_name=app.get_application_id() + "-symbolic",
                               title=_("Scan a Document"),
                               description=_("Drop photos of documents here, or choose them. "
                                             "The sheet is found automatically and its corners "
                                             "can be adjusted by hand."))
        choose = Gtk.Button(label=_("Choose Photos…"), action_name="win.add", halign=Gtk.Align.CENTER)
        choose.add_css_class("pill")
        choose.add_css_class("suggested-action")
        empty.set_child(choose)
        self.stack.add_named(empty, "empty")

        # pages on the left + editor
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=190)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class("navigation-sidebar")
        self.list.update_property([Gtk.AccessibleProperty.LABEL], [_("Pages")])
        self.list.connect("row-selected", self._row_selected)
        sidebar.append(Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER, child=self.list))
        tools = Gtk.Box(spacing=4, halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=6)
        for icon, action, tip in (("go-up-symbolic", "win.move-up", _("Move Up")),
                                  ("go-down-symbolic", "win.move-down", _("Move Down")),
                                  ("user-trash-symbolic", "win.remove", _("Remove Page"))):
            b = Gtk.Button(icon_name=icon, action_name=action, tooltip_text=tip)
            b.add_css_class("flat")
            tools.append(b)
        sidebar.append(tools)
        body.append(sidebar)
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self.editor = Editor()
        self.editor.connect("corners-changed", lambda *a: self._reprocess_current())
        column.append(self.editor)
        bar = Gtk.ActionBar()
        modes = Gtk.Box()
        modes.add_css_class("linked")
        self.corners_button = Gtk.ToggleButton(label=_("Corners"), active=True,
                                               tooltip_text=_("Adjust the corners of the sheet"))
        self.result_button = Gtk.ToggleButton(label=_("Result"), group=self.corners_button,
                                              tooltip_text=_("Show the finished scan"))
        self.corners_button.connect("toggled", self._mode_changed)
        modes.append(self.corners_button)
        modes.append(self.result_button)
        bar.pack_start(modes)
        self.filter_dropdown = Gtk.DropDown.new_from_strings([FILTER_NAMES[f] for f in processing.FILTERS])
        self.filter_dropdown.set_selected(processing.FILTERS.index(self.filter))
        self.filter_dropdown.set_tooltip_text(_("Filter (applies to all pages)"))
        self.filter_dropdown.connect("notify::selected", self._filter_changed)
        bar.set_center_widget(self.filter_dropdown)
        # pack_end puts every button left of the previous one: listed right to left
        for icon, action, tip in (("object-rotate-right-symbolic", "win.rotate-right", _("Rotate Right")),
                                  ("object-rotate-left-symbolic", "win.rotate-left", _("Rotate Left"))):
            bar.pack_end(Gtk.Button(icon_name=icon, action_name=action, tooltip_text=tip))
        bar.pack_end(Gtk.Button(label=_("Whole Photo"), action_name="win.whole",
                                tooltip_text=_("Use the whole photo, without cropping")))
        bar.pack_end(Gtk.Button(label=_("Detect"), action_name="win.detect",
                                tooltip_text=_("Find the corners of the sheet again")))
        column.append(bar)
        body.append(column)
        self.stack.add_named(body, "pages")
        view.set_content(self.stack)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._files_dropped)
        self.stack.add_controller(drop)
        self.connect("close-request", self._save_state)
        self._update_actions()

    # actions
    def _setup_actions(self):
        simple = {
            "add": (self._choose_photos, ["<Control>o"]),
            "export": (self._export_pdf, ["<Control>s"]),
            "save-images": (self._save_images, ["<Control><Shift>s"]),
            "remove": (self._remove, ["Delete"]),
            "clear": (self._clear, []),
            "move-up": (lambda: self._move(-1), ["<Alt>Up"]),
            "move-down": (lambda: self._move(1), ["<Alt>Down"]),
            "rotate-left": (lambda: self._rotate(-1), ["<Control>Left"]),
            "rotate-right": (lambda: self._rotate(1), ["<Control>Right"]),
            "detect": (self._detect, ["<Control>d"]),
            "whole": (self._whole, []),
            "toggle-mode": (self._toggle_mode, ["<Control>r"]),
            "close": (self.close, ["<Control>w"]),
            "show-help-overlay": (self._shortcuts, ["<Control>question"]),
        }
        self.actions = {}
        app = self.get_application()
        for name, (func, accels) in simple.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *x, f=func: f())
            self.add_action(action)
            self.actions[name] = action
            if accels:
                app.set_accels_for_action(f"win.{name}", accels)
        self.page_format = self.settings.get("page-format", "a4")
        fmt = Gio.SimpleAction.new_stateful("page-format", GLib.VariantType.new("s"),
                                            GLib.Variant("s", self.page_format))
        fmt.connect("change-state", self._format_changed)
        self.add_action(fmt)

    def _update_actions(self):
        has_pages = bool(self.pages)
        idle = self.busy == 0
        for name in ("export", "save-images", "clear"):
            self.actions[name].set_enabled(has_pages and idle)
        for name in ("remove", "rotate-left", "rotate-right", "detect", "whole", "toggle-mode"):
            self.actions[name].set_enabled(self.current is not None)
        self.actions["move-up"].set_enabled(bool(self.current))
        self.actions["move-down"].set_enabled(self.current is not None and self.current < len(self.pages) - 1)
        self.stack.set_visible_child_name("pages" if has_pages else "empty")
        self.spinner.set_visible(self.busy > 0)

    def _set_busy(self, delta):
        self.busy += delta
        self._update_actions()

    def toast(self, text, button=None, callback=None):
        t = Adw.Toast(title=text, timeout=5)
        if button:
            t.set_button_label(button)
            t.connect("button-clicked", lambda *a: callback())
        self.toasts.add_toast(t)

    def _save_state(self, *args):
        width, height = self.get_default_size()
        self.settings.update({"width": width, "height": height, "maximized": self.is_maximized(),
                              "filter": self.filter, "page-format": self.page_format})
        return False

    def _shortcuts(self):
        rows = [
            (_("Add Photos"), "<Control>o"), (_("Export PDF"), "<Control>s"),
            (_("Save as Images…"), "<Control><Shift>s"), (_("Switch Corners/Result"), "<Control>r"),
            (_("Detect"), "<Control>d"), (_("Rotate Left"), "<Control>Left"), (_("Rotate Right"), "<Control>Right"),
            (_("Move Up"), "<Alt>Up"), (_("Move Down"), "<Alt>Down"), (_("Remove Page"), "Delete"),
            (_("Close Window"), "<Control>w"), (_("Quit"), "<Control>q"),
        ]
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup()
        for title, accel in rows:
            row = Adw.ActionRow(title=title)
            row.add_suffix(Gtk.ShortcutLabel(accelerator=accel, valign=Gtk.Align.CENTER))
            group.add(row)
        page.add(group)
        dialog = Adw.Dialog(title=_("Keyboard Shortcuts"), content_width=420, content_height=560,
                            child=Adw.ToolbarView(content=page))
        dialog.get_child().add_top_bar(Adw.HeaderBar())
        dialog.present(self)

    # adding photos
    def _choose_photos(self):
        image_filter = Gtk.FileFilter(name=_("Photos"))
        for mime in imageio.MIME_TYPES:
            image_filter.add_mime_type(mime)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(image_filter)
        dialog = Gtk.FileDialog(title=_("Choose Photos of Documents"), filters=filters, default_filter=image_filter)
        dialog.set_initial_folder(Gio.File.new_for_path(user_dir(GLib.UserDirectory.DIRECTORY_PICTURES)))
        dialog.open_multiple(self, None, self._photos_chosen)

    def _photos_chosen(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        self.add_files([files.get_item(i) for i in range(files.get_n_items())])

    def _files_dropped(self, target, value, x, y):
        self.add_files(value.get_files())
        return True

    def add_files(self, files):
        paths = [f.get_path() for f in files if f and f.get_path()]
        if not paths:
            return
        self._set_busy(1)
        filter_name = self.filter

        def work():
            not_found, failed = 0, []
            for path in paths:
                try:
                    preview = imageio.load(path, processing.PREVIEW_SIZE)
                    corners, found = processing.detect_corners(preview)
                    result = processing.process(preview, corners, filter_name, 0)
                    not_found += not found
                    GLib.idle_add(self._page_ready, path, preview, corners, found, result, filter_name)
                except Exception as e:
                    print(f"Cannot open {path}: {e}")
                    failed.append(Path(path).name)
            GLib.idle_add(self._loading_done, not_found, failed)

        threading.Thread(target=work, daemon=True).start()

    def _page_ready(self, path, preview, corners, found, result, filter_name):
        page = Page(path, preview, corners, found)
        page.set_result(result)
        self.pages.append(page)
        if filter_name != self.filter:           # the filter changed meanwhile
            self._reprocess(page)
        self._rebuild_list(len(self.pages) - 1)
        return False

    def _loading_done(self, not_found, failed):
        self._set_busy(-1)
        if failed:
            self.toast(_("Cannot open: {}").format(", ".join(failed)))
        elif not_found:
            self.toast(_("Sheet not found: drag the corners onto its edges") if not_found == 1
                       else _("In some photos the sheet was not found: adjust the corners by hand"))
        return False

    # page list
    def _rebuild_list(self, select=None):
        self._rebuilding = True
        self.list.remove_all()
        self.thumbnails = []
        for i, page in enumerate(self.pages):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=6, margin_bottom=6)
            picture = Gtk.Picture(paintable=page.thumbnail, can_shrink=True,
                                  content_fit=Gtk.ContentFit.CONTAIN, height_request=170)
            box.append(picture)
            label = Gtk.Label(label=str(i + 1))
            label.add_css_class("caption")
            label.add_css_class("dim-label")
            box.append(label)
            row = Gtk.ListBoxRow(child=box)
            row.update_property([Gtk.AccessibleProperty.LABEL], [_("Page {}").format(i + 1)])
            self._make_draggable(row, i)
            self.list.append(row)
            self.thumbnails.append(picture)
        self._rebuilding = False
        if select is not None and self.pages:
            self.list.select_row(self.list.get_row_at_index(min(select, len(self.pages) - 1)))
        else:
            self._row_selected(self.list, None)
        self._update_actions()

    def _make_draggable(self, row, index):
        """Pages can be reordered by dragging them in the list."""
        source = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        source.connect("prepare", lambda s, x, y: Gdk.ContentProvider.new_for_value(GObject.Value(int, index)))
        source.connect("drag-begin", lambda s, d: s.set_icon(Gtk.WidgetPaintable.new(row), 0, 0))
        row.add_controller(source)
        target = Gtk.DropTarget.new(int, Gdk.DragAction.MOVE)
        target.connect("drop", lambda t, value, x, y: self._reorder(value, index))
        row.add_controller(target)

    def _reorder(self, source, destination):
        if source == destination or not (0 <= source < len(self.pages)):
            return False
        page = self.pages.pop(source)
        self.pages.insert(destination, page)
        GLib.idle_add(lambda: self._rebuild_list(destination) and False)
        return True

    def _row_selected(self, listbox, row):
        if self._rebuilding:
            return
        self.current = row.get_index() if row else None
        self.editor.show_page(self.pages[self.current] if row else None)
        self._update_actions()

    def _current_page(self):
        return self.pages[self.current] if self.current is not None else None

    # editing
    def _reprocess(self, page):
        """Recompute the preview of the scan in the background and refresh the view."""
        page.version += 1
        version, corners, rotation, filter_name = page.version, page.corners.copy(), page.rotation, self.filter

        def work():
            result = processing.process(page.preview, corners, filter_name, rotation)
            GLib.idle_add(done, result)

        def done(result):
            if page.version == version:
                page.set_result(result)
                if page in self.pages:
                    i = self.pages.index(page)
                    if i < len(self.thumbnails):
                        self.thumbnails[i].set_paintable(page.thumbnail)
                if page is self._current_page():
                    self.editor.queue_draw()
            return False

        threading.Thread(target=work, daemon=True).start()

    def _reprocess_current(self):
        if self._current_page():
            self._reprocess(self._current_page())

    def _mode_changed(self, button):
        self.editor.show_page(self._current_page(), "corners" if self.corners_button.get_active() else "result")

    def _toggle_mode(self):
        (self.result_button if self.corners_button.get_active() else self.corners_button).set_active(True)

    def _filter_changed(self, *args):
        self.filter = processing.FILTERS[self.filter_dropdown.get_selected()]
        for page in self.pages:
            self._reprocess(page)
        if self.pages:
            self.result_button.set_active(True)

    def _format_changed(self, action, value):
        action.set_state(value)
        self.page_format = value.get_string()

    def _rotate(self, direction):
        page = self._current_page()
        if page:
            page.rotation = (page.rotation + direction) % 4
            self._reprocess(page)
            self.result_button.set_active(True)

    def _detect(self):
        page = self._current_page()
        if page:
            page.corners, page.found = processing.detect_corners(page.preview)
            if not page.found:
                self.toast(_("Sheet not found: drag the corners onto its edges"))
            self.corners_button.set_active(True)
            self.editor.queue_draw()
            self._reprocess(page)

    def _whole(self):
        page = self._current_page()
        if page:
            page.corners = processing.WHOLE_IMAGE.copy()
            self.editor.queue_draw()
            self._reprocess(page)

    def _remove(self):
        if self.current is not None:
            del self.pages[self.current]
            self._rebuild_list(self.current if self.pages else None)

    def _clear(self):
        self.pages.clear()
        self._rebuild_list()

    def _move(self, direction):
        i = self.current
        if i is None or not (0 <= i + direction < len(self.pages)):
            return
        self.pages[i], self.pages[i + direction] = self.pages[i + direction], self.pages[i]
        self._rebuild_list(i + direction)

    # saving
    def _page_data(self):
        return [(p.path, p.corners.copy(), p.rotation) for p in self.pages]

    def _base_name(self):
        # TRANSLATORS: default file name; {} is the date and time
        return _("Scan {}").format(datetime.datetime.now().strftime("%Y-%m-%d %H.%M"))

    def _export_pdf(self):
        dialog = Gtk.FileDialog(title=_("Save PDF"), initial_name=self._base_name() + ".pdf")
        dialog.set_initial_folder(Gio.File.new_for_path(user_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS)))
        dialog.save(self, None, self._pdf_chosen)

    def _pdf_chosen(self, dialog, result):
        try:
            path = dialog.save_finish(result).get_path()
        except GLib.Error:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        data, filter_name, page_format = self._page_data(), self.filter, self.page_format
        self._set_busy(1)

        def work():
            try:
                export.export_pdf(data, path, filter_name, page_format, title=Path(path).stem)
                GLib.idle_add(self._saved, path, ngettext("PDF saved ({} page)", "PDF saved ({} pages)",
                                                          len(data)).format(len(data)))
            except Exception as e:
                GLib.idle_add(self._failed, _("Could not save: {}").format(e))

        threading.Thread(target=work, daemon=True).start()

    def _save_images(self):
        dialog = Gtk.FileDialog(title=_("Choose a Folder for the Images"))
        dialog.set_initial_folder(Gio.File.new_for_path(user_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS)))
        dialog.select_folder(self, None, self._folder_chosen)

    def _folder_chosen(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result).get_path()
        except GLib.Error:
            return
        data, filter_name, name = self._page_data(), self.filter, self._base_name()
        self._set_busy(1)

        def work():
            try:
                export.export_images(data, folder, name, filter_name)
                GLib.idle_add(self._saved, folder, ngettext("{} image saved", "{} images saved",
                                                            len(data)).format(len(data)))
            except Exception as e:
                GLib.idle_add(self._failed, _("Could not save: {}").format(e))

        threading.Thread(target=work, daemon=True).start()

    def _saved(self, path, text):
        self._set_busy(-1)

        def open_it():
            Gtk.FileLauncher.new(Gio.File.new_for_path(path)).launch(self, None, None, None)

        self.toast(text, _("Open"), open_it)
        return False

    def _failed(self, text):
        self._set_busy(-1)
        self.toast(text)
        return False
