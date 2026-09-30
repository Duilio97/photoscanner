# main.py - application
#
# SPDX-License-Identifier: GPL-3.0-or-later
import sys
from gettext import gettext as _

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from .window import Window  # noqa: E402


class Application(Adw.Application):
    def __init__(self, app_id, version, developer, url):
        super().__init__(application_id=app_id, flags=Gio.ApplicationFlags.HANDLES_OPEN,
                         resource_base_path="/" + app_id.replace(".", "/"))
        self.version, self.developer, self.url = version, developer, url
        for name, func, accels in (("quit", lambda *a: self.quit(), ["<Control>q"]),
                                   ("about", self._about, [])):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", func)
            self.add_action(action)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)

    def _window(self):
        return self.props.active_window or Window(self)

    def do_activate(self):
        self._window().present()

    def do_open(self, files, *args):
        window = self._window()
        window.present()
        window.add_files(files)

    def _about(self, *args):
        about = Adw.AboutDialog(
            application_name=_("Photo Scanner"),
            application_icon=self.get_application_id(),
            developer_name=self.developer,
            version=self.version,
            website=self.url,
            issue_url=self.url + "/issues",
            comments=_("Turn photos of documents into clean scans and PDF files"),
            license_type=Gtk.License.GPL_3_0,
            copyright="© 2026 " + self.developer,
            # TRANSLATORS: put your name here, it is shown in the About dialog
            translator_credits=_("translator-credits"),
        )
        about.present(self.props.active_window)


def main(version, app_id, developer="", url=""):
    return Application(app_id, version, developer, url).run(sys.argv)
