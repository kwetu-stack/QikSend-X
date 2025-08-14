# wsgi.py — stable entrypoint for Gunicorn
# Works for both styles:
#   1) app = Flask(__name__)
#   2) def create_app(): return app

from importlib import import_module

mod = import_module("app")  # imports app.py as a module

if hasattr(mod, "app"):
    app = mod.app
elif hasattr(mod, "create_app"):
    app = mod.create_app()
else:
    raise RuntimeError(
        "Neither 'app' nor 'create_app()' found in app.py"
    )
