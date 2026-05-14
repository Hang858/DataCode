import logging
import time
import argparse
from datetime import date, datetime

import pymysql
import urllib3
from opensearchpy import OpenSearch
from opensearchpy.helpers import streaming_bulk
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

DARKNET_TABLE = "darknet"
DARKNET_INDEX = "darknet_index"
CHUNK_SIZE = 10
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 30
ERROR_LOG = "darknet_resync_errors.log"
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
            cursor.execute(f"SELECT COUNT(*) FROM {DARKNET_TABLE}")
            return cursor.fetchone()[0]
    finally:
        conn.close()


def iter_darknet_rows(mysql_conn, pbar):
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {DARKNET_TABLE}")
        while True:
            row = cursor.fetchone()
            if not row:
                break
            for key, value in row.items():
                row[key] = normalize_time_value(value)
            if "_id" in row:
                row["original_id"] = row.pop("_id")
            pbar.update(1)
            yield row


def chunked(iterable, size):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def make_actions(rows):
    for row in rows:
        yield {
            "_op_type": "index",
            "_index": DARKNET_INDEX,
            "_id": row["id"],
            "_source": row,
        }


def set_refresh_interval(client, interval):
    client.indices.put_settings(
        index=DARKNET_INDEX,
        body={"index": {"refresh_interval": interval}},
    )


def bulk_index_with_retry(client, rows):
    error_items = []
    for attempt in range(1, MAX_RETRIES + 1):
        retry_rows = []
        all_ok = True
        result_counts = {"created": 0, "updated": 0}
        for success, info in streaming_bulk(
            client,
            make_actions(rows),
            chunk_size=len(rows),
            max_retries=0,
            raise_on_error=False,
            raise_on_exception=False,
            yield_ok=True,
        ):
            if success:
                item = info.get("index", info)
                result = item.get("result")
                if result in result_counts:
                    result_counts[result] += 1
                continue
            all_ok = False
            item = info.get("index", info)
            status = item.get("status")
            error = item.get("error")
            doc_id = item.get("_id")
            if status == 429:
                retry_row = next((row for row in rows if str(row["id"]) == str(doc_id)), None)
                if retry_row is not None:
                    retry_rows.append(retry_row)
                continue
            error_items.append({"id": doc_id, "status": status, "error": error})

        if all_ok and not retry_rows:
            return True, error_items, result_counts

        if not retry_rows:
            return False, error_items, result_counts

        rows = retry_rows
        backoff = min(INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1)), MAX_BACKOFF_SECONDS)
        print(f"批次触发 429，等待 {backoff}s 后重试，重试条数: {len(rows)}")
        time.sleep(backoff)

    for row in rows:
        error_items.append({"id": row["id"], "status": 429, "error": "max retries exceeded"})
    return False, error_items, {"created": 0, "updated": 0}


def clear_index_if_requested(client, reset_index):
    if not reset_index:
        return
    if client.indices.exists(index=DARKNET_INDEX):
        client.delete_by_query(
            index=DARKNET_INDEX,
            body={"query": {"match_all": {}}},
            conflicts="proceed",
            refresh=True,
            wait_for_completion=True,
        )
        print(f"已清空索引数据: {DARKNET_INDEX}")


def sync_darknet(reset_index=False):
    print("开始重导 darknet -> darknet_index")
    total_count = get_total_count()
    print(f"darknet 总条数: {total_count}")

    mysql_conn = get_mysql_conn(dict_cursor=True)
    os_client = get_os_client()
    success_count = 0
    created_count = 0
    updated_count = 0
    error_items = []

    try:
        set_refresh_interval(os_client, IMPORT_REFRESH_INTERVAL)
        clear_index_if_requested(os_client, reset_index)

        with tqdm(total=total_count, desc="同步 darknet", unit="条") as pbar:
            for rows in chunked(iter_darknet_rows(mysql_conn, pbar), CHUNK_SIZE):
                batch_success, batch_errors, result_counts = bulk_index_with_retry(os_client, rows)
                success_count += len(rows) - len(batch_errors)
                created_count += result_counts.get("created", 0)
                updated_count += result_counts.get("updated", 0)
                if not batch_success and batch_errors:
                    error_items.extend(batch_errors)

        os_client.indices.refresh(index=DARKNET_INDEX)
        set_refresh_interval(os_client, QUERY_REFRESH_INTERVAL)
        print(f"完成。成功写入: {success_count}")
        print(f"新增文档: {created_count}，覆盖更新: {updated_count}")
        print(f"索引已刷新: {DARKNET_INDEX}")

        if error_items:
            print(f"仍有失败数据: {len(error_items)}")
            with open(ERROR_LOG, "w", encoding="utf-8") as handle:
                for item in error_items:
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="仅重导 darknet 数据到 darknet_index")
    parser.add_argument(
        "--reset-index",
        action="store_true",
        help="导入前先清空 darknet_index 中现有数据",
    )
    args = parser.parse_args()
    sync_darknet(reset_index=args.reset_index)
