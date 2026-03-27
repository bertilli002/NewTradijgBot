from __future__ import annotations
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from config.settings import ADMIN_IDS, MIN_DEPOSIT, MIN_WITHDRAWAL, MASTER_WALLET_ADDRESS, CRYPTO_NETWORK
from database.crud import get_or_create_user, get_user_tx_log, get_user_withdrawals, create_withdrawal

logger = logging.getLogger(__name__)


class UserHandlers:

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        tg = update.effective_user
        await get_or_create_user(tg.id, tg.username, tg.full_name)
        await update.message.reply_text(
            f"👋 Welcome, *{tg.first_name}*!\n\n"
            "I manage your trading account. Here's what you can do:\n\n"
            "💰 /balance — View your balance\n"
            "📥 /deposit — Get deposit address\n"
            "📤 /withdraw — Request a withdrawal\n"
            "📋 /history — Transaction history\n"
            "❓ /help — Help & FAQ",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def cmd_balance(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        tg = update.effective_user
        user = await get_or_create_user(tg.id, tg.username, tg.full_name)
        withdrawals = await get_user_withdrawals(user.id, limit=50)
        pending_out = sum(w.amount for w in withdrawals if w.status.value == "pending")
        await update.message.reply_text(
            f"💼 *Your Balance*\n\n"
            f"Available: `${user.balance:.2f} USDC`\n"
            f"Pending withdrawal: `${pending_out:.2f} USDC`",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def cmd_deposit(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        addr = MASTER_WALLET_ADDRESS
        if not addr:
            await update.message.reply_text("⚠️ Deposit address not set yet. Contact admin.")
            return
        await update.message.reply_text(
            f"📥 *Deposit Instructions*\n\n"
            f"Send USDC ({CRYPTO_NETWORK.upper()}) to:\n\n"
            f"`{addr}`\n\n"
            f"Minimum: `${MIN_DEPOSIT:.2f} USDC`\n\n"
            f"⚠️ Only send USDC on {CRYPTO_NETWORK.upper()} network.",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def cmd_withdraw(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        tg = update.effective_user
        user = await get_or_create_user(tg.id, tg.username, tg.full_name)
        args = ctx.args
        if len(args) < 2:
            await update.message.reply_text(
                f"📤 *Withdrawal*\n\nUsage: `/withdraw <amount> <wallet_address>`\n\n"
                f"Minimum: `${MIN_WITHDRAWAL:.2f} USDC`\nYour balance: `${user.balance:.2f} USDC`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        try:
            amount = float(args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid amount.")
            return
        destination = args[1].strip()
        if amount < MIN_WITHDRAWAL:
            await update.message.reply_text(f"❌ Minimum withdrawal is ${MIN_WITHDRAWAL:.2f} USDC.")
            return
        if user.balance < amount:
            await update.message.reply_text(f"❌ Insufficient balance. Available: `${user.balance:.2f} USDC`", parse_mode=ParseMode.MARKDOWN)
            return
        w = await create_withdrawal(user.id, amount, destination, CRYPTO_NETWORK)
        for admin_id in ADMIN_IDS:
            try:
                await ctx.bot.send_message(
                    admin_id,
                    f"🔔 *New Withdrawal Request #{w.id}*\n\n"
                    f"User: @{tg.username or tg.id} (`{tg.id}`)\n"
                    f"Amount: `${amount:.2f} USDC`\n"
                    f"To: `{destination}`\n\n"
                    f"Use `/approve {w.id}` or `/reject {w.id} reason`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
        await update.message.reply_text(
            f"✅ *Withdrawal Submitted*\n\nAmount: `${amount:.2f} USDC`\nTo: `{destination}`\n"
            f"Status: ⏳ Pending admin approval\nRef: `#{w.id}`",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def cmd_history(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        tg = update.effective_user
        user = await get_or_create_user(tg.id, tg.username, tg.full_name)
        logs = await get_user_tx_log(user.id, limit=15)
        if not logs:
            await update.message.reply_text("📋 No transactions yet.")
            return
        lines = ["📋 *Recent Transactions*\n"]
        for tx in logs:
            sign = "+" if tx.amount >= 0 else ""
            emoji = {"deposit": "📥", "withdrawal_hold": "📤", "withdrawal_refund": "↩️",
                     "admin_credit": "🎁", "admin_debit": "🔧"}.get(tx.action, "•")
            lines.append(f"{emoji} `{tx.action}` {sign}${tx.amount:.2f} → `${tx.balance_after:.2f}`\n"
                         f"   _{tx.created_at.strftime('%Y-%m-%d %H:%M UTC')}_")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "❓ *Help*\n\n"
            "/balance — Check your USDC balance\n"
            "/deposit — Get deposit address\n"
            "/withdraw <amount> <address> — Request withdrawal\n"
            "/history — Transaction history\n\n"
            "Deposits are credited after admin confirmation.\n"
            "Withdrawals require admin approval and are sent manually.",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.answer()

    async def handle_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Use /help to see available commands.")
