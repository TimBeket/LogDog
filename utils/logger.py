import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from utils.helpers import get_app_data_dir

# Internal logger for the LogDog Application itself, not the parsed logs.
logger = logging.getLogger("LogDog")
logger.setLevel(logging.DEBUG)

# Max 2 MB per file, keep 3 backup files = ~8 MB total max
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3


def setup_logger(debug_mode: bool = False):
    """Initializes the backend logger specifically for LogDog diagnostics."""
    if logger.handlers:
        for h in logger.handlers[:]:
            logger.removeHandler(h)

    log_file = get_app_data_dir() / "logdog_diagnostic.log"
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    try:
        fh = RotatingFileHandler(
            log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG if debug_mode else logging.INFO)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG if debug_mode else logging.INFO)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        logger.info("LogDog logger initialized -> %s (rotation: %d MB, %d backups)",
                     log_file, LOG_MAX_BYTES // (1024 * 1024), LOG_BACKUP_COUNT)
    except Exception as e:
        logging.basicConfig(level=logging.DEBUG if debug_mode else logging.INFO)
        logger.error("Failed to open diagnostic log file %s: %s", log_file, e)
