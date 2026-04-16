"""
api_app.py — PyInstaller entry point.

This file exists ONLY for PyInstaller native executable builds.
For normal execution use: python main.py --interface api
"""

# ── pysqlite3 monkey-patch (required for ChromaDB in the .exe) ────────────────
try:
    import pysqlite3 as sqlite3
    import sys
    sys.modules["sqlite3"] = sqlite3
except ImportError:
    pass  # Not running as compiled exe — regular sqlite3 is fine

# ── PyInstaller resource path setup ───────────────────────────────────────────
import sys
import os

if getattr(sys, "frozen", False):
    # Running as a compiled executable: make config/ discoverable relative to exe
    _base = os.path.dirname(sys.executable)
    if _base not in sys.path:
        sys.path.insert(0, _base)

# ── App ───────────────────────────────────────────────────────────────────────
from src.launch.api_launcher import ApiLauncher

launcher = ApiLauncher()
app = launcher.get_asgi_app()  # uvicorn reads this 'app' variable

if __name__ == "__main__":
    launcher.run()
