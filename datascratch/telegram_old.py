import requests
import mysql.connector
import time
import os
import logging
from mysql.connector import Error
import mimetypes
import threading
from datetime import datetime, timedelta
from threading import local, Lock
import urllib3
from opensearchpy import OpenSearch, helpers
# import pdb

# 全局配置
GLOBAL_CONFIG = {
    "START_DATE": "2022-11-11",
    "END_DATE": "2025-04-07",
    "THREAD_COUNT": 16,  # 原本为16
    "API_KEY": "f7c23ae0c463de865aad3e0a2379df00",
    "FILE_STORAGE_DIR": "telegram_file",
    "DB_CONFIG": {
        "host": "192.168.23.204",
        "database": "online",  # 修改为online库
        "user": "root",
        "password": "MyPass123!",
        "auth_plugin": "caching_sha2_password"
    },
    "OPENSEARCH_CONFIG": {
        "hosts": [{"host": "192.168.23.204", "port": 9200}],
        "http_auth": ("admin", "MyStrongPass123!"),
        "use_ssl": True,
        "verify_certs": False,
        "ssl_show_warn": False,
        "timeout": 60,
        "max_retries": 5,
        "retry_on_timeout": True,
    },
    "OPENSEARCH_INDEX": "telegram_index",
    "API_RATE_LIMIT": 10,
    "API_REQUEST_LOCK": Lock(),
    "API_REQUEST_COUNTER": {
        "current_second": None,
        "count": 0
    },
    "CUSTOM_MIME_MAP": {
        'image/jpeg': 'jpg',
        'image/png': 'png',
        'application/pdf': 'pdf',
        'video/mp4': 'mp4',
        'audio/mpeg': 'mp3'
    }
}

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
thread_local = local()

# 配置日志
logging.basicConfig(
    filename='telegram_old.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [Thread-%(threadName)s] - %(message)s'
)

# 创建文件存储目录
os.makedirs(GLOBAL_CONFIG["FILE_STORAGE_DIR"], exist_ok=True)


# 数据库工具函数
def get_thread_connection():
    if not hasattr(thread_local, "connection"):
        thread_local.connection = mysql.connector.connect(**GLOBAL_CONFIG["DB_CONFIG"])
        thread_local.cursor = thread_local.connection.cursor()
        logging.info(f"线程 {threading.current_thread().name} 建立数据库连接")
    return thread_local.connection, thread_local.cursor


def get_thread_opensearch_client():
    if not hasattr(thread_local, "opensearch_client"):
        thread_local.opensearch_client = OpenSearch(**GLOBAL_CONFIG["OPENSEARCH_CONFIG"])
        logging.info(f"线程 {threading.current_thread().name} 建立OpenSearch连接")
    return thread_local.opensearch_client


def close_thread_connection():
    if hasattr(thread_local, "connection") and thread_local.connection.is_connected():
        thread_local.cursor.close()
        thread_local.connection.close()
        logging.info(f"线程 {threading.current_thread().name} 关闭数据库连接")


# 时间范围分割
def split_time_range():
    start = datetime.strptime(GLOBAL_CONFIG["START_DATE"], "%Y-%m-%d")
    end = datetime.strptime(GLOBAL_CONFIG["END_DATE"], "%Y-%m-%d")
    total_days = (end - start).days + 1
    days_per_thread = total_days // GLOBAL_CONFIG["THREAD_COUNT"] + 1

    time_ranges = []
    for i in range(GLOBAL_CONFIG["THREAD_COUNT"]):
        t_start = start + timedelta(days=i * days_per_thread)
        t_end = min(start + timedelta(days=(i + 1) * days_per_thread), end)
        time_ranges.append((
            t_start.strftime("%Y-%m-%d"),
            t_end.strftime("%Y-%m-%d")
        ))
    return time_ranges


# 获取每个线程上次最后入库数据的 timestamp
def get_last_timestamp(thread_start, thread_end):
    os_client = get_thread_opensearch_client()
    body = {
        "size": 1,
        "_source": ["timestamp"],
        "sort": [{"timestamp": {"order": "asc"}}],
        "query": {
            "range": {
                "timestamp": {
                    "gte": f"{thread_start} 00:00:00",
                    "lte": f"{thread_end} 23:59:59",
                }
            }
        },
    }
    try:
        response = os_client.search(index=GLOBAL_CONFIG["OPENSEARCH_INDEX"], body=body)
        hits = response.get("hits", {}).get("hits", [])
        if hits:
            timestamp = hits[0].get("_source", {}).get("timestamp")
            if timestamp:
                return str(timestamp).replace("T", " ")
    except Exception as exc:
        logging.warning(f"线程 {threading.current_thread().name} 查询OpenSearch last_timestamp失败: {exc}")
    return thread_end


