from __future__ import annotations
import enum
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship
import os

# Force SQLite - reliable, no greenlet, works everywhere
DATABASE_URL = "sqlite+aiosqlite:///./bot_data.db"

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

def utcnow():
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(64), nullable=True)
    full_name = Column(String(128), nullable=True)
    balance = Column(Float, default=0.0, nullable=False)
    is_banned = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    last_seen = Column(DateTime, default=utcnow)
    deposits = relationship("Deposit", back_populates="user", lazy="selectin")
    withdrawals = relationship("Withdrawal", back_populates="user", lazy="selectin")
    tx_logs = relationship("TransactionLog", back_populates="user", lazy="selectin")

class DepositStatus(str, enum.Enum):
    DETECTED = "detected"
    CREDITED = "credited"

class Deposit(Base):
    __tablename__ = "deposits"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    tx_hash = Column(String(128), unique=True, nullable=False)
    amount = Column(Float, nullable=False)
    token = Column(String(16), default="USDC")
    network = Column(String(16), default="ethereum")
    status = Column(SAEnum(DepositStatus), default=DepositStatus.DETECTED)
    created_at = Column(DateTime, default=utcnow)
    credited_at = Column(DateTime, nullable=True)
    user = relationship("User", back_populates="deposits")

class WithdrawalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class Withdrawal(Base):
    __tablename__ = "withdrawals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    destination = Column(String(128), nullable=False)
    network = Column(String(16), default="ethereum")
    status = Column(SAEnum(WithdrawalStatus), default=WithdrawalStatus.PENDING)
    admin_note = Column(Text, nullable=True)
    requested_at = Column(DateTime, default=utcnow)
    resolved_at = Column(DateTime, nullable=True)
    user = relationship("User", back_populates="withdrawals")

class TradeSignal(Base):
    __tablename__ = "trade_signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_type = Column(String(32), nullable=False)
    asset = Column(String(32), nullable=True)
    direction = Column(String(8), nullable=True)
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    message = Column(Text, nullable=False)
    broadcast_msg_id = Column(BigInteger, nullable=True)
    posted_at = Column(DateTime, default=utcnow)

class TransactionLog(Base):
    __tablename__ = "transaction_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(32), nullable=False)
    amount = Column(Float, nullable=False)
    balance_before = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    reference = Column(String(256), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    user = relationship("User", back_populates="tx_logs")

class BotSetting(Base):
    __tablename__ = "bot_settings"
    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

def get_session() -> AsyncSession:
    return AsyncSessionLocal()
