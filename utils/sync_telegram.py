import argparse
import logging
from datetime import date, datetime

import pymysql
import urllib3
from opensearchpy import OpenSearch
from opensearchpy.helpers import parallel_bulk
from pymysql.cursors import SSDictCursor
from tqdm import tqdm

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.getLogger("opensearch").setLevel(logging.WARNING)

MYSQL_CONFIG = {
    "host": "192.168.23.204",
    "port": 3306,
    "user": "root",
    "password": "MyPass123!",
    "database": "online",
    "charset": "utf8mb4",
}

OPENSEARCH_CONFIG = {
    "hosts": [{"host": "192.168.23.204", "port": 9200}],
    "http_auth": ("admin", "MyStrongPass123!"),
    "use_ssl": True,
    "verify_certs": False,
    "ssl_show_warn": False,
    "timeout": 60,
    "max_retries": 5,
    "retry_on_timeout": True,
}

TELEGRAM_TABLE = "telegram"
TELEGRAM_INDEX = "telegram_index"
THREAD_COUNT = 8
CHUNK_SIZE = 5000
QUEUE_SIZE = 16
ERROR_LOG = "telegram_resync_errors.log"
IMPORT_REFRESH_INTERVAL = "-1"
QUERY_REFRESH_INTERVAL = "30s"


def get_mysql_conn(dict_cursor=True):
    cursor_cls = SSDictCursor if dict_cursor else pymysql.cursors.Cursor
    return pymysql.connect(**MYSQL_CONFIG, cursorclass=cursor_cls)


def get_os_client():
    return OpenSearch(**OPENSEARCH_CONFIG)


def normalize_time_value(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    return value


def get_total_count():
    conn = get_mysql_conn(dict_cursor=False)
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {TELEGRAM_TABLE}")
            return cursor.fetchone()[0]
    finally:
        conn.close()


def generate_bulk_actions(mysql_conn, pbar):
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {TELEGRAM_TABLE}")

        while True:
            row = cursor.fetchone()
            if not row:
                break

            for key, value in row.items():
                row[key] = normalize_time_value(value)

            if "_id" in row:
                row["original_id"] = row.pop("_id")

            pbar.update(1)

            yield {
                "_index": TELEGRAM_INDEX,
                "_id": row["id"],
                "_source": row,
            }


def clear_index_if_requested(os_client, reset_index):
    if not reset_index:
        return
    if os_client.indices.exists(index=TELEGRAM_INDEX):
        os_client.delete_by_query(
            index=TELEGRAM_INDEX,
            body={"query": {"match_all": {}}},
            conflicts="proceed",
            refresh=True,
            wait_for_completion=True,
        )
        print(f"已清空索引数据: {TELEGRAM_INDEX}")


def set_refresh_interval(os_client, interval):
    os_client.indices.put_settings(
        index=TELEGRAM_INDEX,
        body={"index": {"refresh_interval": interval}},
    )


def sync_telegram(reset_index=False):
    print("开始重导 telegram -> telegram_index")
    total_count = get_total_count()
    print(f"telegram 总条数: {total_count}")

    mysql_conn = get_mysql_conn(dict_cursor=True)
    os_client = get_os_client()

    try:
        set_refresh_interval(os_client, IMPORT_REFRESH_INTERVAL)
        clear_index_if_requested(os_client, reset_index)

        with tqdm(total=total_count, desc="同步 telegram", unit="条") as pbar:
            success_count = 0
            created_count = 0
            updated_count = 0
            errors = []

            for success, info in parallel_bulk(
                os_client,
                generate_bulk_actions(mysql_conn, pbar),
                thread_count=THREAD_COUNT,
                chunk_size=CHUNK_SIZE,
                queue_size=QUEUE_SIZE,
                raise_on_error=False,
                raise_on_exception=False,
            ):
                if success:
                    success_count += 1
                    item = info.get("index", info)
                    result = item.get("result")
                    if result == "created":
                        created_count += 1
                    elif result == "updated":
                        updated_count += 1
                else:
                    errors.append(info)

        os_client.indices.refresh(index=TELEGRAM_INDEX)
        set_refresh_interval(os_client, QUERY_REFRESH_INTERVAL)
        print(f"完成。成功写入: {success_count}")
        print(f"新增文档: {created_count}，覆盖更新: {updated_count}")
        print(f"索引已刷新: {TELEGRAM_INDEX}")

        if errors:
            print(f"仍有失败数据: {len(errors)}")
            with open(ERROR_LOG, "w", encoding="utf-8") as handle:
                for item in errors:
                    handle.write(f"{item}\n")
            print(f"错误明细已写入: {ERROR_LOG}")
        else:
            print("没有剩余失败数据。")
    finally:
        try:
            set_refresh_interval(os_client, QUERY_REFRESH_INTERVAL)
        except Exception as exc:
            print(f"恢复 refresh_interval 失败: {exc}")
        mysql_conn.close()


def main():
    parser = argparse.ArgumentParser(description="仅重导 telegram 数据到 telegram_index")
    parser.add_argument(
        "--reset-index",
        action="store_true",
        help="导入前先清空 telegram_index 中现有数据",
    )
    args = parser.parse_args()
    sync_telegram(reset_index=args.reset_index)


if __name__ == "__main__":
    main()
