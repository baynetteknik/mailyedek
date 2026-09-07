import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))
from core.settings import AppSettings

settings = AppSettings()
print(f"settings.key_file_path(): {settings.key_file_path()} (exists: {settings.key_file_path().exists()})")

paths = [
    Path("data/key.key"),
    Path("E:/mailyedek/key.key"),
    Path("E:/mailyedek/mail_archive.key"),
]

for p in paths:
    if p.exists():
        print(f"Found key at {p}, size: {p.stat().st_size} bytes")
    else:
        print(f"Key not found at {p}")
