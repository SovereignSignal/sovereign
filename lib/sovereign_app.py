"""Where the installed Sovereign.app is, for the updater and the status alike.

Run from inside an app, the backend's own bundle is the installed app, wherever someone
put it: ~/Applications, /Applications or anywhere else. Run from a source checkout it is
the first known folder that holds Sovereign.app, and ~/Applications for a fresh install.

Never whatever the bundle identifier resolves to. On 2026-09-20 four bundles on one
machine shared com.sovereign.console and macOS picked the highest version it had
indexed, which that day was an unreleased build sitting in /private/tmp.
"""
import os
import plistlib

NAME = "Sovereign.app"
# Searched in order from a checkout. The first is also where a fresh install goes.
ROOTS = ("~/Applications", "/Applications")


def bundle_of(path):
    """The innermost *.app bundle that path sits inside, by its real location, or None."""
    p = os.path.realpath(path)
    while True:
        if p.endswith(".app") and os.path.isdir(os.path.join(p, "Contents")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def _preview(app):
    """Preview builds stay separate (build.sh will not install one), so one never counts."""
    try:
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as fh:
            return bool(plistlib.load(fh).get("SovereignPreview"))
    except Exception:
        return False


def installed_app_path(here, roots=ROOTS):
    """The installed app for code running at `here` (pass the caller's __file__)."""
    app = bundle_of(here)
    if app and not _preview(app):
        return app
    known = [os.path.join(os.path.expanduser(r), NAME) for r in roots]
    for candidate in known:
        if os.path.isdir(candidate):
            return candidate
    return known[0] if known else os.path.join(os.path.expanduser(ROOTS[0]), NAME)


def writable(app):
    """Whether this user can replace app: remove it and put a new one in its folder."""
    folder = os.path.dirname(app)
    if not os.path.isdir(folder):
        return writable(folder) if folder != app else False
    return os.access(folder, os.W_OK | os.X_OK) and (not os.path.exists(app) or os.access(app, os.W_OK))
