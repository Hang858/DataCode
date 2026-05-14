import logging
import time
from datetime import datetime, timedelta

import mysql.connector
from mysql.connector import Error

from sendworker.config import DB_CONFIG
from sendworker.data_sources.base import BaseDataSource
from sendworker.utils import to_datetime_string


class MySQLDataSource(BaseDataSource):
    def get_connection(self):
        for attempt in range(DB_CONFIG["max_retries"]):
            try:
                connection = mysql.connector.connect(
                    host=DB_CONFIG["host"],
                    database=DB_CONFIG["database"],
                    user=DB_CONFIG["user"],
                    password=DB_CONFIG["password"],
                    auth_plugin=DB_CONFIG["auth_plugin"],
                )
                if connection.is_connected():
                    logging.info("数据库连接成功")
                    return connection
            except Error as exc:
                if attempt < DB_CONFIG["max_retries"] - 1:
                    logging.warning(
                        "数据库连接尝试 %s 失败: %s，将在 %s 秒后重试...",
                        attempt + 1,
                        exc,
                        DB_CONFIG["retry_delay"],
                    )
                    time.sleep(DB_CONFIG["retry_delay"])
                else:
                    logging.error("达到最大重试次数，数据库连接失败: %s", exc)
                    raise
        return None

    def resolve_telegram_time_range(self, cursor, task_id, module, start_date, end_date):
        if module == 7:
            cursor.execute("SELECT start_date, end_date FROM param_submissions WHERE task_id = %s", (task_id,))
            param_result = cursor.fetchone()
            if param_result:
                start_date = to_datetime_string(param_result["start_date"])
                end_date = to_datetime_string(param_result["end_date"])
                logging.info("从param_submissions表中获取到task_id %s 的时间范围: %s 至 %s", task_id, start_date, end_date)
        else:
            cursor.execute("SELECT time_period, send_time, telegram, darknet FROM param_config WHERE task_id = %s", (task_id,))
            param_result = cursor.fetchone()
            if param_result:
                current_date = datetime.now().date()
                start_date = current_date - timedelta(days=int(param_result["send_time"]))
                start_date = to_datetime_string(start_date)
                end_date = to_datetime_string(current_date)
                logging.info("根据send_time计算得到时间范围: %s 至 %s", start_date, end_date)
        return start_date, end_date

    def fetch_submission_flags(self, cursor, task_id):
        cursor.execute("SELECT telegram, darknet FROM param_submissions WHERE task_id = %s", (task_id,))
        result = cursor.fetchone()
        if not result:
            return None
        return {
            "telegram": int(result.get("telegram", 0)) == 1,
            "darknet": int(result.get("darknet", 0)) == 1,
        }

    def fetch_task_filters(self, cursor, task_id, dataset):
        try:
            cursor.execute(
                """
                SELECT search_field, operator, search_value, connector
                FROM param_task_filters
                WHERE task_id = %s AND dataset = %s AND enabled = 1
                ORDER BY sort_order ASC, id ASC
                """,
                (task_id, dataset),
            )
            results = cursor.fetchall()
        except Error as exc:
            logging.warning("读取task_id=%s dataset=%s过滤条件失败: %s", task_id, dataset, exc)
            return []
        filters = []
        for result in results or []:
            search_value = (result.get("search_value") or "").strip()
            if not search_value:
                continue
            filters.append(
                {
                    "search_field": (result.get("search_field") or "").strip(),
                    "operator": (result.get("operator") or "auto").strip(),
                    "search_value": search_value,
                    "connector": (result.get("connector") or "AND").strip().upper(),
                }
            )
        return filters

    def resolve_darknet_time_range(self, cursor, task_id, module, start_date, end_date):
        cursor.execute("SELECT start_date, end_date FROM param_submissions WHERE task_id = %s", (task_id,))
        param_result = cursor.fetchone()
        if param_result:
            start_date = to_datetime_string(param_result["start_date"])
            end_date = to_datetime_string(param_result["end_date"])
            logging.info("从param_submissions表中获取到task_id %s 的时间范围: %s 至 %s", task_id, start_date, end_date)
        return start_date, end_date

    def fetch_telegram_rows(self, connection, start_date, end_date):
        cursor = connection.cursor(dictionary=True, buffered=True)
        try:
            cursor.execute("SELECT * FROM telegram WHERE message_date BETWEEN %s AND %s", (start_date, end_date))
            return cursor.fetchall()
        finally:
            cursor.close()

    def fetch_darknet_rows(self, connection, start_date, end_date):
        start_timestamp = f"{start_date}T00:00:00.000000"
        end_timestamp = f"{end_date}T23:59:59.999999"
        cursor = connection.cursor(dictionary=True, buffered=True)
        try:
            cursor.execute("SELECT * FROM darknet WHERE timestamp BETWEEN %s AND %s", (start_timestamp, end_timestamp))
            return cursor.fetchall()
        finally:
            cursor.close()

    def fetch_scheduler_configs(self, cursor, task_id=None):
        if task_id:
            query = "SELECT id, task_id, created_at, time_period, send_time, telegram, darknet FROM param_config WHERE task_id = %s"
            cursor.execute(query, (task_id,))
        else:
            query = "SELECT id, task_id, created_at, time_period, send_time, telegram, darknet FROM param_config"
            cursor.execute(query)
        return cursor.fetchall()
