from whitenoise.storage import CompressedManifestStaticFilesStorage


class DashSafeManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """CompressedManifestStaticFilesStorage, but tolerant of a lookup that
    can't be resolved to a hashed name yet.

    explorer/dash_apps.py calls Django's static() at Python import time
    (DjangoDash's external_stylesheets=[static('explorer/canopy.css')]),
    which runs as a side effect of collectstatic importing the app in the
    first place - before collectstatic has copied anything into
    STATIC_ROOT or built the manifest that lookup depends on. Without
    this, a first-time collectstatic run on a fresh checkout crashes
    before it can produce the very manifest and files it needs.

    stored_name() falls back to the plain (unhashed) name whenever the
    normal hashed/manifest lookup can't resolve one - both when the
    manifest doesn't have an entry yet, and when it tries computing a
    fresh hash but the source file isn't in STATIC_ROOT yet either. The
    practical cost: canopy.css specifically won't get a cache-busting
    hashed URL (its unhashed URL is already baked into graph_app by the
    time the manifest exists) - every other static file collected
    normally still does.
    """

    def stored_name(self, name):
        try:
            return super().stored_name(name)
        except ValueError:
            return name
