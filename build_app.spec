# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — IPMadalena Cultos para o Drive
Uso:
    pyinstaller build_app.spec
Saída em dist/IPMadalena/
"""

import os
import shutil
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

# ── yt-dlp: incluir executável do PATH ───────────────────────────────────────
_ytdlp = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
extra_binaries = []
if _ytdlp:
    extra_binaries.append((_ytdlp, "."))
else:
    print("AVISO: yt-dlp não encontrado no PATH. Instale com: pip install yt-dlp")

# ── ffmpeg: incluir do diretório local ───────────────────────────────────────
_ffmpeg = os.path.join("ffmpeg", "bin", "ffmpeg.exe")
if os.path.exists(_ffmpeg):
    extra_binaries.append((_ffmpeg, os.path.join("ffmpeg", "bin")))
else:
    print("AVISO: ffmpeg não encontrado em ffmpeg/bin/ffmpeg.exe")

# ── customtkinter: coleta assets (temas, imagens) ────────────────────────────
ctk_datas, ctk_bins, ctk_hidden = collect_all("customtkinter")

# ── tkcalendar/babel: dados de localização ───────────────────────────────────
babel_datas = collect_data_files("babel")

a = Analysis(
    ["app.py"],
    pathex=[os.path.abspath(".")],
    binaries=extra_binaries + ctk_bins,
    datas=ctk_datas + babel_datas + [
        ("setup_wizard.py", "."),
    ],
    hiddenimports=ctk_hidden + [
        "tkcalendar",
        "babel.numbers",
        "babel.dates",
        "plyer.platforms.win.notification",
        "plyer.platforms.win",
        "google.auth",
        "google.auth.transport",
        "google.oauth2",
        "google.oauth2.credentials",
        "google_auth_oauthlib",
        "google_auth_oauthlib.flow",
        "googleapiclient",
        "googleapiclient.discovery",
        "googleapiclient.http",
        "pkg_resources.py2_warn",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "pandas", "PIL"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="IPMadalena",
    debug=False,
    strip=False,
    upx=True,
    console=False,          # sem janela de terminal
    disable_windowed_traceback=False,
    icon="icon.ico" if os.path.exists("icon.ico") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="IPMadalena",
)
