import json
import logging
import threading
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import numpy as np
from database.connection import SessionLocal
from database.models import SemanticMemory

logger = logging.getLogger(__name__)

_EMBED_MODEL = None
_MODEL_LOCK = threading.Lock()


def get_embedding_model():
    """
    Lazy loads the FastEmbed multilingual ONNX model singleton.
    """
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        with _MODEL_LOCK:
            if _EMBED_MODEL is None:
                try:
                    from fastembed import TextEmbedding
                    logger.info("Initializing FastEmbed multilingual embedding model...")
                    _EMBED_MODEL = TextEmbedding(
                        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
                    )
                    logger.info("FastEmbed multilingual embedding model ready.")
                except Exception as e:
                    logger.error(f"Failed to load FastEmbed model: {e}")
                    _EMBED_MODEL = None
    return _EMBED_MODEL


class SemanticMemoryService:
    """
    Semantic Long-Term Memory (RAG + Vector Embedding) Service.
    Enables permanent factual recall with zero token bloat.
    """

    def compute_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generates 384-dimensional dense vector embedding.
        """
        model = get_embedding_model()
        if not model:
            return None
        try:
            cleaned = text.strip()
            if not cleaned:
                return None
            embeddings = list(model.embed([cleaned]))
            if embeddings and len(embeddings) > 0:
                return embeddings[0].tolist()
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
        return None

    def add_memory(
        self,
        chat_id: str,
        content: str,
        category: str = "fact",
        source_user: str = ""
    ) -> bool:
        """
        Embeds and stores a piece of knowledge into persistent Semantic Memory.
        """
        cleaned_content = content.strip()
        if not cleaned_content or len(cleaned_content) < 5:
            return False

        embedding = self.compute_embedding(cleaned_content)
        if embedding is None:
            logger.warning(f"Could not compute embedding for memory: {cleaned_content[:50]}")
            return False

        db = SessionLocal()
        try:
            mem = SemanticMemory(
                chat_id=str(chat_id),
                content=cleaned_content,
                category=category,
                embedding_json=json.dumps(embedding),
                source_user=str(source_user) if source_user else None,
                created_at=datetime.utcnow()
            )
            db.add(mem)
            db.commit()
            logger.info(f"Saved SemanticMemory ({category}) for chat {chat_id}: {cleaned_content[:80]}")
            return True
        except Exception as e:
            logger.error(f"Error storing semantic memory: {e}")
            return False
        finally:
            db.close()

    def search_relevant_memories(
        self,
        chat_id: str,
        query: str,
        top_k: int = 3,
        min_similarity: float = 0.35
    ) -> List[Dict[str, str]]:
        """
        Performs vector cosine similarity search across chat's semantic memories.
        """
        query_cleaned = query.strip()
        if not query_cleaned or len(query_cleaned) < 3:
            return []

        query_vec = self.compute_embedding(query_cleaned)
        if query_vec is None:
            return []

        db = SessionLocal()
        try:
            records = (
                db.query(SemanticMemory)
                .filter(SemanticMemory.chat_id == str(chat_id))
                .all()
            )
            if not records:
                return []

            q_arr = np.array(query_vec, dtype=np.float32)
            q_norm = np.linalg.norm(q_arr)
            if q_norm == 0:
                return []

            scored_items = []
            for r in records:
                try:
                    vec = np.array(json.loads(r.embedding_json), dtype=np.float32)
                    v_norm = np.linalg.norm(vec)
                    if v_norm == 0:
                        continue
                    sim = float(np.dot(q_arr, vec) / (q_norm * v_norm))
                    if sim >= min_similarity:
                        scored_items.append((sim, r))
                except Exception:
                    continue

            # Sort descending by cosine similarity
            scored_items.sort(key=lambda x: x[0], reverse=True)
            top_results = scored_items[:top_k]

            results = []
            for sim, item in top_results:
                results.append({
                    "content": item.content,
                    "category": item.category,
                    "source": item.source_user or "Hệ thống",
                    "similarity": round(sim, 3)
                })

            if results:
                logger.info(f"Retrieved {len(results)} relevant semantic memories for query '{query[:40]}' in chat {chat_id}")
            return results
        except Exception as e:
            logger.error(f"Error querying semantic memories: {e}")
            return []
        finally:
            db.close()

    def format_memories_for_prompt(self, memories: List[Dict[str, str]]) -> str:
        """
        Formats retrieved semantic memories into concise bullet points for LLM injection.
        """
        if not memories:
            return ""
        lines = []
        for m in memories:
            lines.append(f"• [{m['category'].upper()}] {m['content']}")
        return "\n".join(lines)

    def async_auto_index_fact(self, chat_id: str, content: str, category: str = "fact", source_user: str = ""):
        """
        Background task to index facts without blocking HTTP response.
        """
        t = threading.Thread(
            target=self.add_memory,
            args=(chat_id, content, category, source_user),
            daemon=True
        )
        t.start()


semantic_memory_service = SemanticMemoryService()
