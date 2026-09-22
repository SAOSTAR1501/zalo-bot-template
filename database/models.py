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
