#!/usr/bin/env bash
# Set the GitHub account that publishes Photo Scanner: it becomes part of the
# application ID (io.github.<user>.PhotoScanner), of the links and of the
# Flatpak manifest name.
#
#   build-aux/set-publisher.sh <github-user> "<Your Name>"
set -euo pipefail
cd "$(dirname "$0")/.."

USER_NAME="${1:?GitHub user name, e.g. build-aux/set-publisher.sh mario "Mario Rossi"}"
DEV_NAME="${2:?Your name, as shown in the About dialog and on Flathub}"
if ! [[ "$USER_NAME" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "Invalid GitHub user name: $USER_NAME" >&2
    exit 1
fi
# In IDs the user name is lowercase (AppStream requires it for the developer ID;
# GitHub ignores the case) and "-" becomes "_" (not allowed in D-Bus names).
ID_USER="$(echo "${USER_NAME//-/_}" | tr '[:upper:]' '[:lower:]')"

OLD_MANIFEST="$(ls build-aux/flatpak/io.github.*.PhotoScanner.json | head -n1)"
USER_NAME="$USER_NAME" DEV_NAME="$DEV_NAME" ID_USER="$ID_USER" python3 - <<'PY'
import os, re
def meson_str(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"
e = os.environ
text = open("meson.build").read()
for key, value in (("github_user", meson_str(e["USER_NAME"])),
                   ("developer_name", meson_str(e["DEV_NAME"])),
                   ("app_id", meson_str("io.github." + e["ID_USER"] + ".PhotoScanner")),
                   ("developer_id", meson_str("io.github." + e["ID_USER"]))):
    text = re.sub(r"^%s = .*$" % key, lambda m: "%s = %s" % (key, value), text, count=1, flags=re.M)
open("meson.build", "w").write(text)
PY

NEW_MANIFEST="build-aux/flatpak/io.github.$ID_USER.PhotoScanner.json"
if [ "$OLD_MANIFEST" != "$NEW_MANIFEST" ]; then
    git mv "$OLD_MANIFEST" "$NEW_MANIFEST" 2>/dev/null || mv "$OLD_MANIFEST" "$NEW_MANIFEST"
fi
sed -i "s/\"id\": \".*\"/\"id\": \"io.github.$ID_USER.PhotoScanner\"/" "$NEW_MANIFEST"

echo "Application ID: io.github.$ID_USER.PhotoScanner"
echo "Repository:     https://github.com/$USER_NAME/photoscanner"
