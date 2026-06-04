# -*- mode: python ; coding: utf-8 -*-
"""
Robust PyInstaller spec for chatbot-api
Includes: numpy, tiktoken (and tiktoken_ext), chromadb, langchain, langgraph, uvicorn, fastapi
Designed for one-folder COLLECT distribution (recommended for complex packages)
Before building: ensure tiktoken==0.7.0 is installed in the environment.
"""

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files, copy_metadata

# Project root (when running pyinstaller from project root this is fine)
spec_root = Path(os.getcwd())

# -------------------------
# Collect everything for numpy
# -------------------------
numpy_binaries, numpy_datas, numpy_hidden = collect_all("numpy")

# -------------------------
# Collect everything for tiktoken and tiktoken_ext (use collect_all to be safe)
# -------------------------
try:
    tiktoken_binaries, tiktoken_datas, tiktoken_hidden = collect_all("tiktoken")
except Exception:
    # fallback: collect_data_files only (older/newer installs)
    tiktoken_binaries, tiktoken_datas, tiktoken_hidden = [], collect_data_files("tiktoken"), []

try:
    tiktokenext_binaries, tiktokenext_datas, tiktokenext_hidden = collect_all("tiktoken_ext")
except Exception:
    tiktokenext_binaries, tiktokenext_datas, tiktokenext_hidden = [], collect_data_files("tiktoken_ext"), []

# -------------------------
# CRITICAL: Manually collect tiktoken encodings
# -------------------------
try:
    import tiktoken_ext.openai_public
    tiktoken_ext_path = Path(tiktoken_ext.openai_public.__file__).parent
    for encoding_file in tiktoken_ext_path.glob("*.tiktoken"):
        tiktoken_datas.append((str(encoding_file), "tiktoken_ext/openai_public"))
except Exception as e:
    print(f"Warning: Could not collect tiktoken_ext encodings: {e}")

# -------------------------
# Collect chromadb fully
# -------------------------
chromadb_binaries, chromadb_datas, chromadb_hidden = collect_all("chromadb")
chromadb_submodules = collect_submodules("chromadb")

# -------------------------
# LangChain, LangGraph, FastAPI, Uvicorn
# -------------------------
langchain_submodules = collect_submodules("langchain")
langgraph_submodules = collect_submodules("langgraph")
fastapi_submodules = collect_submodules("fastapi")
uvicorn_submodules = collect_submodules("uvicorn")

# -------------------------
# Other useful packages - collect data if present
# -------------------------
pydantic_datas = collect_data_files("pydantic") if os.path.isdir(spec_root / "venv") or True else []
openai_datas = collect_data_files("openai") if True else []

# gradio_client data files (types.json, etc.)
try:
    gradio_client_datas = collect_data_files("gradio_client")
except Exception:
    gradio_client_datas = []

# gradio data files
try:
    gradio_datas = collect_data_files("gradio")
except Exception:
    gradio_datas = []

# safehttpx — version.txt is read at import time via __init__.py
try:
    safehttpx_datas = collect_data_files("safehttpx")
except Exception:
    import safehttpx as _shx
    _shx_dir = Path(_shx.__file__).parent
    safehttpx_datas = [(str(p), "safehttpx") for p in _shx_dir.glob("*.txt")]

# Package metadata — required by pydantic EmailStr, importlib.metadata.version() calls
metadata_packages = [
    "email-validator",
    "email_validator",
    "pydantic",
    "fastapi",
    "uvicorn",
    "starlette",
    "langchain",
    "langgraph",
    "openai",
    "gradio",
    "gradio_client",
    "numpy",
    "tiktoken",
]
package_metadata = []
for pkg in metadata_packages:
    try:
        package_metadata += copy_metadata(pkg)
    except Exception:
        pass

# -------------------------
# Build datas & binaries lists
# -------------------------
datas = []
datas += numpy_datas or []
datas += tiktoken_datas or []
datas += tiktokenext_datas or []
datas += chromadb_datas or []
datas += pydantic_datas or []
datas += openai_datas or []
datas += gradio_client_datas or []
datas += gradio_datas or []
datas += safehttpx_datas or []
datas += package_metadata or []

# Ensure your 'src' directory is included so src.* imports work in exe
if (spec_root / "src").exists():
    datas.append((str(spec_root / "src"), "src"))

# CRITICAL: Explicitly include master_table_creation.sql for runtime access
master_sql_file = spec_root / "src" / "graphs" / "generic_text2sql" / "master_table_creation.sql"
if master_sql_file.exists():
    # Add to root of bundle for easy access via sys._MEIPASS
    datas.append((str(master_sql_file), "."))
    print(f"[SPEC] Added master_table_creation.sql to bundle")

# Add any explicit tiktoken registry files if they exist on disk
# This is defensive: if the standard collection missed them, include manually from site-packages
def try_add_tiktoken_registry():
    import importlib.util, sys
    try:
        import tiktoken
        base = Path(tiktoken.__file__).resolve().parent
        registry_dir = base / "registry" / "data"
        if registry_dir.exists():
            for p in registry_dir.glob("*.tiktoken"):
                # add (src_path, dest_folder_in_dist)
                datas.append((str(p), os.path.join("tiktoken", "registry", "data")))
    except Exception:
        # ignore if not present
        pass

try_add_tiktoken_registry()

# Binaries
binaries = []
binaries += numpy_binaries or []
binaries += tiktoken_binaries or []
binaries += tiktokenext_binaries or []
binaries += chromadb_binaries or []

# -------------------------
# Hidden imports (deduplicate)
# -------------------------
hiddenimports = []
hiddenimports += numpy_hidden or []
hiddenimports += tiktoken_hidden or []
hiddenimports += tiktokenext_hidden or []
hiddenimports += chromadb_hidden or []
hiddenimports += chromadb_submodules or []
hiddenimports += langchain_submodules or []
hiddenimports += langgraph_submodules or []
hiddenimports += fastapi_submodules or []
hiddenimports += uvicorn_submodules or []

# Add common explicit hidden imports for tiktoken registry access
hiddenimports += [
    "tiktoken",
    "tiktoken.model",
    "tiktoken.registry",
    "tiktoken.core",
    "tiktoken.load",
    "tiktoken_ext",
    "tiktoken_ext.openai_public",
    "tiktoken_encodings" ,  # harmless if not present
    "tiktoken.registry.data",
    # Chromadb internals
    "chromadb.execution.executor.local",
    "chromadb.db.impl.sqlite",
]

# Remove duplicates while preserving order
seen = set()
hidden_filtered = []
for h in hiddenimports:
    if h not in seen:
        seen.add(h)
        hidden_filtered.append(h)
hiddenimports = hidden_filtered

# -------------------------
# Excludes (do not exclude numpy/chromadb/tiktoken)
# -------------------------
excludes = [
    "pytest",
    "test",
    "tkinter",
    "matplotlib",
    "IPython",
    "notebook",
]

# -------------------------
# Analysis config
# -------------------------
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT

block_cipher = None

a = Analysis(
    ['api_app.py'],
    pathex=[str(spec_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['hooks'],   # add hook files (hook-tiktoken.py, hook-chromadb.py) here if you create them
    runtime_hooks=['hooks/rthook_tiktoken.py'],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# -------------------------
# PYZ / EXE / COLLECT
# -------------------------
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # True for COLLECT (one-folder) mode
    name='chatbot-api',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='chatbot-api',
)
