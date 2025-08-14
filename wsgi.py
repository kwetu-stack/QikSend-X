# wsgi.py — robust entrypoint for Gunicorn. Loads app.py by file path.
from pathlib import Path
import importlib.util, sys

ROOT = Path(__file__).resolve().parent
APP_FILE = ROOT / "app.py"                # <-- app.py is at repo root

if not APP_FILE.exists():
    raise RuntimeError(f"app.py not found at {APP_FILE}. Files here: {list(ROOT.iterdir())}")

spec = importlib.util.spec_from_file_location("app", str(APP_FILE))
mod = importlib.util.module_from_spec(spec)
sys.modules["app"] = mod
spec.loader.exec_module(mod)

app = getattr(mod, "app", None)
if app is None and hasattr(mod, "create_app"):
    app = mod.create_app()
if app is None:
    raise RuntimeError("Neither 'app' nor 'create_app()' found in app.py")
