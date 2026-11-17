"""Logging setup. Every module logs through the "approval" logger tree; call setup_logging() once at startup."""
import logging
import os

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "approval.log")
FORMAT = "%(asctime)s [%(levelname)s] [%(threadName)s] %(name)s: %(message)s"


def setup_logging(level=logging.INFO):
    """Log to the console and to logs/approval.log. Safe to call more than once."""
    logger = logging.getLogger("approval")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    logger.propagate = False

    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    for handler in (logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")):
        handler.setFormatter(logging.Formatter(FORMAT, datefmt="%H:%M:%S"))
        logger.addHandler(handler)
    return logger
