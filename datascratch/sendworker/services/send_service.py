import argparse
import hashlib
import json
import logging
import threading
import time
from datetime import datetime

import requests
from mysql.connector import Error

from sendworker.config import API_CONFIG_BY_MODULE
from sendworker.data_sources.mysql_source import MySQLDataSource
from sendworker.utils import extract_file_ids, to_datetime_string

logging.basicConfig(
    filename="SendDataFromDB.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

cookie = ""
running = True
data_source = MySQLDataSource()
_stop_events = {}
_stop_events_lock = threading.Lock()


def set_data_source(source):
    global data_source
    data_source = source


def _api_config(module):
    return API_CONFIG_BY_MODULE[9] if module == 9 else API_CONFIG_BY_MODULE[7]


def get_db_connection():
    return data_source.get_connection()


def get_stop_event(task_id):
    key = str(task_id)
    with _stop_events_lock:
        event = _stop_events.get(key)
        if event is None:
            event = threading.Event()
            _stop_events[key] = event
        return event


def clear_stop_event(task_id):
    get_stop_event(task_id).clear()


def stop_task(task_id):
    get_stop_event(task_id).set()
    logging.info("已设置task_id=%s停止标记", task_id)


def is_task_stopped(task_id):
    return get_stop_event(task_id).is_set()


def generate_signature(module=7):
    current_api_config = _api_config(module)
    timestamp = int(time.time())
    raw = f"{current_api_config['user_agent']}-{timestamp}-{current_api_config['auth_key']}"
    return timestamp, hashlib.sha256(raw.encode()).hexdigest()


def get_cookie(module=7):
    current_api_config = _api_config(module)
    global cookie
    if cookie:
        return cookie

    timestamp, signature = generate_signature(module)
    headers = {"User-Agent": current_api_config["user_agent"], "Content-Type": "application/json"}
    payload = {"requestType": current_api_config["request_type"], "time": timestamp, "token": signature}
    try:
        response = requests.post(current_api_config["connect_url"], headers=headers, json=payload, verify=False)
        if response.status_code == 200:
            cookie = response.headers.get("Set-Cookie", "")
            logging.info("获取cookie成功")
            return cookie
        logging.error("获取cookie失败，状态码: %s", response.status_code)
        logging.error("响应内容: %s", response.text)
    except requests.exceptions.RequestException as exc:
        logging.error("获取cookie异常: %s", exc)
    return ""


def send_data_to_api(data, data_type, data_subtype, data_id, file_ids=None, task_id=1, module=7):
    if is_task_stopped(task_id):
        logging.info("task_id=%s 已停止，跳过data_id=%s发送", task_id, data_id)
        return False

    current_api_config = _api_config(module)
    global cookie
    if not cookie:
        cookie = get_cookie(module)
    if not cookie:
        logging.error("没有获取到cookie，无法发送数据")
        return False

    datasource = 3 if data_subtype == 1002 else 2
    x_tag = {
        "producer": current_api_config["user_agent"],
        "data_type": data_type,
        "data_subtype": data_subtype,
        "data_id": data_id,
        "datasource": datasource,
        "schema_id": 100200 if data_subtype == 1002 else 100100,
        "task_id": task_id,
        "file_id_list": [int(fid) for fid in file_ids] if file_ids else [],
    }
    headers = {
        "User-Agent": current_api_config["user_agent"],
        "Cookie": cookie,
        "Checksum": "123456",
        "X-Tag": json.dumps(x_tag),
    }
    payload = {"message": json.dumps(data), "id": data_id}

    try:
        response = requests.post(current_api_config["send_url"], headers=headers, json=payload, verify=False)
        logging.debug("x_tag参数：%s", x_tag)
        if response.status_code == 200:
            logging.debug("API数据发送成功，data_id=%s, task_id=%s", data_id, task_id)
            logging.debug("API响应内容: %s", response.text)
            return True
        logging.error("API数据发送失败，状态码: %s", response.status_code)
        logging.error("API响应内容: %s", response.text)
        if response.status_code == 401:
            cookie = ""
            cookie = get_cookie(module)
            if cookie:
                headers["Cookie"] = cookie
                response = requests.post(current_api_config["send_url"], headers=headers, json=payload, verify=False)
                if response.status_code == 200:
                    logging.debug("重新获取cookie后发送成功，data_id=%s, task_id=%s", data_id, task_id)
                    return True
        return False
    except requests.exceptions.RequestException as exc:
        logging.error("API请求异常: %s", exc)
        return False


def _row_count(rows):
    return len(rows) if hasattr(rows, "__len__") else None


def _send_rows(rows, task_id, module, subtype, builder, sleep_seconds):
    all_success = True
    sent_count = 0
    for idx, item in enumerate(rows):
        if is_task_stopped(task_id):
            logging.info("task_id=%s 收到停止标记，停止发送%s数据，已处理%s条", task_id, "telegram" if subtype == 1001 else "darknet", sent_count)
            break
        file_ids = extract_file_ids(item)
        message_dict = builder(item)
        data_id = item.get("id", f"{'telegram' if subtype == 1001 else 'darknet'}_{idx}_{int(time.time())}")
        if is_task_stopped(task_id):
            logging.info("task_id=%s 收到停止标记，跳过data_id=%s", task_id, data_id)
            break
        success = send_data_to_api(message_dict, 1, subtype, data_id, file_ids, task_id, module=module)
        if not success:
            all_success = False
            logging.error("第 %s 条%s数据发送失败", idx + 1, "telegram" if subtype == 1001 else "darknet")
        sent_count += 1
        time.sleep(sleep_seconds)
    return all_success, sent_count


def _build_telegram_message(item):
    message_date = item.get("message_date")
    if hasattr(message_date, "strftime"):
        message_date = message_date.strftime("%Y-%m-%d")
    elif isinstance(message_date, str):
        text = message_date.strip()
        for sep in (" ", "T"):
            if sep in text:
                try:
                    message_date = datetime.fromisoformat(text.replace(" ", "T")).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    pass

    return {
        "_id": item.get("_id"),
        "chat_id": item.get("chat_id"),
        "chat_name": item.get("chat_name"),
        "content_text": item.get("content_text"),
        "content_text_md5": item.get("content_text_md5"),
        "event": str(item.get("event")) if item.get("event") is not None else "",
        "file_extension": item.get("file_extension"),
        "hot": item.get("hot"),
        "identical_msg_num": item.get("identical_msg_num"),
        "industry": str(item.get("industry")) if item.get("industry") is not None else "",
        "media_file_url": item.get("media_file_url"),
        "media_type": item.get("media_type"),
        "message_date": message_date,
        "message_id": item.get("message_id"),
        "message_time": to_datetime_string(item.get("message_time")),
        "message_time_old_list": str(item.get("message_time_old_list")) if item.get("message_time_old_list") is not None else "",
        "org": str(item.get("org")) if item.get("org") is not None else "",
        "regions": str(item.get("regions")) if item.get("regions") is not None else "",
        "sender_first_name": item.get("sender_first_name"),
        "sender_id": item.get("sender_id"),
        "sender_last_name": item.get("sender_last_name"),
        "sender_phone": item.get("sender_phone"),
        "sender_username": item.get("sender_username"),
        "tags": str(item.get("tags")) if item.get("tags") is not None else "",
        "page_type": str(item.get("page_type")) if item.get("page_type") is not None else "",
        "timestamp": to_datetime_string(item.get("timestamp")),
        "child_file": extract_file_ids(item),
    }


def _build_darknet_message(item):
    message_dict = {
        "_id": item.get("_id"),
        "body_md5": item.get("body_md5"),
        "description": item.get("description"),
        "detail_parsing": json.dumps(item.get("detail_parsing", {})) if isinstance(item.get("detail_parsing"), dict) else item.get("detail_parsing"),
        "event": json.dumps(item.get("event", [])) if isinstance(item.get("event"), list) else item.get("event"),
        "industry": json.dumps(item.get("industry", [])) if isinstance(item.get("industry"), list) else item.get("industry"),
        "is_read": item.get("is_read"),
        "msg_author": item.get("msg_author"),
        "msg_title_cn": item.get("msg_title_cn") or (item.get("msg", {}).get("title_cn") if isinstance(item.get("msg"), dict) else None),
        "msg_description": item.get("msg_description") or (item.get("msg", {}).get("description") if isinstance(item.get("msg"), dict) else None),
        "msg_release_time": item.get("msg_release_time"),
        "org": json.dumps(item.get("org", [])) if isinstance(item.get("org"), list) else item.get("org"),
        "page_type": json.dumps(item.get("page_type", [])) if isinstance(item.get("page_type"), list) else item.get("page_type"),
        "path": item.get("path"),
        "regions_city": item.get("regions_city"),
        "regions_country": item.get("regions_country"),
        "regions_province": item.get("regions_province"),
        "root_domain": item.get("root_domain"),
        "source": item.get("source"),
        "status_code": item.get("status_code"),
        "tags": json.dumps(item.get("tags", [])) if isinstance(item.get("tags"), list) else item.get("tags"),
        "timestamp": item.get("timestamp"),
        "title": item.get("title"),
        "toplv_domain": item.get("toplv_domain"),
        "update_time": item.get("update_time"),
        "url": item.get("url"),
        "user_id": item.get("user_id"),
        "to_new": item.get("to_new"),
        "body": item.get("body"),
        "msg_sample_ss": item.get("msg_sample_ss"),
        "msg_keyword": item.get("msg_keyword"),
        "msg_webpage_ss": item.get("msg_webpage_ss"),
        "child_file": extract_file_ids(item),
    }
    for key, value in list(message_dict.items()):
        message_dict[key] = to_datetime_string(value)
    return message_dict


def query_and_send_telegram_data(start_date, end_date, task_id=1, module=7):
    connection = None
    cursor = None
    try:
        if is_task_stopped(task_id):
            logging.info("task_id=%s 已停止，不启动telegram发送", task_id)
            return True
        connection = get_db_connection()
        if not connection:
            raise Exception("数据库连接失败")
        if hasattr(connection, "task_id"):
            connection.task_id = task_id

        cursor = connection.cursor(dictionary=True, buffered=True)
        start_date, end_date = data_source.resolve_telegram_time_range(cursor, task_id, module, start_date, end_date)
        results = data_source.fetch_telegram_rows(connection, start_date, end_date)
        result_count = _row_count(results)
        if result_count is not None:
            logging.info("查询到 %s 条符合条件的telegram数据", result_count)
        success, sent_count = _send_rows(results, task_id, module, 1001, _build_telegram_message, 0.1)
        if sent_count == 0:
            logging.info("没有查询到符合条件的数据")
            return True
        if result_count is None:
            logging.info("流式发送完成，共发送 %s 条telegram数据", sent_count)
        return success
    except Error as exc:
        logging.error("数据库操作错误: %s", exc)
        return False
    except Exception as exc:
        logging.error("执行过程中发生错误: %s", exc)
        return False
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
            logging.info("数据库连接已关闭")


def query_and_send_darknet_data(start_date, end_date, task_id=1, module=7):
    connection = None
    cursor = None
    try:
        if is_task_stopped(task_id):
            logging.info("task_id=%s 已停止，不启动darknet发送", task_id)
            return True
        connection = get_db_connection()
        if not connection:
            raise Exception("数据库连接失败")
        if hasattr(connection, "task_id"):
            connection.task_id = task_id

        cursor = connection.cursor(dictionary=True, buffered=True)
        start_date, end_date = data_source.resolve_darknet_time_range(cursor, task_id, module, start_date, end_date)
        results = data_source.fetch_darknet_rows(connection, start_date, end_date)
        result_count = _row_count(results)
        if result_count is not None:
            logging.info("查询到 %s 条符合条件的darknet数据", result_count)
        success, sent_count = _send_rows(results, task_id, module, 1002, _build_darknet_message, 0.5)
        if sent_count == 0:
            logging.info("没有查询到符合条件的数据")
            return True
        if result_count is None:
            logging.info("流式发送完成，共发送 %s 条darknet数据", sent_count)
        return success
    except Error as exc:
        logging.error("数据库操作错误: %s", exc)
        return False
    except Exception as exc:
        logging.error("执行过程中发生错误: %s", exc)
        return False
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
            logging.info("数据库连接已关闭")


def main():
    global running
    running = True
    parser = argparse.ArgumentParser(description="并行发送darknet和telegram数据到API")
    parser.add_argument("--start-date", type=str, required=True, help="开始日期，格式为YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, required=True, help="结束日期，格式为YYYY-MM-DD")
    parser.add_argument("--task-id", type=int, default=2, help="任务ID，默认为2")
    args = parser.parse_args()

    try:
        datetime.strptime(args.start_date, "%Y-%m-%d")
        datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError:
        logging.error("日期格式错误，请使用YYYY-MM-DD格式")
        print("日期格式错误，请使用YYYY-MM-DD格式")
        return

    if args.task_id <= 0:
        logging.error("任务ID必须为正整数")
        print("任务ID必须为正整数")
        return

    logging.info("开始发送数据，时间范围: %s 至 %s，任务ID: %s", args.start_date, args.end_date, args.task_id)
    print(f"开始发送数据，时间范围: {args.start_date} 至 {args.end_date}，任务ID: {args.task_id}")

    telegram_thread = threading.Thread(
        target=query_and_send_telegram_data,
        args=(args.start_date, args.end_date, args.task_id),
        name="TelegramThread",
    )
    darknet_thread = threading.Thread(
        target=query_and_send_darknet_data,
        args=(args.start_date, args.end_date, args.task_id),
        name="DarknetThread",
    )
    telegram_thread.start()
    darknet_thread.start()
    telegram_thread.join()
    darknet_thread.join()

    logging.info("所有数据发送线程已完成，正在等待命令接收线程停止...")
    running = False
    logging.info("程序已正常退出")
    print("程序已正常退出")
