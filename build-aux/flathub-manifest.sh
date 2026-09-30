#!/usr/bin/env bash
# Write the manifest for the Flathub submission: same recipe as the local one,
# but Photo Scanner itself comes from a tagged release on GitHub instead of this folder.
#
#   build-aux/flathub-manifest.sh v1.0.0 > io.github.<user>.PhotoScanner.json
#
# Run it after "git tag v1.0.0 && git push --tags".
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${1:?release tag, e.g. v1.0.0}"
COMMIT="$(git rev-parse "$TAG^{commit}")"
REPO="https://github.com/$(sed -n "s/^github_user = '\(.*\)'/\1/p" meson.build)/photoscanner.git"
MANIFEST="$(ls build-aux/flatpak/io.github.*.PhotoScanner.json | head -n1)"
TAG="$TAG" COMMIT="$COMMIT" REPO="$REPO" python3 - "$MANIFEST" <<'PY'
import json, os, sys
m = json.load(open(sys.argv[1]))
app = m["modules"][-1]
app["sources"] = [{"type": "git", "url": os.environ["REPO"], "tag": os.environ["TAG"], "commit": os.environ["COMMIT"],
                   "x-checker-data": {"type": "git", "tag-pattern": "^v([\\d.]+)$"}}]
print(json.dumps(m, indent=4))
PY
