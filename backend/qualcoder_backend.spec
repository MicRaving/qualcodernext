# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the QualCoder v4 packaged backend (onedir, windowed).

Onedir (not onefile): the app ships the whole directory in the installer,
so nothing is unpacked at launch — the current onefile variant re-extracted
~140 MB to a temp dir on every start, which dominated the startup time.

Build:  .\.venv\Scripts\python.exe -m PyInstaller --noconfirm qualcoder_backend.spec
Output: dist/qualcoder-backend/  (copied into the Tauri resources by compile.ps1)

All paths are relative to this spec file so the same build runs on Windows,
Linux and macOS (CI matrix).
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# SPECPATH is the directory containing this spec file (PyInstaller does not
# define __file__ while executing specs).
HERE = os.path.abspath(SPECPATH)

datas = []
binaries = []
hiddenimports = []

# --- uvicorn: dynamic imports that break PyInstaller static analysis -------------
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
]

# --- qualcoder_api lazy imports (function-local, missed by static analysis) -----
hiddenimports += [
    "fitz",  # pymupdf alias
    "pymupdf",  # pymupdf 1.28 top-level package (native binary included via hooks)
    "docx2txt",
    "striprtf",
    "striprtf.striprtf",
    "ebooklib",
    "ebooklib.epub",
    "emoji",  # lazy in coding_service.py
]

# --- SQLAlchemy: async sqlite driver is resolved dynamically --------------------
hiddenimports += collect_submodules("sqlalchemy.dialects.sqlite")

# --- python-multipart (FastAPI form parsing) -------------------------------------
hiddenimports += ["multipart"]

# --- PyMuPDF data files (fonts, libs) --------------------------------------------
datas += collect_data_files("pymupdf")

# --- AI prompt library (markdown package data) ------------------------------------
datas += collect_data_files("qualcoder_api.ai_prompts")

# --- faster-whisper (lazy import; ctranslate2/onnxruntime native binaries) -------
hiddenimports += collect_submodules("faster_whisper")
hiddenimports += ["ctranslate2", "onnxruntime", "tokenizers", "huggingface_hub"]
datas += collect_data_files("tokenizers")
# silero_vad_v6.onnx lives in faster_whisper/assets — REQUIRED for VAD.
datas += collect_data_files("faster_whisper")

# --- Roadmap importers/AI (lazy function-local imports) -------------------------
hiddenimports += ["openpyxl", "pyreadstat", "pandas", "vaderSentiment"]
hiddenimports += collect_submodules("yt_dlp")
hiddenimports += collect_submodules("trafilatura")
hiddenimports += ["docx", "pptx"]
# Lexicons and document templates ship as package data.
datas += collect_data_files("vaderSentiment")
datas += collect_data_files("docx")
datas += collect_data_files("pptx")

a = Analysis(
    ["run_packaged.py"],
    pathex=[os.path.join(HERE, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(HERE, "runtime_hook.py")],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="qualcoder-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="qualcoder-backend",
)
