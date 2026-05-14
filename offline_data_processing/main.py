import argparse
import logging

from .pipeline import OfflineDataPipeline


def main():
    parser = argparse.ArgumentParser(description="离线数据处理")
    parser.add_argument("-f", "--folder", default="test", help="要处理的文件夹路径")
    parser.add_argument("--log-level", default="INFO", help="日志级别")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    pipeline = OfflineDataPipeline(args.folder)
    result = pipeline.process_tree()
    logging.info("处理完成: %s", result)


if __name__ == "__main__":
    main()

