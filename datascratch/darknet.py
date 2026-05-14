import requests
import mysql.connector
import json
import os
import re
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from mysql.connector import Error
import logging
from datetime import datetime
import hashlib
import urllib3
from opensearchpy import OpenSearch

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置日志记录
logging.basicConfig(filename='darknet_new.log', level=logging.ERROR,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# 数据库连接配置 - 修改库名为online
db_config = {
    'host': '192.168.23.204',
    'database': 'online',  # 修改库名为online
    'user': 'root',
    'password': 'MyPass123!',
    'auth_plugin': 'caching_sha2_password'
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
DARKNET_INDEX = "darknet_index"
os_client = OpenSearch(**OPENSEARCH_CONFIG)

# API 密钥
key = "f7c23ae0c463de865aad3e0a2379df00"

# 全部情报数据预览 API 接口
all_data_api_url = "https://0.zone/api/data/"
# 情报详情 API 接口
detail_api_url = "https://0.zone/api/dark-data-detail/"

# 确保 darknet_file 和 public 文件夹存在
darknet_file_dir = 'darknet_file'
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

# 公共配置参数
config = {
    "start_time": "2025-03-10",
    "end_time": "2025-04-14"
}

# 记录API使用次数和时间
api_count = 0
api_start_time = time.time()


#抓取cookie
user_agent = "Module/2"
timestamp=int(time.time())
auth_key = "a29676d1c97b815799e832d7bf3a37b54bc388fc"
cookie=""
request_type = int(10)

# 拼接签名内容
raw = f"{user_agent}-{timestamp}-{auth_key}"
signature = hashlib.sha256(raw.encode()).hexdigest()


# authorization = f"UAS {timestamp} {signature}"

#接受cookie

header={"User-Agent": user_agent, 
        "Content-Type": "application/json"}
data={"requestType":request_type,
      "time": timestamp, 
      "token": signature}
print(data)

try:
    response = requests.post("http://192.168.1.10:8443/system/connect", headers=header, json=data, verify=False)
    cookie=response.headers['Set-Cookie']
    if response.status_code == 200:
        print("请求成功")
        print("响应内容:", response.text)
    else:
        print(f"请求失败，状态码: {response.status_code}")
        print("响应内容:", response.text)

except requests.exceptions.RequestException as e:
    print(f"请求异常: {e}") 

def connect_to_database():
    while True:
        try:
            connection = mysql.connector.connect(**db_config)
            cursor = connection.cursor(dictionary=True)
            print("数据库连接成功")
            return connection, cursor
        except Error as e:
            print(f"数据库连接出错: {e}，将在 5 秒后重试...")
            time.sleep(5)


def create_tables(cursor):
    # 主数据写入OpenSearch；MySQL只保留_id到稳定数字id的映射，供file.parent_id使用
    create_table_query = """
    CREATE TABLE IF NOT EXISTS darknet_id_map (
        id INT AUTO_INCREMENT PRIMARY KEY,
        original_id VARCHAR(255) UNIQUE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """
    try:
        cursor.execute(create_table_query)
        print("创建 darknet_id_map 表成功")
    except Error as e:
        print(f"创建 darknet 表出错: {e}")

    # 创建 file 表（如果不存在）
    create_file_table_query = """
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
    """
    try:
        cursor.execute(create_file_table_query)
        print("创建 file 表成功")
    except Error as e:
        print(f"创建 file 表出错: {e}")


def check_connection(connection, cursor):
    try:
        connection.ping(reconnect=True, attempts=3, delay=5)
        if not connection.is_connected():
            connection, cursor = connect_to_database()
    except Error as e:
        print(f"数据库连接已断开，重新连接: {e}")
        connection, cursor = connect_to_database()
    return connection, cursor


def get_max_darknet_id():
    body = {
        "size": 1,
        "_source": ["id"],
        "sort": [{"id": {"order": "desc"}}],
        "query": {"match_all": {}},
    }
    try:
        response = os_client.search(index=DARKNET_INDEX, body=body)
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return 0
        source_id = hits[0].get("_source", {}).get("id")
        return int(source_id if source_id is not None else hits[0].get("_id"))
    except Exception as exc:
        logging.warning(f"查询OpenSearch最大darknet id失败: {exc}")
        return 0


def align_darknet_id_map_auto_increment(connection, cursor):
    cursor.execute("SELECT COUNT(*) AS count, COALESCE(MAX(id), 0) AS max_id FROM darknet_id_map")
    result = cursor.fetchone()
    next_id = max(int(result["max_id"]), get_max_darknet_id()) + 1
    if next_id > 1:
        cursor.execute(f"ALTER TABLE darknet_id_map AUTO_INCREMENT = {next_id}")
        connection.commit()


def find_existing_darknet_id(original_id):
    body = {
        "size": 1,
        "_source": ["id"],
        "query": {"term": {"original_id": original_id}},
    }
    response = os_client.search(index=DARKNET_INDEX, body=body)
    hits = response.get("hits", {}).get("hits", [])
    if not hits:
        return None
    source_id = hits[0].get("_source", {}).get("id")
    return int(source_id if source_id is not None else hits[0].get("_id"))


def get_or_create_darknet_id(connection, cursor, original_id):
    cursor.execute("SELECT id FROM darknet_id_map WHERE original_id = %s", (original_id,))
    result = cursor.fetchone()
    if result:
        return result["id"]
    existing_id = find_existing_darknet_id(original_id)
    if existing_id is not None:
        cursor.execute(
            "INSERT INTO darknet_id_map (id, original_id) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE original_id = VALUES(original_id)",
            (existing_id, original_id),
        )
        connection.commit()
        return existing_id
    cursor.execute(
        "INSERT INTO darknet_id_map (original_id) VALUES (%s) "
        "ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)",
        (original_id,),
    )
    connection.commit()
    return cursor.lastrowid


def update_darknet_child_file(parent_id, child_file_ids):
    child_file = ",".join(map(str, child_file_ids))
    response = os_client.get(index=DARKNET_INDEX, id=parent_id, ignore=[404])
    if not response or response.get("found") is False:
        logging.warning(f"OpenSearch未找到darknet记录: {parent_id}")
        return
    existing = (response.get("_source") or {}).get("child_file") or ""
    updated = ",".join(part for part in [existing.rstrip(","), child_file] if part)
    os_client.update(index=DARKNET_INDEX, id=parent_id, body={"doc": {"child_file": updated}})


def get_latest_darknet_timestamp():
    body = {
        "size": 1,
        "_source": ["timestamp"],
        "sort": [{"timestamp": {"order": "desc"}}],
        "query": {"match_all": {}},
    }
    try:
        response = os_client.search(index=DARKNET_INDEX, body=body)
        hits = response.get("hits", {}).get("hits", [])
        if hits and hits[0].get("_source", {}).get("timestamp"):
            return str(hits[0]["_source"]["timestamp"]).replace("T", " ")
    except Exception as exc:
        logging.warning(f"查询OpenSearch最新darknet timestamp失败: {exc}")
    return None


def get_data_subtype(file_ext):
    txt_ext = ['.txt']
    doc_ext = ['.doc', '.docx', '.pdf', '.xls', '.xlsx']
    img_ext = ['.jpg', '.jpeg', '.png', '.gif']
    zip_ext = ['.zip', '.7z', '.rar']
    audio_ext = ['.mp3', '.wav']

    if file_ext in txt_ext:
        return 0x2001
    elif file_ext in doc_ext:
        return 0x2002
    elif file_ext in img_ext:
        return 0x2003
    elif file_ext in zip_ext:
        return 0x2004
    elif file_ext == '.html':
        return 0x2005
    elif file_ext in audio_ext:
        return 0x2006
    return 0x2007


def insert_file_to_db(cursor, connection, file_name, file_path, parent_id):
    file_ext = os.path.splitext(file_name)[1].lower()
    data_subtype = get_data_subtype(file_ext)
    file_size = os.path.getsize(file_path)
    
    # 跳过0KB文件
    if file_size == 0:
        print(f"跳过0KB文件: {file_name}")
        return None
    
    insert_file_query = """
    INSERT INTO file (data_type, data_subtype, producer_id, datasource, file_name, file_size, parent_id, file_path)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""
    values = (2, data_subtype, '', 3, file_name, file_size, parent_id, file_path)
    try:
        cursor.execute(insert_file_query, values)
        connection.commit()
        return cursor.lastrowid  # 返回插入后的文件ID
    except Error as e:
        logging.error(f"插入文件记录到 file 表时出错: {e}")
        return None


def process_item(item, cursor, session, connection):
    global api_count, api_start_time
    _id = item.get('_id')
    if not _id:
        return

    # 控制API使用次数
    while api_count >= 2 and time.time() - api_start_time < 1:
        time.sleep(0.1)
    api_count += 1
    if api_count >= 2:
        api_start_time = time.time()
        api_count = 0

    # 检查数据库连接
    connection, cursor = check_connection(connection, cursor)

    # 构建情报详情 API 请求体
    detail_payload = {
        "query_type": "darknet",
        "id": _id,
        "zone_key_id": key
    }

    child_file_ids = []  # 存储所有下载文件的ID
    child_file_names = []
    data_id=0
    message={}
    try:
        # 发送情报详情 API 请求
        detail_response = session.post(detail_api_url, json=detail_payload, timeout=10)
        if detail_response.status_code == 200:
            detail_data = detail_response.json().get('data', {})
            msg = detail_data.get('msg', {})
            mesage=msg

            # 获取字段值
            msg_sample_ss = json.dumps(msg.get('sample_ss', []))
            msg_keyword = json.dumps(msg.get('keyword', []))
            msg_webpage_ss = msg.get('webpage_ss')
            msg_author = msg.get('author')
            msg_release_time = msg.get('release_time')

            # 处理 description 字段可能过长的问题
            description = detail_data.get('description', '')

            regions = detail_data.get('regions', [{}])
            regions_city = regions[0].get('city') if regions else None
            regions_country = regions[0].get('country') if regions else None
            regions_province = regions[0].get('province') if regions else None

            parent_id = get_or_create_darknet_id(connection, cursor, _id)
            data_id=parent_id
            row = {
                "id": parent_id,
                "original_id": detail_data.get("_id") or _id,
                "body_md5": detail_data.get("body_md5"),
                "description": description,
                "detail_parsing": json.dumps(detail_data.get("detail_parsing", {}), ensure_ascii=False),
                "event": json.dumps(detail_data.get("event", []), ensure_ascii=False),
                "industry": json.dumps(detail_data.get("industry", []), ensure_ascii=False),
                "is_read": detail_data.get("is_read"),
                "msg_author": msg_author,
                "msg_title_cn": detail_data.get("msg", {}).get("title_cn"),
                "msg_description": detail_data.get("msg", {}).get("description"),
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
            result = os_client.index(index=DARKNET_INDEX, id=parent_id, body=row)
            logging.info(f"写入OpenSearch darknet id={parent_id} result={result.get('result')}")

            # 创建以 _id 命名的子文件夹
            sub_folder = os.path.join(darknet_file_dir, _id)
            os.makedirs(sub_folder, exist_ok=True)

            # 保存 body 字段为 body.html 文件
            body = detail_data.get('body')
            if body:
                body_file_path = os.path.join(sub_folder, 'body.html')
                with open(body_file_path, 'w', encoding='utf-8') as f:
                    f.write(body)
                
                # 检查文件大小，跳过0KB文件
                if os.path.getsize(body_file_path) > 0:
                    # 插入文件记录并获取ID
                    file_id = insert_file_to_db(cursor, connection, 'body.html', body_file_path, parent_id)
                    if file_id:
                        child_file_ids.append(file_id)
                        child_file_names.append('body.html')
                else:
                    print(f"跳过0KB文件: body.html")

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

                        # 检查文件大小，跳过0KB文件
                        if os.path.getsize(img_file_path) > 0:
                            # 插入文件记录并获取ID
                            file_id = insert_file_to_db(cursor, connection, img_file_name, img_file_path, parent_id)
                            if file_id:
                                child_file_ids.append(file_id)
                                child_file_names.append(img_file_name)
                        else:
                            print(f"跳过0KB文件: {img_file_name}")
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
                            file_path = os.path.join(sub_folder, file_name)

                            # 检查文件是否存在
                            if not os.path.exists(file_path):
                                response = session.get(url, headers=headers, timeout=(3, 10))
                                response.raise_for_status()

                                with open(file_path, 'wb') as f:
                                    f.write(response.content)

                            # 替换链接为相对路径
                            relative_path = file_name
                            body = body.replace(url, relative_path)
                            
                            # 检查文件大小，跳过0KB文件
                            if os.path.getsize(file_path) > 0:
                                # 插入文件记录并获取ID
                                file_id = insert_file_to_db(cursor, connection, file_name, file_path, parent_id)
                                if file_id:
                                    child_file_ids.append(file_id)
                                    child_file_names.append(file_name)
                            else:
                                print(f"跳过0KB文件: {file_name}")
                        except Exception as e:
                            print(f"处理链接 {url} 失败: {e}")

                # 更新 body.html
                if os.path.exists(body_file_path) and os.path.getsize(body_file_path) > 0:
                    with open(body_file_path, 'w', encoding='utf-8') as f:
                        f.write(body)

            # 更新 child_file 字段
            if child_file_ids:
                update_darknet_child_file(parent_id, child_file_ids)
        messagedict={
                "_id":detail_data.get('_id'),
                "body_md5":detail_data.get('body_md5'),
                "description":description,
                "detail_parsing":json.dumps(detail_data.get('detail_parsing', {})),
                "event":json.dumps(detail_data.get('event', [])),
                "industry":json.dumps(detail_data.get('industry', [])),
                "is_read":detail_data.get('is_read'),
                "msg_author":msg_author,
                "msg_title_cn":detail_data.get('msg', {}).get('title_cn'),
                "msg_description":detail_data.get('msg', {}).get('description'),
                "msg_release_time":msg_release_time,
                "org":json.dumps(detail_data.get('org', [])),
                "page_type":json.dumps(detail_data.get('page_type', [])),
                "path":detail_data.get('path'),
                "regions_city":regions_city,
                "regions_country":regions_country,
                "regions_province":regions_province,
                "root_domain":detail_data.get('root_domain'),
                "source":detail_data.get('source'),
                "status_code":detail_data.get('status_code'),
                "tags":json.dumps(detail_data.get('tags', [])),
                "timestamp":detail_data.get('timestamp'),
                "title":detail_data.get('title'),
                "toplv_domain":detail_data.get('toplv_domain'),
                "update_time":detail_data.get('update_time'),
                "url":detail_data.get('url'),
                "user_id":detail_data.get('user_id'),
                "to_new":detail_data.get('to_new'),
                "body":detail_data.get('body'),
                "msg_sample_ss":msg_sample_ss,
                "msg_keyword":msg_keyword,
                "msg_webpage_ss":msg_webpage_ss,
                "child_file":child_file_ids
            }
        
        x_tag = {
            "producer": "Module/2",
            "data_type":1,
            "data_subtype":1002,
            "schema_id":100200,
            "datasource":3,
            "data_id":data_id,
            "task_id": 1,
            "file_id_list":child_file_ids
            }
        headers={
            "User-Agent":"Module/2",
            "Cookie":cookie,
            "Checksum":"123456",
            "X-Tag":json.dumps(x_tag)
            }
        data = {"message":json.dumps(messagedict),"id":data_id}
        print(messagedict)
        try:
        # 发送POST请求，verify=False忽略SSL证书验证（对应curl的-k选项）
            response = requests.post("http://192.168.1.10:8443/data/sendData", headers=headers, json=data, verify=False)
    
        # 检查响应状态码
            if response.status_code == 200:
                print("请求成功")
                print("响应内容:", response.text)
            else:
                print(f"请求失败，状态码: {response.status_code}")
                print("响应内容:", response.text)

        except requests.exceptions.RequestException as e:
            print(f"请求异常: {e}")            
            
    except Exception as e:
        logging.error(f"处理 item {_id} 出错: {e}")

def format_datetime_string(s: str) -> str:
    """
    格式化日期时间字符串为 "%Y-%m-%d %H:%M:%S" 格式：
    1. 验证是否符合ISO 8601格式（带或不带微秒）
    2. 将中间的T替换为空格
    3. 删除秒后面的小数点及微秒部分（如果存在）
    
    参数:
    s (str): 待格式化的字符串
    
    返回:
    str: 格式化后的字符串，失败时返回原始字符串
    """
    # 正则表达式验证ISO 8601格式（带或不带微秒）
    pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$'
    if re.match(pattern, s):
        try:
            # 使用datetime解析确保格式正确
            dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            # 解析失败时回退到正则替换
            return re.sub(r'T|(\.\d+)$', lambda m: ' ' if m.group(0) == 'T' else '', s)
    return s

def main():
    global api_count, api_start_time
    connection, cursor = connect_to_database()
    create_tables(cursor)
    align_darknet_id_map_auto_increment(connection, cursor)

    latest_timestamp = get_latest_darknet_timestamp()
    if latest_timestamp:
        start_time = latest_timestamp
        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    else:
        start_time = config["start_time"]
        end_time = config["end_time"]

    start_time=format_datetime_string(start_time)
    end_time=format_datetime_string(end_time)
    config["start_time"] = start_time
    config["end_time"] = end_time

    while True:
        # 初始化 next_id
        next_id = 0
        has_more_data = True

        while has_more_data:
            # 构建全部情报数据预览 API 请求体
            all_data_payload = {
                "query": f"timestamp>={config['start_time']}&&timestamp<={config['end_time']}",
                "query_type": "darknet",
                "next": next_id,
                "pagesize": 100,
                "zone_key_id": key
            }
            print(f"正在处理 next_id: {next_id}，时间范围: {config['start_time']} - {config['end_time']}")
            print(all_data_payload)
            try:
                # 控制API使用次数
                while api_count >= 2 and time.time() - api_start_time < 1:
                    time.sleep(0.1)
                api_count += 1
                if api_count >= 2:
                    api_start_time = time.time()
                    api_count = 0

                # 发送全部情报数据预览 API 请求
                all_data_response = session.post(all_data_api_url, json=all_data_payload, timeout=10)
                if all_data_response.status_code == 200:
                    all_data = all_data_response.json()
                    next_id = all_data.get('next', 0)
                    print(next_id)
                    data_list = all_data.get('data', [])

                    for item in data_list:
                        process_item(item, cursor, session, connection)

                    # 如果 next_id 为 0，表示没有更多数据
                    if next_id == 0:
                        has_more_data = False
                    else:
                        # 每处理完一页提交一次事务
                        connection.commit()
                        print(f"数据提交成功，继续处理 next_id: {next_id}")
                else:
                    print(f"请求失败，状态码: {all_data_response.status_code}")
                    has_more_data = False
            except Exception as e:
                print(f"处理数据出错: {e}，跳过该页")
                has_more_data = False

        # 所有数据处理完成，更新时间范围
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        config['start_time'] = config['end_time']
        config['end_time'] = current_time

        print("所有数据处理完成，更新时间范围，开始新一轮抓取")


if __name__ == "__main__":
    main()
