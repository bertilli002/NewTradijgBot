from __future__ import annotations
import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config.settings import ADMIN_IDS, BROADCAST_CHAT_ID, runtime
from database.crud import (
    admin_credit, admin_debit, approve_withdrawal, create_trade_signal,
    get_all_users, get_pending_withdrawals, get_recent_signals,
    get_recent_tx_logs, get_setting, get_withdrawal, reject_withdrawal,
    set_setting,
)

logger = logging.getLogger(__name__)


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def admin_only(func):
    async def wrapper(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Admin only.")
            return
        return await func(self, update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper


class AdminHandlers:

    @admin_only
    async def cmd_admin_panel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        state = "🟢 Active" if runtime["signals_active"] else "🔴 Paused"
        users = await get_all_users()
        pending = await get_pending_withdrawals()
        addr = await get_setting("master_wallet_address", "Not set")
        await update.message.reply_text(
            f"🛠 *Admin Panel*\n\n"
            f"👥 Users: `{len(users)}`\n"
            f"⏳ Pending withdrawals: `{len(pending)}`\n"
            f"📡 Signals: {state}\n"
            f"🏦 Deposit address: `{addr}`\n\n"
            f"*Commands:*\n"
            f"/users — List users\n"
            f"/pending — Pending withdrawals\n"
            f"/approve <id> — Approve withdrawal\n"
            f"/reject <id> <reason> — Reject withdrawal\n"
            f"/credit <tg\\_id> <amount> — Credit user\n"
            f"/debit <tg\\_id> <amount> — Debit user\n"
            f"/signal open|close|update|summary — Post trade\n"
            f"/summary — Post performance summary\n"
            f"/pause — Pause signals\n"
            f"/resume — Resume signals\n"
            f"/logs — Recent transactions\n"
            f"/setaddr <address> — Set deposit address",
            parse_mode=ParseMode.MARKDOWN,
        )

    @admin_only
    async def cmd_list_users(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        users = await get_all_users()
        if not users:
            await update.message.reply_text("No users yet.")
            return
        lines = [f"👥 *Users* ({len(users)})\n"]
        for u in users[:30]:
            tag = f"@{u.username}" if u.username else f"`{u.telegram_id}`"
            lines.append(f"• {tag} — `${u.balance:.2f}` USDC")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    @admin_only
    async def cmd_pending_withdrawals(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        pending = await get_pending_withdrawals()
        if not pending:
            await update.message.reply_text("✅ No pending withdrawals.")
            return
        lines = [f"⏳ *Pending Withdrawals* ({len(pending)})\n"]
        for w in pending:
            lines.append(
                f"*#{w.id}* — `${w.amount:.2f}` USDC\n"
                f"  To: `{w.destination}`\n"
                f"  → `/approve {w.id}` | `/reject {w.id}`"
            )
        await update.message.reply_text("\n\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    @admin_only
    async def cmd_approve_withdrawal(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not ctx.args:
            await update.message.reply_text("Usage: `/approve <id> [note]`", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            wid = int(ctx.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid ID.")
            return
        note = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else None
        try:
            w = await approve_withdrawal(wid, note)
        except ValueError as e:
            await update.message.reply_text(f"❌ {e}")
            return
        await update.message.reply_text(
            f"✅ Withdrawal *#{w.id}* approved.\n`${w.amount:.2f}` to `{w.destination}`\n\n⚠️ Send funds manually on-chain.",
            parse_mode=ParseMode.MARKDOWN,
        )
        await self._notify_user(ctx, w, approved=True)

    @admin_only
    async def cmd_reject_withdrawal(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not ctx.args:
            await update.message.reply_text("Usage: `/reject <id> [reason]`", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            wid = int(ctx.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid ID.")
            return
        reason = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else "No reason provided"
        try:
            w = await reject_withdrawal(wid, reason)
        except ValueError as e:
            await update.message.reply_text(f"❌ {e}")
            return
        await update.message.reply_text(f"↩️ Withdrawal *#{w.id}* rejected. ${w.amount:.2f} refunded.", parse_mode=ParseMode.MARKDOWN)
        await self._notify_user(ctx, w, approved=False)

    async def _notify_user(self, ctx, withdrawal, approved: bool):
        from database.db import get_session, User
        async with get_session() as session:
            user = await session.get(User, withdrawal.user_id)
            if not user:
                return
        try:
            if approved:
                msg = (f"✅ *Withdrawal Approved*\n\n`${withdrawal.amount:.2f}` to `{withdrawal.destination}`\n"
                       f"Funds will arrive on-chain shortly.")
            else:
                msg = (f"❌ *Withdrawal Rejected*\n\n`${withdrawal.amount:.2f}` refunded to your balance.\n"
                       f"Reason: {withdrawal.admin_note}")
            await ctx.bot.send_message(user.telegram_id, msg, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

    @admin_only
    async def cmd_credit_user(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if len(ctx.args) < 2:
            await update.message.reply_text("Usage: `/credit <telegram_id> <amount> [note]`", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            tg_id = int(ctx.args[0])
            amount = float(ctx.args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid arguments.")
            return
        note = " ".join(ctx.args[2:]) if len(ctx.args) > 2 else "Admin credit"
        try:
            user = await admin_credit(tg_id, amount, note)
        except ValueError as e:
            await update.message.reply_text(f"❌ {e}")
            return
        await update.message.reply_text(f"✅ Credited `${amount:.2f}` to `{tg_id}`.\nNew balance: `${user.balance:.2f}`", parse_mode=ParseMode.MARKDOWN)

    @admin_only
    async def cmd_debit_user(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if len(ctx.args) < 2:
            await update.message.reply_text("Usage: `/debit <telegram_id> <amount> [note]`", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            tg_id = int(ctx.args[0])
            amount = float(ctx.args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid arguments.")
            return
        note = " ".join(ctx.args[2:]) if len(ctx.args) > 2 else "Admin debit"
        try:
            user = await admin_debit(tg_id, amount, note)
        except ValueError as e:
            await update.message.reply_text(f"❌ {e}")
            return
        await update.message.reply_text(f"✅ Debited `${amount:.2f}` from `{tg_id}`.\nNew balance: `${user.balance:.2f}`", parse_mode=ParseMode.MARKDOWN)

    @admin_only
    async def cmd_broadcast_signal(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not runtime["signals_active"]:
            await update.message.reply_text("⛔ Signals paused. Use /resume first.")
            return
        if not ctx.args:
            await update.message.reply_text(
                "Usage:\n"
                "`/signal open BTC BUY 65000 message`\n"
                "`/signal close BTC BUY 67000 3.5 message`\n"
                "`/signal update message`\n"
                "`/signal summary message`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        signal_type = ctx.args[0].lower()
        parts = ctx.args[1:]
        asset = direction = None
        entry_price = exit_price = pnl_pct = None
        try:
            if signal_type == "open" and len(parts) >= 3:
                asset, direction, entry_price = parts[0].upper(), parts[1].upper(), float(parts[2])
                message = " ".join(parts[3:])
                text = (f"📈 *New Signal*\n\nAsset: `{asset}`\n"
                        f"Direction: {'🟢 BUY' if direction == 'BUY' else '🔴 SELL'}\n"
                        f"Entry: `${entry_price:,.2f}`\n\n_{message}_")
            elif signal_type == "close" and len(parts) >= 4:
                asset, direction = parts[0].upper(), parts[1].upper()
                exit_price, pnl_pct = float(parts[2]), float(parts[3])
                message = " ".join(parts[4:])
                sign = "+" if pnl_pct >= 0 else ""
                emoji = "🎉" if pnl_pct >= 0 else "📉"
                text = (f"{emoji} *Trade Closed*\n\nAsset: `{asset}`\n"
                        f"Exit: `${exit_price:,.2f}`\nResult: `{sign}{pnl_pct:.2f}%`\n\n_{message}_")
            elif signal_type in ("update", "summary"):
                message = " ".join(parts)
                icon = "📊" if signal_type == "summary" else "🔔"
                label = "Summary" if signal_type == "summary" else "Update"
                text = f"{icon} *{label}*\n\n{message}"
            else:
                await update.message.reply_text("❌ Invalid format. See /signal for usage.")
                return
        except (ValueError, IndexError) as e:
            await update.message.reply_text(f"❌ Parse error: {e}")
            return

        sent_id = None
        if BROADCAST_CHAT_ID:
            try:
                sent = await ctx.bot.send_message(BROADCAST_CHAT_ID, text, parse_mode=ParseMode.MARKDOWN)
                sent_id = sent.message_id
            except Exception as e:
                await update.message.reply_text(f"⚠️ Broadcast failed: {e}")
        await create_trade_signal(signal_type, message, asset, direction, entry_price, exit_price, pnl_pct, sent_id)
        await update.message.reply_text("✅ Signal posted and logged.")

    @admin_only
    async def cmd_post_summary(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        signals = await get_recent_signals(50)
        closed = [s for s in signals if s.signal_type == "close" and s.pnl_pct is not None]
        if not closed:
            await update.message.reply_text("No closed trades to summarise.")
            return
        wins = [s for s in closed if s.pnl_pct >= 0]
        avg_pnl = sum(s.pnl_pct for s in closed) / len(closed)
        win_rate = len(wins) / len(closed) * 100
        text = (f"📊 *Performance Summary*\n\nTrades: `{len(closed)}`\n"
                f"Wins: `{len(wins)}` | Losses: `{len(closed)-len(wins)}`\n"
                f"Win Rate: `{win_rate:.1f}%`\nAvg PnL: `{'+'if avg_pnl>=0 else ''}{avg_pnl:.2f}%`")
        if BROADCAST_CHAT_ID:
            try:
                await ctx.bot.send_message(BROADCAST_CHAT_ID, text, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                await update.message.reply_text(f"⚠️ {e}")
                return
        await update.message.reply_text("✅ Summary posted.")

    @admin_only
    async def cmd_pause_signals(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        runtime["signals_active"] = False
        await set_setting("signals_active", "false")
        await update.message.reply_text("🔴 Signals *paused*.", parse_mode=ParseMode.MARKDOWN)

    @admin_only
    async def cmd_resume_signals(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        runtime["signals_active"] = True
        await set_setting("signals_active", "true")
        await update.message.reply_text("🟢 Signals *resumed*.", parse_mode=ParseMode.MARKDOWN)

    @admin_only
    async def cmd_recent_logs(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        logs = await get_recent_tx_logs(30)
        if not logs:
            await update.message.reply_text("No logs yet.")
            return
        lines = ["📋 *Recent Logs*\n"]
        for tx in logs:
            sign = "+" if tx.amount >= 0 else ""
            lines.append(f"• `{tx.action}` {sign}${tx.amount:.2f} [user {tx.user_id}] → `${tx.balance_after:.2f}`")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    @admin_only
    async def cmd_set_deposit_address(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not ctx.args:
            await update.message.reply_text("Usage: `/setaddr <wallet_address>`", parse_mode=ParseMode.MARKDOWN)
            return
        address = ctx.args[0].strip()
        await set_setting("master_wallet_address", address)
        import config.settings as s
        s.MASTER_WALLET_ADDRESS = address
        await update.message.reply_text(f"✅ Deposit address updated:\n`{address}`", parse_mode=ParseMode.MARKDOWN)

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.answer()
