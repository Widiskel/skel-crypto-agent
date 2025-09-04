import sys
from loguru import logger

def setup_logger():
    """Configures the loguru logger for the application."""
    logger.remove()
    logger.add(
        sys.stderr, level="DEBUG",
        # format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}:{line}</cyan> - <level>{message}</level>",
        format="<green>{time:HH:mm:ss}</green>(<level>{level: <8}</level>) - <level>{message}</level>",
        colorize=True,
    )
    return logger