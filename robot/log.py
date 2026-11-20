import logging
import sys

from . import config

_logger = logging.getLogger("robot")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(config.LOGS / "robot.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    _logger.addHandler(fh)
    _logger.addHandler(sh)

log = _logger
