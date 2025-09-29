import sys
from pathlib import Path

from loguru import logger

LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
LOG_FILE = LOG_DIR / "agent.log"


def setup_logger():
    """Configures the loguru logger for the application."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG",
        format="<green>{time:HH:mm:ss}</green>(<level>{level: <8}</level>) - <level>{message}</level>",
        colorize=True,
    )
    logger.add(
        LOG_FILE,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
        enqueue=True,
    )
    return logger
