import argparse
import logging

from .storage import OpenSearchRecordStore


def parse_args():
    parser = argparse.ArgumentParser(description="初始化离线数据 OpenSearch 索引")
    parser.add_argument("--delete-existing", action="store_true", help="如果索引已存在，先删除后重建")
    parser.add_argument("--log-level", default="INFO", help="日志级别")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    store = OpenSearchRecordStore()
    for index_name in [store.index_name, store.import_index_name]:
        if store.client.indices.exists(index=index_name):
            if not args.delete_existing:
                logging.info("索引已存在，跳过删除: %s", index_name)
                continue
            logging.warning("删除已存在索引: %s", index_name)
            store.client.indices.delete(index=index_name)

    store.ensure_schema()
    logging.info("索引初始化完成: %s, %s", store.index_name, store.import_index_name)


if __name__ == "__main__":
    main()
