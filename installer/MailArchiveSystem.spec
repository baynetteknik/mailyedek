# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

block_cipher = None

repo_root = Path(r"c:\mail_home_benzeri\mail_archive_system")

datas = [
    (str(repo_root / "gui" / "resources"), "gui/resources"),
    (str(repo_root / "gui" / "templates"), "gui/templates"),
]

hiddenimports = [
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "sqlite3",
    "cryptography",
    "cryptography.fernet",
    "email",
    "email.mime",
    "email.header",
    "imaplib",
    "poplib",
    "smtplib",
    "socket",
    "ssl",
    "json",
    "csv",
    "logging",
    "threading",
    "core",
    "core.database",
    "core.mail_engine",
    "core.settings",
    "core.crypto_utils",
    "core.reporter",
    "core.performance",
    "domain",
    "domain.entities",
    "domain.interfaces",
    "domain.repositories",
    "infrastructure",
    "infrastructure.sqlite_repository",
    "infrastructure.imap_client",
    "infrastructure.network_analyzer",
    "usecases",
    "usecases.sync_usecase",
    "usecases.export_usecase",
    "usecases.restore_usecase",
    "plugins",
    "plugins.provider_registry",
]

a = Analysis(
    [str(repo_root / "gui" / "app.py")],
    pathex=[str(repo_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MailArchiveSystem',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MailArchiveSystem',
)
