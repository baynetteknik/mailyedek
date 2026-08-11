# DIA 3-Panel Pro Grid Architecture Standard

Bu doküman, Mail Archive System uygulamasında kullanılan **DIA 3-Panel Pro Grid Mimarisi** (DIA 3-Panel Workspace Architecture) standardını ve kullanım yönergelerini açıklar.

## 🌟 Mimari Özeti

DIA ERP ve kurumsal masaüstü sistemlerinden ilham alınan bu mimari, karmaşık veri listeleme, filtreleme ve işlem yapma ekranlarını 3 temel alanda yapılandırır:

```
+---------------------------------------------------------------------------------------+
|  Üst Başlık Barı (Title Bar & Panel Toggle Butonları)                                 |
+----------------------+----------------------------------------+-----------------------+
| SOL PANEL            | ORTA GRID PANELI                       | SAĞ İŞLEM PANELI     |
| (Filtreleme & Grup)  | (ProGridWidget / Custom DB Grid)      | (Aksiyonlar & Loglar) |
|                      |                                        |                       |
| - Kategori Ağacı     | - Üst Arama & Sütun Araç Çubuğu        | - Stat Kartları       |
| - Domain / Grup      | - Sütun Genişlik & Sıra Sürükleme      | - Hızlı İşlem Butonları|
| - Hızlı Arama        | - Sağ Tık Sütun Göster/Gizle (ProHeader)| - Canlı Akış Log Kutusu|
|                      | - Okunabilir 3-Satırlı Hücre Hücresi   |                       |
|                      | - Kalıcı Sütun Düzeni (Save State)     |                       |
+----------------------+----------------------------------------+-----------------------+
```

---

## 🛠️ Temel Bileşenler

### 1. `DiaThreePanelWorkspace` (`gui/templates/three_panel_workspace.py`)
Tüm ekranlarda 3 panelli yapıyı ve yeniden boyutlandırılabilir/gizlenebilir `QSplitter` kontrolünü sağlayan standart şablondur.

#### Örnek Kullanım:
```python
from gui.templates.three_panel_workspace import DiaThreePanelWorkspace

class MyModuleScreen(DiaThreePanelWorkspace):
    def __init__(self, parent=None):
        super().__init__(title="📧 E-Posta Yönetimi", parent=parent)
        self._setup_custom_ui()

    def _setup_custom_ui(self):
        # Sol Panele Eleman Ekleme
        self.left_inner_layout.addWidget(QLabel("Grup Filtresi"))

        # Orta Panele Grid Ekleme
        self.center_layout.addWidget(my_pro_grid_widget)

        # Sağ Panele İşlem Butonları Ekleme
        self.right_inner_layout.addWidget(btn_action)
```

---

### 2. `ProGridWidget` & `ProHeaderView` (`gui/widgets/pro_grid_widget.py`)
Gelişmiş tablolama ihtiyaçları için sağ-tık sütun gizleme/gösterme menüsü, sütun genişliği sürükleme, hızlı metin araması ve kalıcı görünüm kaydetme özelliklerini içeren veritabanı grid bileşenidir.

#### Öne Çıkan Özellikler:
- **`ProHeaderView`**: Sütun başlıklarına sağ tıklandığında görünürlüğü açıp kapatan bağlam menüsü (`👁️ Sütun Görünürlüğü`).
- **Movable Headers**: Sütun başlıklarının sürüklenerek yer değiştirilebilmesi (`setSectionsMovable(True)`).
- **Yüksek Okunabilirlik**:
  - `setDefaultSectionSize(78)` ile 3-satırlı hücre düzeni.
  - Satır 1: Başlık (`#0f172a`, `12.5px bold`) + Grup Rozeti.
  - Satır 2: E-Posta (`#334155`, `11px`).
  - Satır 3: İstatistikler (`#64748b`, `10.5px`).
- **Grid State Persistence**:
  - `_save_grid_state()`: Sütun genişlikleri ve gizli sütunları `AppSettings`'e kaydeder.
  - `_load_grid_state()`: Uygulama açılışında kaydedilen düzeni geri yükler.
  - `_reset_grid_state()`: Varsayılan sütun düzenine sıfırlar.

---

## 🎯 Uygulandığı Ekranlar
- **E-Posta Senkronizasyonu (`SyncPanel`)**: `account_table` 3-satırlı Account Details, `ProHeaderView`, sütun kaydetme/sıfırlama butonları ve 3 panelli alan ile güncellenmiştir.
