"""
build_setup.py — Master script to build standalone executable setup package.

Generates:
1. Portable App Directory: installer/dist/MailArchiveSystem/
2. One-Click Setup Script: installer/dist/MailArchiveSystem/Kurulum_Yap.bat
3. Distribution Zip: installer/MailArchiveSystem_v1.0_Kurulum_Paketi.zip
"""

import sys
import os
import shutil
import zipfile
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

installer_dir = Path(__file__).parent.resolve()
repo_root = installer_dir.parent.resolve()

if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from core.version import get_version

app_version = get_version()
dist_dir = installer_dir / "dist"
build_dir = installer_dir / "build"
spec_file = installer_dir / "MailArchiveSystem.spec"

print("==================================================")
print(f"BUILDING MAIL ARCHIVE SYSTEM WINDOWS SETUP BUNDLE v{app_version}")
print("==================================================")
print(f"Repo Root: {repo_root}")
print(f"Installer Dir: {installer_dir}")

# 1. Clean previous dist folder
if dist_dir.exists():
    print(f"Cleaning directory: {dist_dir}")
    shutil.rmtree(dist_dir, ignore_errors=True)

# 2. Run PyInstaller
cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--distpath", str(dist_dir),
    "--workpath", str(build_dir),
    str(spec_file)
]

print("\nRunning PyInstaller build command...")
res = subprocess.run(cmd, cwd=repo_root)
if res.returncode != 0:
    print(f"\n❌ PyInstaller build failed with exit code: {res.returncode}")
    sys.exit(res.returncode)

target_bundle = dist_dir / "MailArchiveSystem"
if not target_bundle.exists():
    print(f"\n❌ Target bundle directory not found: {target_bundle}")
    sys.exit(1)

# 3. Create default data directory inside bundle
data_dir = target_bundle / "data"
data_dir.mkdir(parents=True, exist_ok=True)

# Copy KURULUM_REHBERI.txt into target bundle
guide_source = installer_dir / "KURULUM_REHBERI.txt"
if guide_source.exists():
    shutil.copy2(guide_source, target_bundle / "KURULUM_REHBERI.txt")

# 4. Create one-click installer batch script inside target_bundle
setup_bat_content = f"""@echo off
chcp 65001 > NUL
title Mail Archive System v{app_version} - Otomatik Kurulum Sihirbazı
color 0A
echo ======================================================================
echo           MAIL ARCHIVE SYSTEM v{app_version} OTOMATİK KURULUM SİHİRBAZI
echo ======================================================================
echo.
echo Uygulama bilgisayarınıza kuruluyor, lütfen bekleyin...
echo.

set TARGET_DIR=%LocalAppData%\\MailArchiveSystem
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"

echo [1/3] Dosyalar kopyalanıyor: "%TARGET_DIR%" ...
xcopy /E /Y /I "%~dp0*" "%TARGET_DIR%\\" > NUL

echo [2/3] Masaüstü Kısayolu Oluşturuluyor...
set SCRIPT="%TEMP%\\CreateShortcut.vbs"
echo Set oWS = WScript.CreateObject("WScript.Shell") > %SCRIPT%
echo sLinkFile = oWS.SpecialFolders("Desktop") ^& "\\Mail Archive System.lnk" >> %SCRIPT%
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> %SCRIPT%
echo oLink.TargetPath = "%TARGET_DIR%\\MailArchiveSystem.exe" >> %SCRIPT%
echo oLink.WorkingDirectory = "%TARGET_DIR%" >> %SCRIPT%
echo oLink.Description = "Mail Archive System v{app_version}" >> %SCRIPT%
echo oLink.Save >> %SCRIPT%
cscript //nologo %SCRIPT%
del %SCRIPT%

echo [3/3] Başlat Menüsü Kısayolu Oluşturuluyor...
set START_DIR=%AppData%\\Microsoft\\Windows\\Start Menu\\Programs\\Mail Archive System
if not exist "%START_DIR%" mkdir "%START_DIR%"
set SCRIPT2="%TEMP%\\CreateStartShortcut.vbs"
echo Set oWS = WScript.CreateObject("WScript.Shell") > %SCRIPT2%
echo sLinkFile = "%START_DIR%\\Mail Archive System.lnk" >> %SCRIPT2%
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> %SCRIPT2%
echo oLink.TargetPath = "%TARGET_DIR%\\MailArchiveSystem.exe" >> %SCRIPT2%
echo oLink.WorkingDirectory = "%TARGET_DIR%" >> %SCRIPT2%
echo oLink.Save >> %SCRIPT2%
cscript //nologo %SCRIPT2%
del %SCRIPT2%

echo.
echo ======================================================================
echo   ✅ KURULUM BAŞARIYLA TAMAMLANDI!
echo   Masaüstünüze ve Başlat Menünüze "Mail Archive System" eklendi.
echo ======================================================================
echo.
set /p START_NOW="Uygulamayı şimdi başlatmak ister misiniz? (E/H): "
if /i "%START_NOW%"=="E" (
    start "" "%TARGET_DIR%\\MailArchiveSystem.exe"
)
exit
"""

setup_bat_file = target_bundle / "Kurulum_Yap.bat"
with open(setup_bat_file, "w", encoding="utf-8-sig") as f:
    f.write(setup_bat_content)

print(f"Created setup installer script: {setup_bat_file}")

# 5. Compress into Setup Zip Archive
zip_filename = installer_dir / f"MailArchiveSystem_v{app_version}_Kurulum_Paketi.zip"
print(f"\nCompressing bundle into zip package: {zip_filename}")
with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(target_bundle):
        for file in files:
            full_path = Path(root) / file
            rel_path = full_path.relative_to(dist_dir)
            zf.write(full_path, rel_path)

print("==================================================")
print(f"✅ BUILD COMPLETE (v{app_version})!")
print(f"Standalone Executable Folder: {target_bundle / 'MailArchiveSystem.exe'}")
print(f"Kurulum Paketi (Zip): {zip_filename}")
print("==================================================")
