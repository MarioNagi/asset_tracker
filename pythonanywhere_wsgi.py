"""WSGI entry point for the PythonAnywhere web app.

PythonAnywhere expects a ``wsgi.py``-style file whose module-level
``application`` variable is the WSGI callable. This file:

1. Adds the project root to ``sys.path`` so ``asset_tracker`` resolves.
2. Loads ``.env`` from the project root into ``os.environ`` so the
   deployment-time configuration travels with the code instead of
   requiring every variable to be re-typed in the PythonAnywhere
   web-app env-var panel.
3. Exposes ``application`` for the PythonAnywhere WSGI server.

Copy this file to ``/home/<your-username>/asset_tracker/wsgi.py`` on
the PythonAnywhere account (or symlink it) and set the WSGI
configuration file path in the Web tab to
``/home/<your-username>/asset_tracker/wsgi.py``. Adjust
``PROJECT_ROOT`` if you checked the code out somewhere other than
``~/asset_tracker``.
"""
import os
import sys
from pathlib import Path

# Project root on the PythonAnywhere account. Override by exporting
# ASSET_TRACKER_PROJECT_ROOT in the web app's env-var panel if the
# code lives somewhere other than ``~/asset_tracker``.
PROJECT_ROOT = Path(
    os.environ.get(
        'ASSET_TRACKER_PROJECT_ROOT',
        str(Path.home() / 'asset_tracker'),
    )
).resolve()

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_env(env_path):
    """Populate ``os.environ`` from a simple ``.env`` file.

    Only adds variables that are not already set in the environment, so
    values declared in the PythonAnywhere env-var panel always win.
    Empty lines and ``#`` comments are ignored. Surrounding single or
    double quotes around a value are stripped.
    """
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


_load_env(PROJECT_ROOT / '.env')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'asset_tracker.settings')

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
