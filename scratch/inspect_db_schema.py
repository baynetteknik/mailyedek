import sqlite3

conn = sqlite3.connect('data/mail_archive.db')
print("mail_metadata server_hosts:")
for r in conn.execute("SELECT server_host, COUNT(*) FROM mail_metadata GROUP BY server_host"):
    print(" ", r)

print("\nsync_state server_hosts:")
for r in conn.execute("SELECT server_host, COUNT(*) FROM sync_state GROUP BY server_host"):
    print(" ", r)

print("\nAccounts with their default/active hosts:")
for r in conn.execute("SELECT id, email, imap_host FROM accounts"):
    print(" ", r)
