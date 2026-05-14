import requests
import mysql.connector
import json
import os
import re
import time
import threading
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from mysql.connector import Error
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import urllib3
from opensearchpy import OpenSearch

# --------------------------- 全局配置 ---------------------------
GLOBAL_CONFIG = {
    "START_DATE": "1965-05-30",
    "END_DATE": "2025-04-10",
    "THREAD_COUNT": 8,  # 时间分段并行线程数
    "API_KEY": "f7c23ae0c463de865aad3e0a2379df00",
    "FILE_STORAGE_DIR": "darknet_file",
    "DB_CONFIG": {
        "host": "192.168.23.204",
        "database": "online",  # 修改数据库名为online
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
    "OPENSEARCH_INDEX": "darknet_index",
    "API_RATE_LIMIT": 8,
    "API_REQUEST_LOCK": threading.Lock(),
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
thread_local = threading.local()

# --------------------------- 时间分段生成函数 ---------------------------
def generate_time_segments(start_date_str, end_date_str, thread_count):
    """
    自定义时间分段：
    - 第1线程处理2010年12月31日前的时间段
    - 第2线程处理2011年1月1日-2015年12月31日
    - 剩余线程平均分配2016年1月1日后的时间段
    """
    start = datetime.strptime(start_date_str, "%Y-%m-%d")
    end = datetime.strptime(end_date_str, "%Y-%m-%d")

    # 固定时间节点
    date_2010 = datetime(2010, 12, 31)
    date_2015 = datetime(2015, 12, 31)
    date_2016 = datetime(2016, 1, 1)

    segments = []

    # 处理第1线程：start ~ 2010-12-31（如果start <= 2010-12-31）
    if start <= date_2010:
        segment_end = min(date_2010, end)
        segments.append((
            start.strftime("%Y-%m-%d"),
            segment_end.strftime("%Y-%m-%d")
        ))
        current = segment_end + timedelta(days=1)
    else:
        current = start  # 如果start在2010之后，跳过第一线程时间段

    # 处理第2线程：2011-01-01 ~ 2015-12-31（如果current <= 2015-12-31且线程数>=2）
    if thread_count >= 2 and current <= date_2015 and current <= end:
        segment_end = min(date_2015, end)
        segments.append((
            current.strftime("%Y-%m-%d"),
            segment_end.strftime("%Y-%m-%d")
        ))
        current = segment_end + timedelta(days=1)

    # 处理剩余线程：2016-01-01之后的时间段，平均分配
    remaining_threads = thread_count - len(segments)
    if remaining_threads > 0 and current <= end:
        total_remaining_days = (end - current).days + 1
        days_per_thread = total_remaining_days // remaining_threads
        remainder = total_remaining_days % remaining_threads

        for i in range(remaining_threads):
            segment_days = days_per_thread + (1 if i < remainder else 0)
            segment_end = current + timedelta(days=segment_days - 1)
            segment_end = min(segment_end, end)
            segments.append((
                current.strftime("%Y-%m-%d"),
                segment_end.strftime("%Y-%m-%d")
            ))
            current = segment_end + timedelta(days=1)

    return segments

# --------------------------- 配置初始化 ---------------------------
logging.basicConfig(
    filename='darknet_old.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(threadName)s - %(message)s'
)

# API 接口地址
all_data_api_url = "https://0.zone/api/data/"
detail_api_url = "https://0.zone/api/dark-data-detail/"

# 文件存储目录
darknet_file_dir = GLOBAL_CONFIG["FILE_STORAGE_DIR"]
public_dir = os.path.join(darknet_file_dir, 'public')
os.makedirs(public_dir, exist_ok=True)

# 配置请求重试策略
session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504]
)
session.mount("https://", HTTPAdapter(max_retries=retries))


def get_thread_opensearch_client():
    if not hasattr(thread_local, "opensearch_client"):
        thread_local.opensearch_client = OpenSearch(**GLOBAL_CONFIG["OPENSEARCH_CONFIG"])
        logging.info(f"线程 {threading.current_thread().name} 建立OpenSearch连接")
    return thread_local.opensearch_client

