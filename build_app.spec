# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec -- IPMadalena Cultos para o Drive (PyQt6 + QWebEngine)
Uso:
    pyinstaller build_app.spec
Saida em dist/IPMadalena/

Requisitos antes de rodar:
    pip install pyinstaller pyinstaller-hooks-contrib
    (pyinstaller-hooks-contrib fornece os hooks para PyQt6/WebEngine)
"""

import os
import shutil
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

# ── yt-dlp: preferir standalone local (baixado por build_installer.bat) ──────
_ytdlp_local = os.path.join(".", "yt-dlp.exe")
if os.path.exists(_ytdlp_local):
    _ytdlp = _ytdlp_local
else:
    _ytdlp = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")

extra_binaries = []
if _ytdlp:
    extra_binaries.append((_ytdlp, "."))
    print(f"INFO: bundling yt-dlp de: {_ytdlp}")
else:
    print("AVISO: yt-dlp nao encontrado. Execute build_installer.bat para baixar o standalone.")

# ── ffmpeg: incluir do diretorio local ───────────────────────────────────────
_ffmpeg = os.path.join("ffmpeg", "bin", "ffmpeg.exe")
if os.path.exists(_ffmpeg):
    extra_binaries.append((_ffmpeg, os.path.join("ffmpeg", "bin")))
else:
    print("AVISO: ffmpeg nao encontrado em ffmpeg/bin/ffmpeg.exe")

# ── PyQt6 WebEngine: collect_all aciona os hooks do pyinstaller-hooks-contrib ─
# Inclui QtWebEngineProcess.exe, plugins Qt, locales, resources, DLLs ICU.
qt6_we_d,  qt6_we_b,  qt6_we_h  = collect_all("PyQt6.QtWebEngineWidgets")
qt6_wec_d, qt6_wec_b, qt6_wec_h = collect_all("PyQt6.QtWebEngineCore")

# ── Modulos adicionais PyQt6 usados diretamente ───────────────────────────────
# Os hooks do pyinstaller-hooks-contrib ja cuidam dos binarios Qt6; aqui
# apenas garantimos que os hidden imports sejam reconhecidos pelo analisador.
_qt6_hidden = [
    "PyQt6",
    "PyQt6.sip",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtNetwork",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    # player_subprocess_qt e importado condicionalmente via --player-mode-qt
    "player_subprocess_qt",
]

a = Analysis(
    ["app.py"],
    pathex=[os.path.abspath(".")],
    binaries=extra_binaries + qt6_we_b + qt6_wec_b,
    datas=qt6_we_d + qt6_wec_d + [
        # Modulos Python locais (importados condicionalmente)
        ("setup_wizard.py",        "."),
        ("player_window_qt.py",    "."),
        ("player_subprocess_qt.py", "."),
        # Icone da janela / barra de tarefas
        ("icon.ico", "."),
    ],
    hiddenimports=qt6_we_h + qt6_wec_h + _qt6_hidden + [
        # Google APIs
        "google.auth",
        "google.auth.transport",
        "google.auth.transport.requests",
        "google.oauth2",
        "google.oauth2.credentials",
        "google_auth_oauthlib",
        "google_auth_oauthlib.flow",
        "googleapiclient",
        "googleapiclient.discovery",
        "googleapiclient.http",
        # Notificacao desktop
        "plyer.platforms.win.notification",
        "plyer.platforms.win",
        # Compatibilidade pkg_resources
        "pkg_resources.py2_warn",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # UI legada (substituida por PyQt6)
        "customtkinter",
        "tkcalendar",
        "babel",
        "webview",          # pywebview
        # Nao usado
        "matplotlib",
        "numpy",
        "pandas",
        "PIL",
    ],
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
    upx_exclude=[
        # Nao comprimir DLLs Qt6/WebEngine — UPX pode corrompê-las
        "Qt6*.dll",
        "QtWebEngine*.dll",
        "QtWebEngineProcess.exe",
        "*.pak",
    ],
    name="IPMadalena",
)
