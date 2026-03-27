from __future__ import annotations
import asyncio
import logging
import aiohttp
from config.settings import ADMIN_IDS, BLOCKCHAIN_API_KEY, CRYPTO_NETWORK, DEPOSIT_POLL_INTERVAL, MIN_DEPOSIT
from database.crud import deposit_exists, get_setting

logger = logging.getLogger(__name__)

USDC_CONTRACTS = {
    "ethereum": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "bsc": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
}


class DepositMonitor:
    def __init__(self, bot):
        self.bot = bot
        self._seen: set = set()

    async def run(self):
        logger.info("DepositMonitor started.")
        while True:
            try:
                await self._check()
            except Exception as e:
                logger.error(f"DepositMonitor error: {e}")
            await asyncio.sleep(DEPOSIT_POLL_INTERVAL)

    async def _check(self):
        wallet = await get_setting("master_wallet_address") or ""
        if not wallet:
            return
        txns = await self._fetch(wallet)
        for tx in txns:
            tx_hash = tx.get("hash", "")
            amount = tx.get("amount", 0.0)
            if not tx_hash or tx_hash in self._seen:
                continue
            self._seen.add(tx_hash)
            if await deposit_exists(tx_hash):
                continue
            if amount < MIN_DEPOSIT:
                continue
            logger.info(f"New deposit: {amount} USDC | {tx_hash}")
            msg = (f"📥 *New Deposit Detected*\n\n"
                   f"Amount: `{amount:.2f} USDC`\nTxHash: `{tx_hash}`\n"
                   f"Network: {CRYPTO_NETWORK.upper()}\n\n"
                   f"Use `/credit <telegram_id> {amount:.2f} deposit:{tx_hash}` to credit the user.")
            for admin_id in ADMIN_IDS:
                try:
                    await self.bot.send_message(admin_id, msg, parse_mode="Markdown")
                except Exception:
                    pass

    async def _fetch(self, wallet: str) -> list:
        network = CRYPTO_NETWORK.lower()
        contract = USDC_CONTRACTS.get(network, "")
        if network == "ethereum":
            api_base = "https://api.etherscan.io/api"
        elif network == "bsc":
            api_base = "https://api.bscscan.com/api"
        else:
            return []
        params = {
            "module": "account", "action": "tokentx",
            "contractaddress": contract, "address": wallet,
            "sort": "desc", "apikey": BLOCKCHAIN_API_KEY or "freekey",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_base, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    data = await resp.json()
                    txns = data.get("result", [])
                    if not isinstance(txns, list):
                        return []
                    results = []
                    for tx in txns:
                        if tx.get("to", "").lower() != wallet.lower():
                            continue
                        try:
                            decimals = int(tx.get("tokenDecimal", 6))
                            amount = int(tx["value"]) / (10 ** decimals)
                            results.append({"hash": tx["hash"], "amount": amount})
                        except (KeyError, ValueError):
                            continue
                    return results
        except Exception as e:
            logger.error(f"Deposit fetch error: {e}")
            return []