# 数据处理函数（新增child_file字段，初始为空）
def process_data(item):
    _source = item.get('_source', {})
    timestamp = _source.get('timestamp', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    
    return {
        "original_id": item.get('_id', ''),
        "timestamp": timestamp,
        "chat_id": _source.get('chat_id', ''),
        "chat_name": _source.get('chat_name', ''),
        "content_text": _source.get('content_text', ''),
        "content_text_md5": _source.get('content_text_md5', ''),
        "event": str(_source.get('event', [])),
        "file_extension": _source.get('file_extension', ''),
        "hot": _source.get('hot', 0),
        "identical_msg_num": _source.get('identical_msg_num', 0),
        "industry": str(_source.get('industry', [])),
        "media_file_url": _source.get('media_file_url', ''),
        "media_type": _source.get('media_type', ''),
        "message_date": _source.get('message_date', ''),
        "message_id": _source.get('message_id', ''),
        "message_time": _source.get('message_time', ''),
        "message_time_old_list": str(_source.get('message_time_old_list', [])),
        "org": str(_source.get('org', [])),
        "regions": str(_source.get('regions', [])),
        "sender_first_name": _source.get('sender_first_name', ''),
        "sender_id": _source.get('sender_id', ''),
        "sender_last_name": _source.get('sender_last_name', ''),
        "sender_phone": _source.get('sender_phone', ''),
        "sender_username": _source.get('sender_username', ''),
        "tags": str(_source.get('tags', [])),
        "page_type": str(_source.get('page_type', [])),
        "child_file": ''
    }


def get_or_create_telegram_numeric_id(cursor, conn, original_id):
    cursor.execute("SELECT id FROM telegram_id_map WHERE original_id = %s", (original_id,))
    result = cursor.fetchone()
    if result:
        return result[0]

    existing_id = find_existing_telegram_id(original_id)
    if existing_id is not None:
        cursor.execute(
            """
            INSERT INTO telegram_id_map (id, original_id)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE original_id = VALUES(original_id)
            """,
            (existing_id, original_id),
        )
        conn.commit()
        return existing_id

    insert_query = """
    INSERT INTO telegram_id_map (original_id)
    VALUES (%s)
    ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)
    """
    cursor.execute(insert_query, (original_id,))
    conn.commit()
    return cursor.lastrowid


def find_existing_telegram_id(original_id):
    os_client = get_thread_opensearch_client()
    body = {
        "size": 1,
        "_source": ["id"],
        "query": {"term": {"original_id": original_id}},
    }
    try:
        response = os_client.search(index=GLOBAL_CONFIG["OPENSEARCH_INDEX"], body=body)
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return None
        source_id = hits[0].get("_source", {}).get("id")
        if source_id is not None:
            return int(source_id)
        return int(hits[0].get("_id"))
    except Exception as exc:
        logging.warning(f"查询OpenSearch现有telegram id失败，original_id={original_id}: {exc}")
        return None


def get_max_telegram_id(os_client):
    body = {
        "size": 1,
        "_source": ["id"],
        "sort": [{"id": {"order": "desc"}}],
        "query": {"match_all": {}},
    }
    try:
        response = os_client.search(index=GLOBAL_CONFIG["OPENSEARCH_INDEX"], body=body)
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return 0
        source_id = hits[0].get("_source", {}).get("id")
        if source_id is not None:
            return int(source_id)
        return int(hits[0].get("_id"))
    except Exception as exc:
        logging.warning(f"查询OpenSearch最大telegram id失败: {exc}")
        return 0


def align_telegram_id_map_auto_increment(cursor, conn, os_client):
    cursor.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM telegram_id_map")
    map_count, map_max_id = cursor.fetchone()
    max_telegram_id = get_max_telegram_id(os_client)
    next_id = max(int(map_max_id), max_telegram_id) + 1
    if next_id <= 1:
        return
    cursor.execute(f"ALTER TABLE telegram_id_map AUTO_INCREMENT = {next_id}")
    conn.commit()
    logging.info(
        "映射表 telegram_id_map AUTO_INCREMENT 调整为 %s "
        "(map_count=%s, map_max_id=%s, opensearch_max_id=%s)",
        next_id,
        map_count,
        map_max_id,
        max_telegram_id,
    )


# 速率限制控制
def wait_for_rate_limit():
    with GLOBAL_CONFIG["API_REQUEST_LOCK"]:
        current_time = time.perf_counter()
        current_second = int(current_time)
        counter = GLOBAL_CONFIG["API_REQUEST_COUNTER"]

        # 新秒重置计数器
        if counter["current_second"] != current_second:
            counter.update({
                "current_second": current_second,
                "count": 1
            })
            logging.info(f"线程 {threading.current_thread().name} 进入新的一秒，重置计数器为 1")
        else:
            # 达到速率限制则等待到下一秒
            if counter["count"] >= GLOBAL_CONFIG["API_RATE_LIMIT"]:
                wait_time = 1 - (current_time - current_second)
                if wait_time > 0:
                    logging.info(f"线程 {threading.current_thread().name} 达到速率限制，等待 {wait_time:.3f} 秒")
                    # 忙等待到下一秒
                    while time.perf_counter() < current_second + 1:
                        time.sleep(0.001)
                # 重置计数器
                new_second = int(time.perf_counter())
                counter.update({
                    "current_second": new_second,
                    "count": 1
                })
                logging.info(f"线程 {threading.current_thread().name} 进入新的一秒，重置计数器为 1")
            else:
                counter["count"] += 1
                logging.info(f"线程 {threading.current_thread().name} 发送请求，当前计数器: {counter['count']}")


# 线程任务函数
def thread_worker(thread_start, thread_end):
    try:
        # 获取上次最后入库数据的 timestamp
        # pdb.set_trace()
        last_timestamp = get_last_timestamp(thread_start, thread_end)
        logging.info(f"线程 {threading.current_thread().name} 从 {thread_start} 开始抓取，到{last_timestamp}结束")

        conn, cursor = get_thread_connection()
        next_id = 0

        while True:
            wait_for_rate_limit()

            payload = {
                "query": f"timestamp>={thread_start}&&timestamp<={last_timestamp}",
                "query_type": "telegram",
                "next": next_id,
                "pagesize": 100,
                "zone_key_id": GLOBAL_CONFIG["API_KEY"]
            }

            while True:
                try:
                    response = requests.post(
                        "https://0.zone/api/im/",
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=15
                    )
                    response.raise_for_status()
                    data = response.json()
                    if data.get('code') == 0:
                        break
                    elif "请求太频繁" in data.get('message', ''):
                        logging.warning(f"线程 {threading.current_thread().name} 触发请求频率限制，等待下一秒重试")
                        # 忙等待到下一秒
                        current_time = time.perf_counter()
                        current_second = int(current_time)
                        wait_time = 1 - (current_time - current_second)
                        if wait_time > 0:
                            while time.perf_counter() < current_second + 1:
                                time.sleep(0.001)
                        with GLOBAL_CONFIG["API_REQUEST_LOCK"]:
                            new_second = int(time.perf_counter())
                            GLOBAL_CONFIG["API_REQUEST_COUNTER"].update({
                                "current_second": new_second,
                                "count": 1
                            })
                        continue
                    else:
                        logging.error(f"线程 {threading.current_thread().name} API错误: {data.get('message')}")
                        break
                except requests.exceptions.RequestException as e:
                    logging.warning(f"线程 {threading.current_thread().name} 请求异常: {str(e)}，等待 2 秒重试")
                    time.sleep(2)

            current_data = data.get('data', [])
            if not current_data:
                logging.info(f"线程 {threading.current_thread().name} 数据获取完毕")
                break

            next_id = data.get('next', 0)
            save_to_database(cursor, conn, current_data)

    except Exception as e:
        logging.error(f"线程 {threading.current_thread().name} 处理异常: {str(e)}", exc_info=True)
    finally:
        close_thread_connection()


def save_to_database(cursor, conn, data_list):
    os_client = get_thread_opensearch_client()
    rows = []
    for item in data_list:
        row = process_data(item)
        if not row["original_id"]:
            continue
        row["id"] = get_or_create_telegram_numeric_id(cursor, conn, row["original_id"])
        rows.append(row)

    actions = [
        {
            "_op_type": "index",
            "_index": GLOBAL_CONFIG["OPENSEARCH_INDEX"],
            "_id": row["id"],
            "_source": row,
        }
        for row in rows
    ]

    for retry in range(3):
        try:
            success_count, errors = helpers.bulk(
                os_client,
                actions,
                raise_on_error=False,
                raise_on_exception=False,
            )
            if errors:
                logging.warning(f"线程 {threading.current_thread().name} OpenSearch写入失败 {len(errors)} 条: {errors[:3]}")
            logging.info(f"线程 {threading.current_thread().name} 写入OpenSearch {success_count} 条数据")
            break
        except Exception as e:
            logging.warning(f"线程 {threading.current_thread().name} OpenSearch写入重试 {retry + 1}: {str(e)}")
            time.sleep(2)

    with GLOBAL_CONFIG["API_REQUEST_LOCK"]:
        for item in data_list:
            download_file(item, conn, cursor)  # 传递连接和游标以便查询ID


def download_file(item, conn, cursor):
    _source = item.get('_source', {})
    media_url = _source.get('media_file_url')
    media_type = _source.get('media_type')
    item_id = item.get('_id')  # 获取当前记录的_id

    if not all([media_url, media_type, item_id]):
        logging.warning(f"线程 {threading.current_thread().name} 跳过无效文件: {item_id}")
        return

    file_path = os.path.join(GLOBAL_CONFIG["FILE_STORAGE_DIR"], item_id)
    file_extension = ""
    file_ids = []  # 存储当前文件的file_id

    for retry in range(3):
        try:
            file_response = requests.get(media_url, stream=True, timeout=30)
            file_response.raise_for_status()

            content_type = file_response.headers.get('Content-Type', '')
            file_extension = GLOBAL_CONFIG["CUSTOM_MIME_MAP"].get(content_type)
            if not file_extension:
                guessed_ext = mimetypes.guess_extension(content_type)
                file_extension = guessed_ext.lstrip('.') if guessed_ext and guessed_ext.startswith('.') else ''

            # 保存临时文件
            with open(file_path, 'wb') as f:
                for chunk in file_response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # 添加文件扩展名
            if file_extension:
                new_file_path = f"{file_path}.{file_extension}"
                os.rename(file_path, new_file_path)
                file_path = new_file_path

            content_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)

            # 确定 data_subtype
            if file_extension.lower() == 'txt':
                data_subtype = 0x2001
            elif file_extension.lower() in ['doc', 'docx', 'pdf', 'xls', 'xlsx']:
                data_subtype = 0x2002
            elif file_extension.lower() in ['jpeg', 'jpg', 'png']:
                data_subtype = 0x2003
            elif file_extension.lower() in ['zip', '7z', 'rar']:
                data_subtype = 0x2004
            elif file_extension.lower() in ['html', 'htm']:
                data_subtype = 0x2005
            elif file_extension.lower() in ['mp3', 'wav', 'ogg','mp4']:
                data_subtype = 0x2006
            else:
                data_subtype = 0x2007

            # 获取telegram对应的稳定数字id，用于file.parent_id和OpenSearch文档id
            cursor.execute("SELECT id FROM telegram_id_map WHERE original_id = %s", (item_id,))
            result = cursor.fetchone()
            if not result:
                logging.warning(f"线程 {threading.current_thread().name} 未找到对应的telegram记录: {item_id}")
                return
            parent_id = result[0]

            # 插入file表
            insert_file_query = """
            INSERT INTO file (
                data_type, data_subtype, producer_id, datasource, file_name, file_size, parent_id, file_path
            )
            VALUES (
                2, %s, '', 2, %s, %s, %s, %s
            ) ON DUPLICATE KEY UPDATE 
                data_type = VALUES(data_type),
                data_subtype = VALUES(data_subtype),
                producer_id = VALUES(producer_id),
                datasource = VALUES(datasource),
                file_name = VALUES(file_name),
                file_size = VALUES(file_size),
                parent_id = VALUES(parent_id),
                file_path = VALUES(file_path)
            """
            cursor.execute(insert_file_query, (data_subtype, file_name, content_size, parent_id, file_path))
            conn.commit()

            # 获取刚插入的file_id
            cursor.execute("SELECT LAST_INSERT_ID()")
            file_id = cursor.fetchone()[0]
            file_ids.append(str(file_id))

            # 更新OpenSearch中telegram文档的child_file字段
            if file_ids:
                child_file = ','.join(file_ids)
                update_telegram_child_file(parent_id, child_file)
                logging.info(f"线程 {threading.current_thread().name} 更新child_file: {child_file} 到记录ID {parent_id}")

            logging.info(f"线程 {threading.current_thread().name} 保存文件: {file_path}")
            break

        except requests.exceptions.RequestException as e:
            logging.warning(f"线程 {threading.current_thread().name} 文件下载重试 {retry + 1}: {str(e)}")
            time.sleep(2)
        except Exception as e:
            logging.error(f"线程 {threading.current_thread().name} 文件处理错误: {str(e)}")


