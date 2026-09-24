import sqlite3

conn = sqlite3.connect("/home/zalo-bot/data/zalo_bot.db")
c = conn.cursor()

print("=== TABLES ===")
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
for t in c.fetchall():
    print(t[0])

print("\n=== Recent messages for zgr-954e8895bcf555ab0ce4 ===")
c.execute("SELECT id, created_at, event_type, substr(message,1,100), substr(reply,1,100) FROM message_logs WHERE user_id = 'zgr-954e8895bcf555ab0ce4' ORDER BY id DESC LIMIT 10")
for row in c.fetchall():
    print(f"ID: {row[0]} | {row[1]} | {row[2]}")
    print(f"  MSG: {row[3]}")
    print(f"  REPLY: {row[4]}")
    print()

print("=== Rolling summary for zgr-954e8895bcf555ab0ce4 ===")
c.execute("SELECT summary, last_summarized_id, updated_at FROM group_context_summaries WHERE chat_id = 'zgr-954e8895bcf555ab0ce4'")
row = c.fetchone()
if row:
    print(f"SUMMARY (last id {row[1]}, updated {row[2]}):")
    print(row[0][:500])
else:
    print("(no summary)")

conn.close()
