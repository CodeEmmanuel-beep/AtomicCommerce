import logging
from logging.handlers import RotatingFileHandler
import os


def get_logger(name: str):
    logs = "logs"
    os.makedirs(logs, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        logger.propagate = False
        fmt = logging.Formatter("%(asctime)s-%(levelname)s-%(message)s")
        fh = RotatingFileHandler(
            f"{logs}/{name}.log", maxBytes=5_000_000, backupCount=3
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    return logger