# --------------------------- 数据处理函数 ---------------------------
def process_time_segment(segment):
    """处理单个时间段内的所有数据（串行处理该时间段的所有分页）"""
    segment_start, segment_end = segment
    conn, cursor = connect_to_database()
    try:
        next_id = 0
        while True:
            all_data_payload = {
                "query": f"timestamp>={segment_start}&&timestamp<={segment_end}",
                "query_type": "darknet",
                "next": next_id,
                "pagesize": 100,
                "zone_key_id": GLOBAL_CONFIG["API_KEY"]
            }

            try:
                wait_for_rate_limit()
                all_data_response = session.post(
                    all_data_api_url,
                    json=all_data_payload,
                    timeout=10
                )
                if all_data_response.status_code != 200:
                    logging.warning(f"列表请求失败，状态码: {all_data_response.status_code}，时间段: {segment_start}-{segment_end}")
                    continue
                all_data = all_data_response.json()
                data_list = all_data.get('data', [])
                next_id = all_data.get('next', 0)

                if not data_list:
                    break

                for item in data_list:
                    try:
                        process_item(item, conn, cursor)  # 复用原item处理逻辑
                    except Exception as e:
                        logging.error(f"处理 item 时出错，_id: {item.get('_id')}, 错误: {str(e)}", exc_info=True)
                        continue

                if next_id == 0:
                    break
            except Exception as e:
                logging.error(f"请求所有数据时出错，时间段: {segment_start}-{segment_end}, 错误: {str(e)}", exc_info=True)
                continue

    except Exception as e:
        logging.error(f"时间段处理异常 {segment_start}-{segment_end}: {str(e)}", exc_info=True)
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

# --------------------------- 主逻辑 ---------------------------
def main():
    """主处理流程：按线程数平均分配时间范围并行处理"""
    main_conn, main_cursor = connect_to_database()
    create_tables(main_cursor)
    main_conn.commit()  # 显式提交表创建操作
    main_os_client = OpenSearch(**GLOBAL_CONFIG["OPENSEARCH_CONFIG"])
    ensure_darknet_index(main_os_client)
    validate_darknet_index_mapping(main_os_client)
    align_darknet_id_map_auto_increment(main_cursor, main_conn, main_os_client)

    # 生成平均时间分段
    time_segments = generate_time_segments(
        GLOBAL_CONFIG["START_DATE"],
        GLOBAL_CONFIG["END_DATE"],
        GLOBAL_CONFIG["THREAD_COUNT"]
    )

    # 检查每个时间段内OpenSearch已有数据的最小 timestamp，避免重复抓已入库范围
    new_time_segments = []
    for start, end in time_segments:
        min_timestamp = get_existing_min_timestamp(main_os_client, start, end)
        new_time_segments.append((start, min_timestamp or end))

    logging.info(f"生成时间分段: {new_time_segments}")

    main_cursor.close()
    main_conn.close()

    with ThreadPoolExecutor(max_workers=GLOBAL_CONFIG["THREAD_COUNT"]) as executor:
        futures = [executor.submit(process_time_segment, segment) for segment in new_time_segments]
        for future in futures:
            try:
                future.result()
            except Exception as e:
                logging.error(f"线程执行出错，错误: {str(e)}", exc_info=True)

    logging.info("所有时间段处理完成")

# --------------------------- 辅助函数（增强表创建健壮性） ---------------------------
def wait_for_rate_limit():
    with GLOBAL_CONFIG["API_REQUEST_LOCK"]:
        current_time = time.perf_counter()
        current_second = int(current_time)
        counter = GLOBAL_CONFIG["API_REQUEST_COUNTER"]

        if counter["current_second"] != current_second:
            counter.update({"current_second": current_second, "count": 1})
        else:
            if counter["count"] >= GLOBAL_CONFIG["API_RATE_LIMIT"]:
                wait_time = 1 - (current_time - current_second)
                if wait_time > 0:
                    time.sleep(wait_time)
                counter.update({"current_second": int(time.perf_counter()), "count": 1})
            else:
                counter["count"] += 1


def connect_to_database():
    while True:
        try:
            connection = mysql.connector.connect(**GLOBAL_CONFIG["DB_CONFIG"])
            cursor = connection.cursor(dictionary=True)
            return connection, cursor
        except Error as e:
            logging.error(f"数据库连接失败: {e}，5秒后重试")
            time.sleep(5)


