import logging
import sys
from pythonjsonlogger import jsonlogger
from app.core.config import settings


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("skilltwin")
    logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)

    # Avoid duplicate handlers if setup_logging is called multiple times
    if not logger.handlers:
        log_handler = logging.StreamHandler(sys.stdout)
        if settings.APP_ENV == "production":
            formatter = jsonlogger.JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(message)s"
            )
        else:
            formatter = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] %(name)s.%(module)s: %(message)s"
            )
        log_handler.setFormatter(formatter)
        logger.addHandler(log_handler)

    return logger


logger = setup_logging()
