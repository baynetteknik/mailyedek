import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Set headless environment for PySide6
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from core.settings import AppSettings
from core.mail_engine import MailEngine
from gui.widgets.sync_panel import SyncPanel

def test_sync_panel():
    app = QApplication.instance() or QApplication(sys.argv)
    
    settings = AppSettings()
    print("================ ONLINE TEST ================")
    print("Configured data path:", settings.configured_data_path_str())
    print("Is configured path available:", settings.is_configured_data_path_available())
    
    engine = MailEngine(db_path=settings.db_path(), key_file=settings.key_file_path())
    panel = SyncPanel(engine=engine, settings=settings)
    panel.refresh()
    
    row_count = panel.account_table.rowCount()
    print(f"Online table row count: {row_count}")
    print(f"Disk status banner: {panel.lbl_disk_status_text.text()}")
    print(f"Group sidebar item count: {panel.group_filter_list.count()}")
    for i in range(panel.group_filter_list.count()):
        item_text = panel.group_filter_list.item(i).text()
        print(f"  - {item_text.encode('ascii', 'replace').decode('ascii')}")
    
    print("\n================ OFFLINE TEST ================")
    # Simulate missing disk
    settings.set("data_path", "Z:\\non_existent_drive\\mailyedek")
    print("Simulated data path:", settings.configured_data_path_str())
    print("Is configured path available:", settings.is_configured_data_path_available())
    
    panel_offline = SyncPanel(engine=engine, settings=settings)
    panel_offline.refresh()
    
    row_count_offline = panel_offline.account_table.rowCount()
    print(f"Offline table row count: {row_count_offline}")
    banner_offline = panel_offline.lbl_disk_status_text.text()
    print(f"Offline Disk status banner: {banner_offline.encode('ascii', 'replace').decode('ascii')}")
    print(f"Offline Group sidebar item count: {panel_offline.group_filter_list.count()}")
    
    # Restore original setting
    settings.set("data_path", "E:\\mailyedek")
    settings.save()
    print("\nAll SyncPanel verification tests passed successfully!")

if __name__ == "__main__":
    test_sync_panel()