def create_tables(cursor):
    """创建数据库表（增强错误处理）"""
    table_creation_queries = [
        ("darknet_id_map", """
        CREATE TABLE IF NOT EXISTS darknet_id_map (
            id INT AUTO_INCREMENT PRIMARY KEY,
            original_id VARCHAR(255) UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """),
        ("file", """
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
    ]

    for table_name, query in table_creation_queries:
        try:
            cursor.execute(query)
            logging.info(f"表 {table_name} 已创建或已存在")
        except Error as e:
            logging.error(f"创建表 {table_name} 失败: {e}")


def get_existing_min_timestamp(os_client, start, end):
    body = {
        "size": 1,
        "_source": ["timestamp"],
        "sort": [{"timestamp": {"order": "asc"}}],
        "query": {
            "range": {
                "timestamp": {
                    "gte": f"{start} 00:00:00",
                    "lte": f"{end} 23:59:59",
                }
            }
        },
    }
    try:
        response = os_client.search(index=GLOBAL_CONFIG["OPENSEARCH_INDEX"], body=body)
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return None
        timestamp = hits[0].get("_source", {}).get("timestamp")
        return str(timestamp).replace("T", " ").split(".")[0] if timestamp else None
    except Exception as exc:
        logging.warning(f"查询OpenSearch最小timestamp失败，时间段: {start}-{end}, 错误: {exc}")
        return None


def get_or_create_darknet_numeric_id(cursor, conn, original_id):
    cursor.execute("SELECT id FROM darknet_id_map WHERE original_id = %s", (original_id,))
    result = cursor.fetchone()
    if result:
        return result["id"]

    existing_id = find_existing_darknet_id(original_id)
    if existing_id is not None:
        cursor.execute(
            """
            INSERT INTO darknet_id_map (id, original_id)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE original_id = VALUES(original_id)
            """,
            (existing_id, original_id),
        )
        conn.commit()
        return existing_id

    cursor.execute(
        """
        INSERT INTO darknet_id_map (original_id)
        VALUES (%s)
        ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)
        """,
        (original_id,),
    )
    conn.commit()
    return cursor.lastrowid


def find_existing_darknet_id(original_id):
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
        logging.warning(f"查询OpenSearch现有darknet id失败，original_id={original_id}: {exc}")
        return None


def get_max_darknet_id(os_client):
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
        logging.warning(f"查询OpenSearch最大darknet id失败: {exc}")
        return 0


def align_darknet_id_map_auto_increment(cursor, conn, os_client):
    cursor.execute("SELECT COUNT(*) AS count, COALESCE(MAX(id), 0) AS max_id FROM darknet_id_map")
    result = cursor.fetchone()
    map_count = result["count"]
    map_max_id = result["max_id"]
    max_darknet_id = get_max_darknet_id(os_client)
    next_id = max(int(map_max_id), max_darknet_id) + 1
    if next_id <= 1:
        return
    cursor.execute(f"ALTER TABLE darknet_id_map AUTO_INCREMENT = {next_id}")
    conn.commit()
    logging.info(
        "映射表 darknet_id_map AUTO_INCREMENT 调整为 %s "
        "(map_count=%s, map_max_id=%s, opensearch_max_id=%s)",
        next_id,
        map_count,
        map_max_id,
        max_darknet_id,
    )


def update_darknet_child_file(parent_id, child_file):
    os_client = get_thread_opensearch_client()
    try:
        response = os_client.get(index=GLOBAL_CONFIG["OPENSEARCH_INDEX"], id=parent_id, ignore=[404])
        if not response or response.get("found") is False:
            logging.warning(f"OpenSearch未找到darknet记录: {parent_id}")
            return
        source = response.get("_source", {}) or {}
        existing = source.get("child_file") or ""
        updated_child_file = ",".join(part for part in [existing.rstrip(","), child_file] if part)
        os_client.update(
            index=GLOBAL_CONFIG["OPENSEARCH_INDEX"],
            id=parent_id,
            body={"doc": {"child_file": updated_child_file}},
        )
    except Exception as exc:
        logging.error(f"更新OpenSearch darknet child_file失败: {exc}")


def ensure_darknet_index(os_client):
    index_name = GLOBAL_CONFIG["OPENSEARCH_INDEX"]
    if os_client.indices.exists(index=index_name):
        return
    index_body = {
        "settings": {
            "index": {
                "number_of_shards": 30,
                "number_of_replicas": 0,
                "refresh_interval": "30s",
            }
        },
        "mappings": {
            "dynamic": "false",
            "properties": {
                "id": {"type": "long"},
                "title": {"type": "text", "analyzer": "standard"},
                "msg_author": {"type": "text", "analyzer": "standard"},
                "msg_title_cn": {"type": "text", "analyzer": "smartcn"},
                "url": {"type": "text", "analyzer": "standard"},
                "msg_description": {"type": "text", "analyzer": "smartcn"},
                "event": {"type": "text", "analyzer": "smartcn"},
                "industry": {"type": "text", "analyzer": "smartcn"},
                "tags": {"type": "text", "analyzer": "smartcn"},
                "original_id": {"type": "keyword"},
                "root_domain": {"type": "keyword"},
                "toplv_domain": {"type": "keyword"},
                "user_id": {"type": "keyword"},
                "child_file": {"type": "keyword"},
                "msg_release_time": {
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


def validate_darknet_index_mapping(os_client):
    index_name = GLOBAL_CONFIG["OPENSEARCH_INDEX"]
    mapping = os_client.indices.get_mapping(index=index_name)
    properties = mapping.get(index_name, {}).get("mappings", {}).get("properties", {})
    id_mapping = properties.get("id", {})
    original_id_mapping = properties.get("original_id", {})
    if id_mapping.get("type") != "long" or original_id_mapping.get("type") != "keyword":
        raise RuntimeError(
            f"{index_name} mapping不符合要求：需要 id=long 且 original_id=keyword。"
            "请先用新的 init_index.py 重建索引，再用 sync_darknet.py 从MySQL导入历史数据。"
        )


def process_item(item, conn, cursor):
    MAX_RETRIES = 3
    _id = item.get('_id')
    if not _id:
        return

    child_file_ids = []  # 用于存储所有关联文件的ID

    try:
        wait_for_rate_limit()
        detail_payload = {
            "query_type": "darknet",
            "id": _id,
            "zone_key_id": GLOBAL_CONFIG["API_KEY"]
        }

        detail_response = session.post(detail_api_url, json=detail_payload, timeout=10)
        if detail_response.status_code != 200:
            logging.warning(f"详情请求失败，状态码: {detail_response.status_code}，_id: {_id}")
            return

        detail_data = detail_response.json().get('data', {})
        msg = detail_data.get('msg', {})

        msg_sample_ss = json.dumps(msg.get('sample_ss', []))
        msg_keyword = json.dumps(msg.get('keyword', []))
        msg_webpage_ss = msg.get('webpage_ss')
        msg_author = msg.get('author')
        msg_release_time = msg.get('release_time')

        regions = detail_data.get('regions', [{}])
        regions_city = regions[0].get('city') if regions else None
        regions_country = regions[0].get('country') if regions else None
        regions_province = regions[0].get('province') if regions else None

        parent_id = get_or_create_darknet_numeric_id(cursor, conn, _id)
        row = {
            "id": parent_id,
            "original_id": detail_data.get("_id") or _id,
            "body_md5": detail_data.get("body_md5"),
            "description": detail_data.get("description", ""),
            "detail_parsing": json.dumps(detail_data.get("detail_parsing", {}), ensure_ascii=False),
            "event": json.dumps(detail_data.get("event", []), ensure_ascii=False),
            "industry": json.dumps(detail_data.get("industry", []), ensure_ascii=False),
            "is_read": detail_data.get("is_read"),
            "msg_author": msg_author,
            "msg_title_cn": msg.get("title_cn"),
            "msg_description": msg.get("description"),
            "msg_release_time": msg_release_time,
            "org": json.dumps(detail_data.get("org", []), ensure_ascii=False),
            "page_type": json.dumps(detail_data.get("page_type", []), ensure_ascii=False),
            "path": detail_data.get("path"),
            "regions_city": regions_city,
            "regions_country": regions_country,
            "regions_province": regions_province,
            "root_domain": detail_data.get("root_domain"),
            "source": detail_data.get("source"),
            "status_code": detail_data.get("status_code"),
            "tags": json.dumps(detail_data.get("tags", []), ensure_ascii=False),
            "timestamp": detail_data.get("timestamp"),
            "title": detail_data.get("title"),
            "toplv_domain": detail_data.get("toplv_domain"),
            "update_time": detail_data.get("update_time"),
            "url": detail_data.get("url"),
            "user_id": detail_data.get("user_id"),
            "to_new": detail_data.get("to_new"),
            "body": detail_data.get("body"),
            "msg_sample_ss": msg_sample_ss,
            "msg_keyword": msg_keyword,
            "msg_webpage_ss": msg_webpage_ss,
            "child_file": "",
        }

        os_client = get_thread_opensearch_client()
        for retry in range(MAX_RETRIES):
            try:
                response = os_client.index(
                    index=GLOBAL_CONFIG["OPENSEARCH_INDEX"],
                    id=parent_id,
                    body=row,
                )
                logging.info(
                    "写入OpenSearch darknet id=%s original_id=%s result=%s",
                    parent_id,
                    _id,
                    response.get("result"),
                )
                break
            except Exception as exc:
                logging.warning(f"OpenSearch写入重试 {retry + 1}，_id: {_id}, 错误: {exc}")
                time.sleep(2)
        else:
            logging.error(f"OpenSearch写入失败，跳过文件处理，_id: {_id}")
            return

        # 创建以 _id 命名的子文件夹
        sub_folder = os.path.join(darknet_file_dir, _id)
        os.makedirs(sub_folder, exist_ok=True)

        # 保存 body 字段为 body.html 文件
        body = detail_data.get('body')
        if body:
            body_file_path = os.path.join(sub_folder, 'body.html')
            with open(body_file_path, 'w', encoding='utf-8') as f:
                f.write(body)
            file_size = os.path.getsize(body_file_path)
            data_subtype = 0x2005
            file_id = insert_file_to_db(conn, cursor, 'body.html', body_file_path, file_size, parent_id, data_subtype)
            if file_id:
                child_file_ids.append(str(file_id))  # 收集文件ID

        # 下载 sample_ss 中的图片
        sample_ss_list = json.loads(msg_sample_ss)
        if sample_ss_list:
            for i, url in enumerate(sample_ss_list):
                if '0.zone' not in url:
                    continue
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                    }
                    response = session.get(url, headers=headers, timeout=(3, 10))
                    response.raise_for_status()
                    img_file_name = f'sample_ss_{i}.jpg'
                    img_file_path = os.path.join(sub_folder, img_file_name)

                    if not os.path.exists(img_file_path):
                        with open(img_file_path, 'wb') as f:
                            f.write(response.content)
                    # 替换 body.html 中的图片链接
                    if body:
                        relative_path = img_file_name
                        body = body.replace(url, relative_path)
                        with open(body_file_path, 'w', encoding='utf-8') as f:
                            f.write(body)
                    file_size = os.path.getsize(img_file_path)
                    data_subtype = 0x2003
                    file_id = insert_file_to_db(conn, cursor, img_file_name, img_file_path, file_size, parent_id, data_subtype)
                    if file_id:
                        child_file_ids.append(str(file_id))  # 收集文件ID
                except Exception as e:
                    print(f"处理图片 {url} 失败: {e}")

        # 处理其他包含 0.zone 的链接
        if body:
            # 提取所有包含 0.zone 的链接
            pattern = re.compile(r'https?://[^"]*0\.zone[^"]*')
            all_links = pattern.findall(body)
            for url in all_links:
                # 排除 sample_ss 中的链接
                if url not in sample_ss_list:
                    try:
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                        }
                        # 生成文件名时清理非法字符
                        file_name = re.sub(r'[\\/*?:"<>|]', '_', url.split('/')[-1])
                        if not file_name:
                            file_name = 'unknown.html'
                        file_path = os.path.join(public_dir, file_name)

                        # 检查文件是否存在
                        if not os.path.exists(file_path):
                            response = session.get(url, headers=headers, timeout=(3, 10))
                            response.raise_for_status()

                            with open(file_path, 'wb') as f:
                                f.write(response.content)

                        # 替换链接为相对路径
                        relative_path = os.path.join('../public', file_name)
                        body = body.replace(url, relative_path)
                        file_size = os.path.getsize(file_path)
                        data_subtype = 0x2004  # 假设类型为0x2004，表示其他类型的文件
                        file_id = insert_file_to_db(conn, cursor, file_name, file_path, file_size, parent_id, data_subtype)
                        if file_id:
                            child_file_ids.append(str(file_id))  # 收集文件ID
                    except Exception as e:
                        print(f"处理链接 {url} 失败: {e}")

            # 更新 body.html
            with open(body_file_path, 'w', encoding='utf-8') as f:
                f.write(body)

        # 如果有新的文件ID，更新child_file字段
        if child_file_ids and len(child_file_ids) > 0:
            update_darknet_child_file(parent_id, ','.join(child_file_ids))

    except Exception as e:
        logging.error(f"处理 item {_id} 出错: {e}")


def insert_file_to_db(conn, cursor, file_name, file_path, file_size, parent_id, data_subtype):
    insert_file_query = """
    INSERT INTO file (data_type, data_subtype, producer_id, datasource, file_name, file_size, parent_id, file_path)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    values = (2, data_subtype, '', 3, file_name, file_size, parent_id, file_path)
    try:
        cursor.execute(insert_file_query, values)
        conn.commit()
        return cursor.lastrowid  # 返回插入的文件ID
    except mysql.connector.Error as err:
        logging.error(f"插入文件数据到 file 表失败，文件名: {file_name}, 错误: {str(err)}", exc_info=True)
        return None


if __name__ == "__main__":
    main()