def update_telegram_child_file(parent_id, child_file):
    os_client = get_thread_opensearch_client()
    try:
        response = os_client.get(index=GLOBAL_CONFIG["OPENSEARCH_INDEX"], id=parent_id, ignore=[404])
        if not response or response.get("found") is False:
            logging.warning(f"线程 {threading.current_thread().name} OpenSearch未找到telegram记录: {parent_id}")
            return
        source = response.get("_source", {}) or {}
        existing = source.get("child_file") or ""
        updated_child_file = f"{existing}{child_file},"
        os_client.update(
            index=GLOBAL_CONFIG["OPENSEARCH_INDEX"],
            id=parent_id,
            body={"doc": {"child_file": updated_child_file}},
        )
    except Exception as exc:
        logging.error(f"线程 {threading.current_thread().name} 更新OpenSearch child_file失败: {exc}")


def ensure_telegram_index(os_client):
    index_name = GLOBAL_CONFIG["OPENSEARCH_INDEX"]
    if os_client.indices.exists(index=index_name):
        return
    index_body = {
        "settings": {
            "index": {
                "number_of_shards": 30,
                "number_of_replicas": 0,
                "refresh_interval": "-1",
            }
        },
        "mappings": {
            "dynamic": "false",
            "properties": {
                "content_text": {"type": "text", "analyzer": "smartcn"},
                "chat_name": {"type": "text", "analyzer": "smartcn"},
                "org": {"type": "text", "analyzer": "smartcn"},
                "sender_first_name": {"type": "text", "analyzer": "smartcn"},
                "sender_last_name": {"type": "text", "analyzer": "smartcn"},
                "event": {"type": "text", "analyzer": "smartcn"},
                "industry": {"type": "text", "analyzer": "smartcn"},
                "tags": {"type": "text", "analyzer": "smartcn"},
                "original_id": {"type": "keyword"},
                "chat_id": {"type": "keyword"},
                "message_id": {"type": "keyword"},
                "sender_id": {"type": "keyword"},
                "sender_username": {"type": "keyword"},
                "message_date": {
                    "type": "date",
                    "format": "yyyy-MM-dd HH:mm:ss||yyyy-MM-dd",
                },
                "message_time": {
                    "type": "date",
                    "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time",
                },
                "timestamp": {
                    "type": "date",
                    "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time",
                },
            },
        },
    }
    os_client.indices.create(index=index_name, body=index_body)
    logging.info(f"OpenSearch索引 {index_name} 创建完成")


