# settings.py - a few remembered preferences
#
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os

from gi.repository import GLib


class Settings:
    """Small JSON file in the user configuration folder."""

    def __init__(self):
        self.path = os.path.join(GLib.get_user_config_dir(), "photoscanner", "settings.json")
        try:
            with open(self.path) as f:
                self.values = json.load(f)
        except (OSError, ValueError):
            self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def update(self, values):
        self.values.update(values)
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump(self.values, f, indent=1)
        except OSError:
            pass
