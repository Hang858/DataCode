import logging
import threading

from sendworker.config import (
    DEFAULT_DIRECT_END_DATE,
    DEFAULT_DIRECT_START_DATE,
    MODULE_7_RECV_API_CONFIG,
    get_data_source_name,
)
from sendworker.data_sources.factory import build_data_source
from sendworker.receiver import create_receiver
from sendworker.services import send_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

send_service.set_data_source(build_data_source(get_data_source_name(7)))

receiver = create_receiver(MODULE_7_RECV_API_CONFIG)


def _submission_flags(task_id):
    connection = None
    cursor = None
    try:
        connection = send_service.get_db_connection()
        if not connection:
            logging.error("task_id=%s 读取param_submissions开关失败: 数据库连接失败", task_id)
            return None
        cursor = connection.cursor(dictionary=True, buffered=True)
        return send_service.data_source.fetch_submission_flags(cursor, task_id)
    except Exception as exc:
        logging.error("task_id=%s 读取param_submissions开关失败: %s", task_id, exc)
        return None
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def _start_telegram(task_id, start_date, end_date):
    flags = _submission_flags(task_id)
    if flags is not None and not flags.get("telegram", False):
        logging.info("task_id=%s param_submissions.telegram=0，跳过telegram发送", task_id)
        return
    thread = threading.Thread(
        target=send_service.query_and_send_telegram_data,
        args=(start_date or DEFAULT_DIRECT_START_DATE, end_date or DEFAULT_DIRECT_END_DATE, task_id),
        name=f"TelegramThread_task_{task_id}",
    )
    thread.start()
    receiver.telegram_threads.append(thread)


def _start_darknet(task_id, start_date, end_date):
    flags = _submission_flags(task_id)
    if flags is not None and not flags.get("darknet", False):
        logging.info("task_id=%s param_submissions.darknet=0，跳过darknet发送", task_id)
        return
    thread = threading.Thread(
        target=send_service.query_and_send_darknet_data,
        args=(start_date or DEFAULT_DIRECT_START_DATE, end_date or DEFAULT_DIRECT_END_DATE, task_id),
        name=f"DarknetThread_task_{task_id}",
    )
    thread.start()
    receiver.darknet_threads.append(thread)


receiver.on_start_telegram = _start_telegram
receiver.on_start_darknet = _start_darknet


def receive_commands():
    return receiver.receive_commands()


def main():
    receiver.start().join()
