# Çoklu Sunucu Profili Yönetimi ve Senkronizasyon / Geri Yükleme Seçimi

## 1. Senkronizasyon Esnasında (Sunucudan E-Posta Çekilirken)
Birden fazla sunucu profili olan hesaplarda (Örn: `muhasebe@ozmedmedikal.com.tr`):
1. **Görsel Rozet Göstergesi (Sync Grid Kartı)**:
   - Senkronizasyon tablosunda her hesabın kartında şu an hangi sunucunun aktif olduğu ve kaç sunucu tanımlandığı yeşil rozet ile gösterilir:
     `🔌 Aktif Sunucu: Cenuta (srv10.cenuta.email) [2 Sunucu Tanımlı]`
2. **Otomatik Sunucu Seçim Penceresi (`SelectSyncServerDialog`)**:
   - `▶` Butonuna basıldığında veya "Seçili Hesapları Senkronize Et" / "Tümünü Senkronize Et" çalıştırıldığında sistem otomatik olarak ekrana modal pencere açar:
     > **"Bu hesaba ait birden fazla sunucu profili bulunmaktadır. Hangi sunucudan senkronize olmak istiyorsunuz?"**
     > - 🔘 Yandex Mail (`imap.yandex.com:993`)
     > - 🔘 Cenuta Mail (`srv10.cenuta.email:993`)
     > - `[ ] Seçilen sunucuyu bu hesap için varsayılan (aktif) sunucu yap`
   - Seçilen sunucu hangisi ise indirme işlemi anında o sunucudan başlatılır.

---

## 2. Geri Yükleme / Gönderim Esnasında (Sunucuya E-Posta Gönderilirken)
- **Geri Yükleme Merkezi (`RestorePanel`)**:
  - Yedekten IMAP sunucusuna e-posta aktarılırken (`target_imap = True`), aktarım doğrudan o hesabın **Aktif / Varsayılan** olarak seçilmiş olan sunucusuna yapılır.
- **Hesaplar Ekranı (`AccountPanel`)**:
  - Hesap satırına **Sağ Tıklandığında** -> `🔌 Aktif Sunucuyu Seç` alt menüsünden tek tıkla aktif sunucu değiştirilebilir (`★ Yandex` <-> `★ Cenuta`).
  - `✏️ Hesabı Düzenle` ekranından istenilen sunucu profili seçilip `[⭐ Varsayılan (Aktif) Yap]` butonuyla da kalıcı olarak değiştirilebilir.
