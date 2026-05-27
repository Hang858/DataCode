import requests
import mysql.connector
import time
import os
import logging
from mysql.connector import Error
import mimetypes
import hashlib
import json
import urllib3
from opensearchpy import OpenSearch

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DB_CONFIG = {
    "host": "192.168.23.204",
    "database": "online",
    "user": "root",
    "password": "MyPass123!",
    "auth_plugin": "caching_sha2_password",
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
TELEGRAM_INDEX = "telegram_index"
os_client = OpenSearch(**OPENSEARCH_CONFIG)

# 配置日志记录，确保日志输出到标准输出以便被shell脚本捕获
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# 手动定义一些常见的 MIME 类型和后缀的映射
CUSTOM_MIME_MAP = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'application/pdf': '.pdf',
    'video/mp4': '.mp4',
    'audio/mpeg': '.mp3'
}

# 配置参数
# config = {
#     "start_time": "2025-04-13",
#     "end_time": "2025-04-14",
#     "key": "f7c23ae0c463de865aad3e0a2379df00",
#     "headers": {
#         "Content-Type": "application/json"
#     },
#     "api_url": "https://0.zone/api/im/",
#     "max_retries": 5,
#     "retry_delay": 5,
#     "api_retries": 3,
#     "api_retry_delay": 3,
#     "db_retries": 3,
#     "db_retry_delay": 3,
#     "file_retries": 3,
#     "file_retry_delay": 3,
#     "db_commit_retries": 3,
#     "db_commit_retry_delay": 3,
#     "api_max_calls_per_second": 2
# }

config = {
    "start_time": "2025-04-13",
    "end_time": "2025-04-14",
    "key": "f7c23ae0c463de865aad3e0a2379df00",
    "headers": {
        "Content-Type": "application/json"
    },
    "api_url": "https://0.zone/api/im/",
    "max_retries": 5,
    "retry_delay": 5,
    "api_retries": 3,
    "api_retry_delay": 3,
    "db_retries": 3,
    "db_retry_delay": 3,
    "file_retries": 3,
    "file_retry_delay": 3,
    "db_commit_retries": 3,
    "db_commit_retry_delay": 3,
    "api_max_calls_per_second": 2
}

# 创建文件存储目录
os.makedirs('telegram_file', exist_ok=True)

#抓取cookie
user_agent = "Module/2"
# timestamp=str(int(time.time()))
timestamp = int(time.time())
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
    response = requests.post("http://192.168.23.201:8443/system/connect", headers=header, json=data, verify=False)
    cookie=response.headers['Set-Cookie']
    if response.status_code == 200:
        print("dbus请求成功")
        print("dbus响应内容:", response.text)
    else:
        print(f"dbus请求失败，状态码: {response.status_code}")
        print("dbus响应内容:", response.text)

except requests.exceptions.RequestException as e:
    print(f"dbus请求异常: {e}") 


# 数据库连接重试机制（修改库名为online）
for attempt in range(config["max_retries"]):
    try:
        connection = mysql.connector.connect(
            **DB_CONFIG
        )
        if connection.is_connected():
            cursor = connection.cursor()
            logging.info("数据库连接成功")
            break
    except Error as e:
        if attempt < config["max_retries"] - 1:
            logging.warning(f"数据库连接尝试 {attempt + 1} 失败: {e}，将在 {config['retry_delay']} 秒后重试...")
            time.sleep(config['retry_delay'])
        else:
            logging.error(f"达到最大重试次数，数据库连接失败: {e}")
            raise

# 创建表（新增child_file字段）
try:
    create_table_query = """
    CREATE TABLE IF NOT EXISTS telegram_id_map (
        id INT AUTO_INCREMENT PRIMARY KEY,
        original_id VARCHAR(255) UNIQUE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """
    cursor.execute(create_table_query)

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
    cursor.execute(create_file_table_query)
    logging.info("表创建成功")
except Error as e:
    logging.error(f"表创建失败: {e}")
    raise

# 检查 OpenSearch telegram_index 是否存在数据
try:
    body = {
        "size": 1,
        "_source": ["timestamp"],
        "sort": [{"timestamp": {"order": "desc"}}],
        "query": {"match_all": {}},
    }
    response = os_client.search(index=TELEGRAM_INDEX, body=body)
    hits = response.get("hits", {}).get("hits", [])
    if hits and hits[0].get("_source", {}).get("timestamp"):
        config["start_time"] = str(hits[0]["_source"]["timestamp"]).replace("T", " ")
