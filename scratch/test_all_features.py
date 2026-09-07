"""
test_all_features.py — Verification script for:
1. Domain filtering & sidebar selection preservation
2. SearchPanel with ToyaDbGrid, per-column filters & pagination
3. VHDX backup and streaming decompression restore
"""

import sys
import os
import gzip
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure Qt platform is offscreen for headless verification
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from core.settings import AppSettings
from core.mail_engine import MailEngine
from gui.widgets.account_group_sidebar_widget import AccountGroupSidebarWidget
from gui.widgets.search_panel import SearchPanel
from gui.widgets.toya_grid_widget import ToyaDbGrid, ToyaPaginationBar
from infrastructure.vhdx_backup_client import VhdxBackupClient


def run_tests():
    app = QApplication.instance() or QApplication(sys.argv)
    settings = AppSettings()
    engine = MailEngine(settings.data_path() / "metadata.db", settings=settings)

    print("\n--- 1. Testing AccountGroupSidebarWidget Domain Selection ---")
    sidebar = AccountGroupSidebarWidget()
    test_domains = {
        "4umedical.com.tr": {"is_active": True, "count": 6},
        "acsgroup.com.tr": {"is_active": True, "count": 5},
        "baynetbilisim.com.tr": {"is_active": True, "count": 1},
        "keisharp.com.tr": {"is_active": True, "count": 2},
        "ohmteknik.com": {"is_active": True, "count": 1},
        "ozmedmedikal.com.tr": {"is_active": True, "count": 4},
        "seges.com.tr": {"is_active": True, "count": 1},
    }
    sidebar.populate_domains(test_domains, total_accounts_count=20)
    assert sidebar.lbl_count_badge.text() == "7 Domain", f"Expected '7 Domain', got {sidebar.lbl_count_badge.text()}"
    assert sidebar.group_list.count() == 8, f"Expected 8 items (1 All + 7 Domains), got {sidebar.group_list.count()}"

    # Select a specific domain
    sidebar.select_group("baynetbilisim.com.tr")
    assert sidebar.get_selected_domain() == "baynetbilisim.com.tr"

    # Re-populate (as on background refresh) and ensure selection is preserved!
    sidebar.populate_domains(test_domains, total_accounts_count=20)
    assert sidebar.get_selected_domain() == "baynetbilisim.com.tr", "Domain selection was lost during populate_domains!"
    print("✅ AccountGroupSidebarWidget domain selection & preservation verified.")

    print("\n--- 2. Testing SearchPanel with ToyaDbGrid & Pagination ---")
    search_panel = SearchPanel(engine)
    assert isinstance(search_panel.db_grid, ToyaDbGrid)
    assert not search_panel.db_grid.pagination_bar.isHidden()

    # Simulate search results
    mock_results = []
    for i in range(135):
        mock_results.append({
            "id": i + 1,
            "account_id": 1,
            "date": f"2026-09-0{i%9+1} 10:00:00",
            "sender": f"user{i}@example.com",
            "recipients": f"dest{i}@example.com",
            "subject": f"Fatura Raporu {i}" if i % 2 == 0 else f"Normal Bildirim {i}",
            "folder": "INBOX",
            "size_bytes": 1024 * (i + 10),
            "has_attachments": 1 if i % 3 == 0 else 0
        })

    search_panel._on_search_results_ready(mock_results)
    assert search_panel.db_grid.pagination_bar.total_pages() == 3  # 135 items with default 50 per page -> 3 pages
    visible_cnt = sum(1 for r in range(search_panel.table.rowCount()) if not search_panel.table.isRowHidden(r))
    assert visible_cnt == 50  # First page displays 50 visible rows

    # Navigate to page 2
    search_panel.db_grid.pagination_bar._go_next()
    assert search_panel.db_grid.pagination_bar.current_page() == 2
    visible_cnt_p2 = sum(1 for r in range(search_panel.table.rowCount()) if not search_panel.table.isRowHidden(r))
    assert visible_cnt_p2 == 50  # Second page displays 50 visible rows

    # Navigate to last page (page 3)
    search_panel.db_grid.pagination_bar._go_last()
    assert search_panel.db_grid.pagination_bar.current_page() == 3
    visible_cnt_p3 = sum(1 for r in range(search_panel.table.rowCount()) if not search_panel.table.isRowHidden(r))
    assert visible_cnt_p3 == 35  # Third page displays remaining 35 rows (135 - 100)

    # Column filter test: Filter column 4 (Subject) with "fatura"
    search_panel.db_grid.filter_bar._on_text_changed(4, "fatura")
    assert search_panel.db_grid.pagination_bar.total_pages() == 2  # 68 items -> 2 pages
    visible_filter_p1 = sum(1 for r in range(search_panel.table.rowCount()) if not search_panel.table.isRowHidden(r))
    assert visible_filter_p1 == 50
    print("✅ SearchPanel ToyaDbGrid, Column Filters & Pagination verified.")

    print("\n--- 3. Testing VHDX Backup & Streaming Restore ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        source_raw = tmp_path / "vm_disk_original.vhdx"
        test_payload = b"VHDX_RAW_DISK_STREAM_TEST_BLOCK_DATA_1234567890" * (1024 * 64)  # ~3 MB
        source_raw.write_bytes(test_payload)

        # 3.1 Compress to .vhdx.gz
        compressed_vhdx = tmp_path / "vm_disk_backup.vhdx.gz"
        with open(source_raw, "rb") as f_in, gzip.open(compressed_vhdx, "wb") as f_out:
            f_out.write(f_in.read())

        assert compressed_vhdx.exists()

        # 3.2 Restore with VhdxBackupClient.restore_vhdx_file
        client = VhdxBackupClient()
        restore_dest_dir = tmp_path / "restored_output"

        progress_msgs = []
        def progress_cb(msg, pct, speed):
            progress_msgs.append((msg, pct, speed))

        res = client.restore_vhdx_file(
            source_backup_path=str(compressed_vhdx),
            target_dest_path=str(restore_dest_dir),
            mode="custom",
            progress_callback=progress_cb
        )

        assert res["status"] == "SUCCESS"
        restored_file = Path(res["target_file"])
        assert restored_file.exists()
        assert restored_file.suffix == ".vhdx"
        assert not restored_file.name.endswith(".gz")  # Must be pure .vhdx!
        assert restored_file.read_bytes() == test_payload  # Binary integrity verified!
        print(f"✅ VHDX streaming decompression restore verified (Restored: {restored_file.name}, Size: {len(restored_file.read_bytes()):,} bytes).")

    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! 🎉\n")

if __name__ == "__main__":
    run_tests()
