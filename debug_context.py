import sys
sys.path.insert(0, "/home/zalo-bot")

from services.context_service import context_service
from services.semantic_memory_service import semantic_memory_service

chat_id = "3f6de3efa9a340fd19b2"
summary, history = context_service.get_optimized_context(chat_id, max_hours=12, recent_count=10)
print("=== ROLLING SUMMARY ===")
print(summary if summary else "(empty)")
print("\n=== HISTORY (last 10) ===")
for msg in history:
    role = msg.get("role", "?")
    content = msg.get("content", "")[:120]
    print(f"{role}: {content}")
print("\n=== SEMANTIC MEMORY (top 3) ===")
mems = semantic_memory_service.search_relevant_memories(
    chat_id=chat_id,
    query="admin sao dai ca context",
    top_k=3,
    min_similarity=0.2
)
for m in mems:
    print(f"- {m[:200]}")
