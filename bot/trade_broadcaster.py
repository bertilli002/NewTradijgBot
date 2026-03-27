from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
from telegram.constants import ParseMode
from config.settings import BROADCAST_CHAT_ID, TRADE_POLL_INTERVAL, runtime
from database.crud import create_trade_signal, get_setting, set_setting

logger = logging.getLogger(__name__)
TRADE_FEED_FILE = Path("trade_feed.jsonl")


class TradeBroadcaster:
    def __init__(self, bot):
        self.bot = bot
        self._offset = 0

    async def run(self):
        logger.info("TradeBroadcaster started.")
        try:
            stored = await get_setting("trade_feed_offset", "0")
            self._offset = int(stored)
        except Exception:
            self._offset = 0
        while True:
            try:
                await self._process()
            except Exception as e:
                logger.error(f"TradeBroadcaster error: {e}")
            await asyncio.sleep(TRADE_POLL_INTERVAL)

    async def _process(self):
        if not TRADE_FEED_FILE.exists() or not runtime.get("signals_active", True):
            return
        with open(TRADE_FEED_FILE, "rb") as f:
            f.seek(self._offset)
            lines = f.readlines()
            new_offset = f.tell()
        if not lines:
            return
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                trade = json.loads(line)
                await self._broadcast(trade)
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
        self._offset = new_offset
        await set_setting("trade_feed_offset", str(self._offset))

    async def _broadcast(self, trade: dict):
        t = trade.get("type", "update").lower()
        asset = trade.get("asset")
        direction = trade.get("direction")
        entry = trade.get("entry_price")
        exit_p = trade.get("exit_price")
        pnl = trade.get("pnl_pct")
        message = trade.get("message", "")
        if t == "open":
            text = (f"📈 *New Signal*\nAsset: `{asset}`\n"
                    f"Direction: {'🟢 BUY' if direction == 'BUY' else '🔴 SELL'}\n"
                    f"Entry: `${entry:,.2f}`\n\n_{message}_")
        elif t == "close":
            sign = "+" if (pnl or 0) >= 0 else ""
            text = (f"{'🎉' if (pnl or 0) >= 0 else '📉'} *Trade Closed*\n"
                    f"Asset: `{asset}`\nExit: `${exit_p:,.2f}`\nResult: `{sign}{pnl:.2f}%`\n\n_{message}_")
        elif t == "summary":
            text = f"📊 *Summary*\n\n{message}"
        else:
            text = f"🔔 *Update*\n\n{message}"
        sent_id = None
        if BROADCAST_CHAT_ID:
            try:
                sent = await self.bot.send_message(BROADCAST_CHAT_ID, text, parse_mode=ParseMode.MARKDOWN)
                sent_id = sent.message_id
            except Exception as e:
                logger.error(f"Channel send failed: {e}")
        await create_trade_signal(t, message, asset, direction, entry, exit_p, pnl, sent_id)
