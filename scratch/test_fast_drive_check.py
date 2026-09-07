import sys
sys.path.insert(0, '.')
import time
import os
import ctypes
from pathlib import Path

def is_drive_mounted(path_str: str) -> bool:
    if not path_str:
        return True
    try:
        drive, tail = os.path.splitdrive(path_str)
        if drive and sys.platform.startswith("win"):
            drive_letter = drive.strip(":").upper()
            if len(drive_letter) == 1 and 'A' <= drive_letter <= 'Z':
                bitmask = ctypes.windll.kernel32.GetLogicalDrives()
                drive_index = ord(drive_letter) - ord('A')
                if not (bitmask & (1 << drive_index)):
                    # Drive is physically/logically NOT mounted
                    return False
        # If drive is mounted, check if directory exists
        return os.path.exists(path_str)
    except Exception:
        return False

# Test performance
t0 = time.perf_counter()
print("E:\\mailyedek mounted?", is_drive_mounted("E:\\mailyedek"))
print(f"Elapsed: {(time.perf_counter() - t0)*1000:.3f} ms")

t0 = time.perf_counter()
print("Z:\\missing mounted?", is_drive_mounted("Z:\\missing"))
print(f"Elapsed: {(time.perf_counter() - t0)*1000:.3f} ms")
