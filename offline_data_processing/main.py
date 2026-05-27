import argparse
import logging
import sys
from pathlib import Path

from .config import LOG_DIR
from .pipeline import OfflineDataPipeline


class ExactLevelFilter(logging.Filter):
    def __init__(self, level):
        super().__init__()
        self.level = level

    def filter(self, record):
        return record.levelno == self.level


def configure_logging(log_level, log_dir=LOG_DIR):
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    all_handler = logging.FileHandler(log_path / "all.log", encoding="utf-8")
    all_handler.setLevel(logging.DEBUG)
    all_handler.setFormatter(formatter)
    root_logger.addHandler(all_handler)

    for level, filename in [
        (logging.DEBUG, "debug.log"),
        (logging.INFO, "info.log"),
        (logging.ERROR, "error.log"),
    ]:
        handler = logging.FileHandler(log_path / filename, encoding="utf-8")
        handler.setLevel(level)
        handler.addFilter(ExactLevelFilter(level))
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)


def main():
    parser = argparse.ArgumentParser(description="离线数据处理")
    parser.add_argument("-f", "--folder", default="test", help="要处理的文件夹路径")
    parser.add_argument("--log-level", default="INFO", help="日志级别")
    parser.add_argument("--log-dir", default=LOG_DIR, help="日志目录")
    args = parser.parse_args()

    configure_logging(args.log_level, args.log_dir)
    folder = Path(args.folder)
    if not folder.exists():
        logging.error("要处理的目录不存在: %s", folder)
        return 1
    if not folder.is_dir():
        logging.error("要处理的路径不是目录: %s", folder)
        return 1

    try:
        pipeline = OfflineDataPipeline(args.folder)
        result = pipeline.process_tree()
        logging.info("处理完成: %s", result)
        return 0
    except Exception:
        logging.exception("离线数据处理异常退出")
        return 1


if __name__ == "__main__":
    sys.exit(main())
