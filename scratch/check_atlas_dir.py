import sys
import os
from pathlib import Path

atlas_dir = Path("E:/mailyedek/atlas")
print(f"Atlas dir exists: {atlas_dir.exists()}")
if atlas_dir.exists():
    items = list(atlas_dir.iterdir())
    print(f"Direct items in E:/mailyedek/atlas ({len(items)}):")
    for it in items[:20]:
        print(" -", it.name, "is_dir:", it.is_dir())
