from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class MessageLog(Base):
    __tablename__ = "message_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)  # chat_id (group or private)
    message = Column(Text, nullable=False)
    reply = Column(Text, nullable=True)
    event_type = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class GroupKnowledge(Base):
    __tablename__ = "group_knowledge"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, nullable=False, index=True)
    topic = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    created_by = Column(String, nullable=True)
    is_auto = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class GroupContextSummary(Base):
    """
    Episodic memory: stores the rolling condensed summary of a group/chat.
    Saves 80%+ tokens by replacing dozens of raw messages with a concise 50-token synopsis.
    """
    __tablename__ = "group_context_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, nullable=False, unique=True, index=True)
    summary = Column(Text, nullable=False, default="")
    last_summarized_id = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)


class SemanticMemory(Base):
    """
    Semantic Long-Term Memory (RAG + Vector Embedding):
    Stores key facts, decisions, rules, and knowledge with 384-dimensional dense embeddings.
    Enables instant semantic retrieval of relevant facts without token bloat.
    """
    __tablename__ = "semantic_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, nullable=False, index=True)
    content = Column(Text, nullable=False)
    category = Column(String, default="fact", index=True)  # fact | decision | rule | task | knowledge
    embedding_json = Column(Text, nullable=False)  # JSON-serialized float array
    source_user = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserQuota(Base):
    """
    Rate limiting and access control for 1-1 private chats.
    - Free tier: 10 messages
    - Over quota: warning up to 3 times, then silent drop
    - Admin whitelist: unlimited
    """
    __tablename__ = "user_quotas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=True)
    message_count = Column(Integer, default=0)
    max_quota = Column(Integer, default=10)
    is_approved = Column(Boolean, default=False)
    spam_warnings_sent = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