except Exception as e:
    logging.warning(f"检查 OpenSearch telegram_index 数据时出错: {e}")

# 初始化 API 调用计数器和时间戳
api_call_count = 0
last_api_call_time = time.time()

# 检查数据库连接状态的函数
def check_connection(connection, cursor):
    try:
        connection.ping(reconnect=True, attempts=3, delay=5)
        if not connection.is_connected():
            for attempt in range(config["max_retries"]):
                try:
                    connection = mysql.connector.connect(**DB_CONFIG)
                    if connection.is_connected():
                        cursor = connection.cursor()
                        logging.info("重新连接数据库成功")
                        break
                except Error as e:
                    if attempt < config["max_retries"] - 1:
                        logging.warning(f"重新连接数据库尝试 {attempt + 1} 失败: {e}，将在 {config['retry_delay']} 秒后重试...")
                        time.sleep(config['retry_delay'])
                    else:
                        logging.error(f"达到最大重试次数，重新连接数据库失败: {e}")
                        raise
    except Error as e:
        logging.error(f"检查数据库连接时出错: {e}")
        raise
    return connection, cursor


def get_max_telegram_id():
    body = {
        "size": 1,
        "_source": ["id"],
        "sort": [{"id": {"order": "desc"}}],
        "query": {"match_all": {}},
    }
    try:
        response = os_client.search(index=TELEGRAM_INDEX, body=body)
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return 0
        source_id = hits[0].get("_source", {}).get("id")
        return int(source_id if source_id is not None else hits[0].get("_id"))
    except Exception as exc:
        logging.warning(f"查询OpenSearch最大telegram id失败: {exc}")
        return 0


def align_telegram_id_map_auto_increment(connection, cursor):
    cursor.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM telegram_id_map")
    _map_count, map_max_id = cursor.fetchone()
    next_id = max(int(map_max_id), get_max_telegram_id()) + 1
    if next_id > 1:
        cursor.execute(f"ALTER TABLE telegram_id_map AUTO_INCREMENT = {next_id}")
        connection.commit()


def find_existing_telegram_id(original_id):
    body = {
        "size": 1,
        "_source": ["id"],
        "query": {"term": {"original_id": original_id}},
    }
    response = os_client.search(index=TELEGRAM_INDEX, body=body)
    hits = response.get("hits", {}).get("hits", [])
    if not hits:
        return None
    source_id = hits[0].get("_source", {}).get("id")
    return int(source_id if source_id is not None else hits[0].get("_id"))


def get_or_create_telegram_id(connection, cursor, original_id):
    cursor.execute("SELECT id FROM telegram_id_map WHERE original_id = %s", (original_id,))
    result = cursor.fetchone()
    if result:
        return result[0]
    existing_id = find_existing_telegram_id(original_id)
    if existing_id is not None:
        cursor.execute(
            "INSERT INTO telegram_id_map (id, original_id) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE original_id = VALUES(original_id)",
            (existing_id, original_id),
        )
        connection.commit()
        return existing_id
    cursor.execute(
        "INSERT INTO telegram_id_map (original_id) VALUES (%s) "
        "ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)",
        (original_id,),
    )
    connection.commit()
    return cursor.lastrowid


def update_telegram_child_file(telegram_id, child_file):
    response = os_client.get(index=TELEGRAM_INDEX, id=telegram_id, ignore=[404])
    if not response or response.get("found") is False:
        logging.warning(f"OpenSearch未找到telegram记录: {telegram_id}")
        return
    existing = (response.get("_source") or {}).get("child_file") or ""
    updated = ",".join(part for part in [existing.rstrip(","), child_file] if part)
    os_client.update(index=TELEGRAM_INDEX, id=telegram_id, body={"doc": {"child_file": updated}})


align_telegram_id_map_auto_increment(connection, cursor)

