import ssl
import sys
import imaplib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from infrastructure.imap_client import ImapClient

print("--- Testing Connection 1: srv10.cenuta.email:993 with Cenuta Password ---")
client1 = ImapClient()
ok1 = client1.connect(
    host="srv10.cenuta.email",
    port=993,
    use_ssl=True,
    username="muhasebe@ozmedmedikal.com.tr",
    password="Mh!Oz.1983"
)
print(f"Result for srv10.cenuta.email: {ok1}")
if ok1:
    print("Folders on Cenuta:", client1.list_folders()[:5])
    client1.disconnect()

print("\n--- Testing Connection 2: imap.yandex.com:993 with Yandex Password ---")
client2 = ImapClient()
ok2 = client2.connect(
    host="imap.yandex.com",
    port=993,
    use_ssl=True,
    username="muhasebe@ozmedmedikal.com.tr",
    password="Hazal.210820"
)
print(f"Result for imap.yandex.com: {ok2}")
if ok2:
    print("Folders on Yandex:", client2.list_folders()[:5])
    client2.disconnect()
