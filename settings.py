import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: list = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
BROADCAST_CHAT_ID: str = os.getenv("BROADCAST_CHAT_ID", "")
MASTER_WALLET_ADDRESS: str = os.getenv("MASTER_WALLET_ADDRESS", "")
CRYPTO_NETWORK: str = os.getenv("CRYPTO_NETWORK", "ethereum")
BLOCKCHAIN_API_KEY: str = os.getenv("BLOCKCHAIN_API_KEY", "")
MIN_DEPOSIT: float = float(os.getenv("MIN_DEPOSIT", "10"))
MIN_WITHDRAWAL: float = float(os.getenv("MIN_WITHDRAWAL", "10"))
DEPOSIT_POLL_INTERVAL: int = int(os.getenv("DEPOSIT_POLL_INTERVAL", "60"))
TRADE_POLL_INTERVAL: int = int(os.getenv("TRADE_POLL_INTERVAL", "30"))
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot_data.db")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# Fix common Railway DATABASE_URL format issues
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+asyncpg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

runtime: dict = {
    "signals_active": os.getenv("SIGNALS_ACTIVE", "true").lower() == "true"
}
