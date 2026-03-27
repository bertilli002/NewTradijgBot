from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.db import (
    Deposit, DepositStatus, TransactionLog, User,
    Withdrawal, WithdrawalStatus, TradeSignal, BotSetting,
    get_session, utcnow,
)


# ── Users ──────────────────────────────────────────────────────────────────────

async def get_or_create_user(telegram_id: int, username: str, full_name: str) -> User:
    async with get_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(telegram_id=telegram_id, username=username, full_name=full_name)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            user.username = username
            user.full_name = full_name
            user.last_seen = utcnow()
            await session.commit()
        return user

async def get_user_by_telegram_id(telegram_id: int) -> Optional[User]:
    async with get_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

async def get_all_users() -> list:
    async with get_session() as session:
        result = await session.execute(select(User).order_by(User.created_at.desc()))
        return list(result.scalars().all())


# ── Balance ────────────────────────────────────────────────────────────────────

async def adjust_balance(session: AsyncSession, user: User, delta: float, action: str, reference: str = None, note: str = None):
    before = user.balance
    user.balance = round(before + delta, 8)
    log = TransactionLog(
        user_id=user.id, action=action, amount=delta,
        balance_before=before, balance_after=user.balance,
        reference=reference, note=note,
    )
    session.add(log)


# ── Deposits ───────────────────────────────────────────────────────────────────

async def deposit_exists(tx_hash: str) -> bool:
    async with get_session() as session:
        result = await session.execute(select(Deposit).where(Deposit.tx_hash == tx_hash))
        return result.scalar_one_or_none() is not None

async def create_deposit(user_id: int, tx_hash: str, amount: float, token: str, network: str) -> Deposit:
    async with get_session() as session:
        dep = Deposit(user_id=user_id, tx_hash=tx_hash, amount=amount, token=token, network=network)
        session.add(dep)
        await session.commit()
        await session.refresh(dep)
        return dep


# ── Withdrawals ────────────────────────────────────────────────────────────────

async def create_withdrawal(user_id: int, amount: float, destination: str, network: str) -> Withdrawal:
    async with get_session() as session:
        user = await session.get(User, user_id)
        await adjust_balance(session, user, -amount, "withdrawal_hold", note=f"Withdrawal to {destination}")
        w = Withdrawal(user_id=user_id, amount=amount, destination=destination, network=network)
        session.add(w)
        await session.commit()
        await session.refresh(w)
        return w

async def get_pending_withdrawals() -> list:
    async with get_session() as session:
        result = await session.execute(
            select(Withdrawal).where(Withdrawal.status == WithdrawalStatus.PENDING).order_by(Withdrawal.requested_at)
        )
        return list(result.scalars().all())

async def get_withdrawal(withdrawal_id: int) -> Optional[Withdrawal]:
    async with get_session() as session:
        return await session.get(Withdrawal, withdrawal_id)

async def approve_withdrawal(withdrawal_id: int, admin_note: str = None) -> Withdrawal:
    async with get_session() as session:
        w = await session.get(Withdrawal, withdrawal_id)
        if w is None:
            raise ValueError("Withdrawal not found")
        w.status = WithdrawalStatus.APPROVED
        w.admin_note = admin_note
        w.resolved_at = utcnow()
        await session.commit()
        await session.refresh(w)
        return w

async def reject_withdrawal(withdrawal_id: int, admin_note: str = None) -> Withdrawal:
    async with get_session() as session:
        w = await session.get(Withdrawal, withdrawal_id)
        if w is None:
            raise ValueError("Withdrawal not found")
        w.status = WithdrawalStatus.REJECTED
        w.admin_note = admin_note
        w.resolved_at = utcnow()
        user = await session.get(User, w.user_id)
        await adjust_balance(session, user, w.amount, "withdrawal_refund", reference=str(withdrawal_id), note="Withdrawal rejected - refunded")
        await session.commit()
        await session.refresh(w)
        return w

async def get_user_withdrawals(user_id: int, limit: int = 10) -> list:
    async with get_session() as session:
        result = await session.execute(
            select(Withdrawal).where(Withdrawal.user_id == user_id).order_by(Withdrawal.requested_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


# ── Trade Signals ──────────────────────────────────────────────────────────────

async def create_trade_signal(signal_type: str, message: str, asset: str = None, direction: str = None,
                               entry_price: float = None, exit_price: float = None, pnl_pct: float = None,
                               broadcast_msg_id: int = None) -> TradeSignal:
    async with get_session() as session:
        ts = TradeSignal(signal_type=signal_type, message=message, asset=asset, direction=direction,
                         entry_price=entry_price, exit_price=exit_price, pnl_pct=pnl_pct, broadcast_msg_id=broadcast_msg_id)
        session.add(ts)
        await session.commit()
        await session.refresh(ts)
        return ts

async def get_recent_signals(limit: int = 20) -> list:
    async with get_session() as session:
        result = await session.execute(select(TradeSignal).order_by(TradeSignal.posted_at.desc()).limit(limit))
        return list(result.scalars().all())


# ── Transaction Logs ───────────────────────────────────────────────────────────

async def get_user_tx_log(user_id: int, limit: int = 15) -> list:
    async with get_session() as session:
        result = await session.execute(
            select(TransactionLog).where(TransactionLog.user_id == user_id).order_by(TransactionLog.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

async def get_recent_tx_logs(limit: int = 30) -> list:
    async with get_session() as session:
        result = await session.execute(select(TransactionLog).order_by(TransactionLog.created_at.desc()).limit(limit))
        return list(result.scalars().all())


# ── Settings ───────────────────────────────────────────────────────────────────

async def get_setting(key: str, default: str = "") -> str:
    async with get_session() as session:
        row = await session.get(BotSetting, key)
        return row.value if row else default

async def set_setting(key: str, value: str) -> None:
    async with get_session() as session:
        row = await session.get(BotSetting, key)
        if row is None:
            session.add(BotSetting(key=key, value=value))
        else:
            row.value = value
        await session.commit()


# ── Admin helpers ──────────────────────────────────────────────────────────────

async def admin_credit(telegram_id: int, amount: float, note: str = "") -> User:
    async with get_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")
        await adjust_balance(session, user, amount, "admin_credit", note=note or "Admin credit")
        await session.commit()
        await session.refresh(user)
        return user

async def admin_debit(telegram_id: int, amount: float, note: str = "") -> User:
    async with get_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")
        if user.balance < amount:
            raise ValueError("Insufficient balance")
        await adjust_balance(session, user, -amount, "admin_debit", note=note or "Admin debit")
        await session.commit()
        await session.refresh(user)
        return user