# 主流程
if __name__ == "__main__":
    main_conn = mysql.connector.connect(**GLOBAL_CONFIG["DB_CONFIG"])
    main_cursor = main_conn.cursor()
    # pdb.set_trace()

    # telegram主数据写入OpenSearch；MySQL只保留_id到稳定数字id的映射，供file.parent_id使用
    main_cursor.execute("""
    CREATE TABLE IF NOT EXISTS telegram_id_map (
        id INT AUTO_INCREMENT PRIMARY KEY,
        original_id VARCHAR(255) UNIQUE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    logging.info("映射表 telegram_id_map 创建完成")

    # 创建文件表
    main_cursor.execute("""
    CREATE TABLE IF NOT EXISTS file (
        file_id INT AUTO_INCREMENT PRIMARY KEY,
        data_type INT,
        data_subtype INT,
        producer_id VARCHAR(255),
        datasource INT,
        file_name VARCHAR(255),
        file_size INT,
        parent_id INT,
        file_path TEXT
    )
    """)
    logging.info("文件表 file 创建完成")

    main_os_client = OpenSearch(**GLOBAL_CONFIG["OPENSEARCH_CONFIG"])
    ensure_telegram_index(main_os_client)
    align_telegram_id_map_auto_increment(main_cursor, main_conn, main_os_client)

    main_conn.close()

    time_ranges = split_time_range()
    threads = []
    for i, (start, end) in enumerate(time_ranges):
        thread_name = f"Worker-{i + 1}"
        t = threading.Thread(
            target=thread_worker,
            args=(start, end),
            name=thread_name
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    logging.info("所有线程执行完毕，程序退出")