while True:
    start_time = time.time()
    count = 2000000
    config["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    query = f"timestamp>={config['start_time']}&&timestamp<={config['end_time']}"

    next_id=0
    for _i in range(count):
        payload = {
            "query": query,
            "query_type": "telegram",
            "next": next_id,
            "pagesize": 100,
            "zone_key_id": config["key"],
        }

        # 检查 API 调用次数限制
        current_time = time.time()
        if current_time - last_api_call_time < 1:
            if api_call_count >= config["api_max_calls_per_second"]:
                wait_time = 1 - (current_time - last_api_call_time)
                logging.info(f"达到 API 调用次数限制，等待 {wait_time:.2f} 秒")
                time.sleep(wait_time)
                last_api_call_time = time.time()
                api_call_count = 1
            else:
                api_call_count += 1
        else:
            last_api_call_time = current_time
            api_call_count = 1

        for api_attempt in range(config["api_retries"]):
            try:
                # 发送 POST 请求
                logging.info(f"发送请求: {payload}")
                response = requests.post(config["api_url"], json=payload, headers=config["headers"])
                logging.info(f"请求响应: {response.status_code}")

                # 检查响应状态码
                if response.status_code == 200:
                    # 解析 JSON 数据
                    try:
                        data = response.json()
                    except ValueError as e:
                        logging.error(f"解析 JSON 数据失败: {e}")
                        break
                    if data.get('code', 0) != 0:
                        print(data)
                        break
                    
                    next_id = data.get('next', 0)
                    child_file_ids=[]
                    child_file_names=[]
                    data_id=0

                    # 遍历数据并插入到 MySQL 数据库
                    for item in data.get('data', []):
                        _source = item.get('_source', {})
                        connection, cursor = check_connection(connection, cursor)
                        file_ids = []  # 用于存储当前记录对应的文件ID
                        telegram_id = get_or_create_telegram_id(connection, cursor, item.get('_id'))
                        data_id=telegram_id
                        row = {
                            "id": telegram_id,
                            "original_id": item.get('_id'),
                            "chat_id": _source.get('chat_id'),
                            "chat_name": _source.get('chat_name'),
                            "content_text": _source.get('content_text'),
                            "content_text_md5": _source.get('content_text_md5'),
                            "event": str(_source.get('event')),
                            "file_extension": _source.get('file_extension'),
                            "hot": _source.get('hot'),
                            "identical_msg_num": _source.get('identical_msg_num'),
                            "industry": str(_source.get('industry')),
                            "media_file_url": _source.get('media_file_url'),
                            "media_type": _source.get('media_type'),
                            "message_date": _source.get('message_date'),
                            "message_id": _source.get('message_id'),
                            "message_time": _source.get('message_time'),
                            "message_time_old_list": str(_source.get('message_time_old_list')),
                            "org": str(_source.get('org')),
                            "regions": str(_source.get('regions')),
                            "sender_first_name": _source.get('sender_first_name'),
                            "sender_id": _source.get('sender_id'),
                            "sender_last_name": _source.get('sender_last_name'),
                            "sender_phone": _source.get('sender_phone'),
                            "sender_username": _source.get('sender_username'),
                            "tags": str(_source.get('tags')),
                            "page_type": str(_source.get('page_type')),
                            "timestamp": _source.get('timestamp'),
                            "child_file": "",
                        }
                        response = os_client.index(index=TELEGRAM_INDEX, id=telegram_id, body=row)
                        logging.info(f"写入OpenSearch telegram id={telegram_id} result={response.get('result')}")
                        # 处理文件下载和存储
                        media_type = _source.get('media_type')
                        media_url = _source.get('media_file_url')
                        if media_type and media_url:
                            file_id = item.get('_id')
                            if not file_id:
                                logging.warning("文件 ID 为空，跳过文件处理")
                                continue
                            file_path = os.path.join('telegram_file', file_id)
                            # 根据 Content-Type 获取文件后缀
                            content_type = None
                            file_extension = None
                            if file_path:
                                file_response = requests.head(media_url)
                                content_type = file_response.headers.get('Content-Type')
                                file_extension = CUSTOM_MIME_MAP.get(content_type)
                                if not file_extension:
                                    file_extension = mimetypes.guess_extension(content_type)
                                if file_extension:
                                    new_file_path = os.path.join('telegram_file', file_id + file_extension)
                                else:
                                    new_file_path = file_path

                                # 检查文件是否已存在
                                if os.path.exists(new_file_path):
                                    logging.info(f"文件 {new_file_path} 已存在，跳过下载")
                                    content_size = os.path.getsize(new_file_path)
                                    file_name = os.path.basename(new_file_path)
                                else:
                                    for file_attempt in range(config["file_retries"]):
                                        try:
                                            file_response = requests.get(media_url, stream=True)
                                            file_response.raise_for_status()

                                            with open(file_path, 'wb') as f:
                                                for chunk in file_response.iter_content(chunk_size=8192):
                                                    f.write(chunk)

                                            if file_extension:
                                                new_file_path = os.path.join('telegram_file', file_id + file_extension)
                                                os.rename(file_path, new_file_path)
                                                file_path = new_file_path

                                            content_size = os.path.getsize(file_path)
                                            file_name = os.path.basename(new_file_path)

                                            # 确定 data_subtype
                                            if file_extension.lower() == '.txt':
                                                data_subtype = 0x2001
                                            elif file_extension.lower() in ['.doc', '.docx', '.pdf', '.xls', '.xlsx']:
                                                data_subtype = 0x2002
                                            elif file_extension.lower() in ['.jpeg', '.jpg', '.png']:
                                                data_subtype = 0x2003
                                            elif file_extension.lower() in ['.zip', '.7z', '.rar']:
                                                data_subtype = 0x2004
                                            elif file_extension.lower() in ['.html', '.htm']:
                                                data_subtype = 0x2005
                                            elif file_extension.lower() in ['.mp3', '.wav', '.ogg']:
                                                data_subtype = 0x2006
                                            else:
                                                data_subtype = 0x2007

                                            # 插入file表并获取file_id
                                            insert_file_query = """
                                            INSERT INTO file (
                                                data_type, data_subtype, producer_id, datasource, 
                                                file_name, file_size, parent_id, file_path
                                            )
                                            VALUES (
                                                2, %s, '', 2, %s, %s, %s, %s
                                            )
                                            ON DUPLICATE KEY UPDATE  
                                                data_type = VALUES(data_type),
                                                data_subtype = VALUES(data_subtype),
                                                producer_id = VALUES(producer_id),
                                                datasource = VALUES(datasource),
                                                file_name = VALUES(file_name),
                                                file_size = VALUES(file_size),
                                                parent_id = VALUES(parent_id),
                                                file_path = VALUES(file_path)
                                            """
                                            connection, cursor = check_connection(connection, cursor)
                                            cursor.execute(insert_file_query, (data_subtype, file_name, content_size, telegram_id, file_path))
                                            connection.commit()  # 提交以获取LAST_INSERT_ID
                                            
                                            # 获取刚插入的file_id
                                            file_id = cursor.lastrowid
                                            # cursor.execute("SELECT LAST_INSERT_ID()")
                                            # file_id = cursor.fetchone()[0]
                                            file_ids.append(str(file_id))  # 存储文件ID
                                            child_file_names.append(file_name)

                                            logging.info(f"文件 {file_id} 下载并保存成功，文件路径: {file_path}")
                                            break
                                        except requests.exceptions.RequestException as e:
                                            if file_attempt < config["file_retries"] - 1:
                                                logging.warning(f"下载文件 {file_id} 尝试 {file_attempt + 1} 失败: {e}，将在 {config['file_retry_delay']} 秒后重试...")
                                                time.sleep(config['file_retry_delay'])
                                            else:
                                                logging.error(f"达到最大重试次数，下载文件 {file_id} 失败: {e}")
                                        except FileNotFoundError as e:
                                            logging.error(f"文件操作出错 {file_id}: {e}")
                                            break
                                        except Exception as e:
                                            if file_attempt < config["file_retries"] - 1:
                                                logging.warning(f"处理文件 {file_id} 尝试 {file_attempt + 1} 出错: {e}，将在 {config['file_retry_delay']} 秒后重试...")
                                                time.sleep(config['file_retry_delay'])
                                            else:
                                                logging.error(f"达到最大重试次数，处理文件 {file_id} 出错: {e}")

                        # 更新telegram记录的child_file字段
                        if file_ids:
                            child_file = ','.join(file_ids)
                            update_telegram_child_file(telegram_id, child_file)
                            logging.info(f"更新OpenSearch child_file字段为: {child_file}")
                        child_file_ids=file_ids
                        messagedict={
                            '_id':item.get('_id'),
                            'chat_id':_source.get('chat_id'),
                            'chat_name':_source.get('chat_name'),
                            'content_text':_source.get('content_text'),
                            'content_text_md5':_source.get('content_text_md5'),
                            'event':str(_source.get('event')),
                            'file_extension':_source.get('file_extension'),
                            'hot':_source.get('hot'),
                            'identical_msg_num':_source.get('identical_msg_num'),
                            'industry':str(_source.get('industry')),
                            'media_file_url':_source.get('media_file_url'),
                            'media_type':_source.get('media_type'),
                            'message_date':_source.get('message_date'),
                            'message_id':_source.get('message_id'),
                            'message_time':_source.get('message_time'),
                            'message_time_old_list':str(_source.get('message_time_old_list')),
                            'org':str(_source.get('org')),
                            'regions':str(_source.get('regions')),
                            'sender_first_name':_source.get('sender_first_name'),
                            'sender_id':_source.get('sender_id'),
                            'sender_last_name':_source.get('sender_last_name'),
                            'sender_phone':_source.get('sender_phone'),
                            'sender_username':_source.get('sender_username'),
                            'tags':str(_source.get('tags')),
                            'page_type':str(_source.get('page_type')),
                            'timestamp':_source.get('timestamp'),
                            "child_file":file_ids,
                            }

                        
                        # x_tag = {
                        #     "data_type":1,
                        #     "data_subtype":0x1001,
                        #     "schema_id":0x100100,
                        #     "producer_id":0,
                        #     "datasource":2,
                        #     "data_id":data_id,
                        #     "task_id":[1],
                        #     "flow_id":[],
                        #     "file_id_list":[int(s) for s in child_file_ids],
                        #     "file_name_list":child_file_names
                        #     }

                        x_tag = { 
                            "producer": "Module/2", 
                            "data_type": 1, 
                            "data_subtype": 1001,
                            "data_id": data_id,
                            "datasource": 2,
                            "schema_id": 100100, 
                            "task_id": 1,
                            "file_id_list":[int(s) for s in child_file_ids]
                            }
                        
                        headers={
                            "User-Agent":user_agent,
                            "Cookie":cookie,
                            "Checksum":"123456",
                            "X-Tag":json.dumps(x_tag)
                            }
                        # data = {"message":json.dumps(messagedict),"id":data_id}
                        data = {"message": messagedict, "id": data_id}
                        # print("data", data)
                        # print(messagedict)
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

                    # 提交事务（主数据插入已在每条记录中提交，此处主要处理可能的批量操作）
                    connection, cursor = check_connection(connection, cursor)
                    for db_commit_attempt in range(config["db_commit_retries"]):
                        try:
                            connection.commit()
                            logging.info(f"第 {_i + 1} 次数据处理完成")
                            break
                        except Error as e:
                            if db_commit_attempt < config["db_commit_retries"] - 1:
                                logging.warning(f"第 {_i + 1} 次事务提交尝试 {db_commit_attempt + 1} 失败: {e}，将在 {config['db_commit_retry_delay']} 秒后重试...")
                                time.sleep(config['db_commit_retry_delay'])
                            else:
                                logging.error(f"达到最大重试次数，第 {_i + 1} 次事务提交失败: {e}")
                                connection.rollback()
                    break
                else:
                    logging.error(f"请求失败，状态码: {response.status_code}")
                    if api_attempt < config["api_retries"] - 1:
                        logging.warning(f"API 请求尝试 {api_attempt + 1} 失败，将在 {config['api_retry_delay']} 秒后重试...")
                        time.sleep(config['api_retry_delay'])
                    else:
                        logging.error(f"达到最大重试次数，API 请求失败")
            except requests.RequestException as e:
                if api_attempt < config["api_retries"] - 1:
                    logging.warning(f"API 请求尝试 {api_attempt + 1} 出错: {e}，将在 {config['api_retry_delay']} 秒后重试...")
                    time.sleep(config['api_retry_delay'])
                else:
                    logging.error(f"达到最大重试次数，API 请求出错: {e}")

    # 更新起始时间和结束时间
    config["start_time"] = config["end_time"]
