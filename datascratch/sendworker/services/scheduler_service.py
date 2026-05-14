import logging
import threading
import time
from datetime import datetime, timedelta

from mysql.connector import Error

from sendworker.services import send_service

logging.basicConfig(
    filename="task_scheduler.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

global_threads = []


class TaskScheduler(threading.Thread):
    def __init__(self, task_id=None):
        super().__init__()
        self.task_id = task_id
        self.daemon = True
        self.name = f"TaskScheduler_task_{task_id}" if task_id else "TaskScheduler"

    def run(self):
        logging.info("%s 已启动", self.name)
        while True:
            try:
                self.check_and_start_tasks()
                logging.info("%s 本次检查结束，等待1小时后再次检查...", self.name)
                time.sleep(3600)
            except Exception as exc:
                logging.error("%s 运行出错: %s", self.name, exc)
                time.sleep(60)

    def get_db_connection(self):
        return send_service.get_db_connection()

    def check_and_start_tasks(self):
        connection = None
        cursor = None
        try:
            connection = self.get_db_connection()
            if not connection:
                raise Exception("数据库连接失败")

            cursor = connection.cursor(dictionary=True)
            configs = send_service.data_source.fetch_scheduler_configs(cursor, self.task_id)
            if not configs:
                logging.info("param_config表中没有找到配置记录")
                return

            current_date = datetime.now().date()
            for config in configs:
                task_id = config.get("task_id")
                created_at = config.get("created_at")
                time_period = int(config.get("time_period", 0))
                send_time = int(config.get("send_time", 0))
                telegram_enabled = config.get("telegram", 0) == 1
                darknet_enabled = config.get("darknet", 0) == 1

                if isinstance(created_at, str):
                    try:
                        created_at = datetime.strptime(created_at, "%Y-%m-%d").date()
                    except ValueError:
                        logging.error("任务ID %s 的created_at格式错误: %s", task_id, created_at)
                        continue

                days_passed = (current_date - created_at).days
                logging.info(
                    "任务ID %s: 创建日期 %s, 当前日期 %s, 已过天数 %s, 配置间隔 %s天",
                    task_id,
                    created_at,
                    current_date,
                    days_passed,
                    time_period,
                )

                if days_passed >= time_period:
                    logging.info("任务ID %s: 时间间隔已满足条件，准备启动任务", task_id)
                    start_date = current_date - timedelta(days=send_time)
                    end_date = current_date
                    start_date_str = start_date.strftime("%Y-%m-%d")
                    end_date_str = end_date.strftime("%Y-%m-%d")
                    logging.info("任务ID %s: 数据查询时间范围: %s 至 %s", task_id, start_date_str, end_date_str)

                    if telegram_enabled:
                        telegram_thread = threading.Thread(
                            target=send_service.query_and_send_telegram_data,
                            args=(start_date_str, end_date_str, task_id),
                            kwargs={"module": 9},
                            name=f"TelegramThread_task_{task_id}",
                        )
                        global_threads.append(telegram_thread)
                        telegram_thread.start()
                        logging.info("已启动telegram线程: %s", telegram_thread.name)

                    if darknet_enabled:
                        darknet_thread = threading.Thread(
                            target=send_service.query_and_send_darknet_data,
                            args=(start_date_str, end_date_str, task_id),
                            kwargs={"module": 9},
                            name=f"DarknetThread_task_{task_id}",
                        )
                        global_threads.append(darknet_thread)
                        darknet_thread.start()
                        logging.info("已启动darknet线程: %s", darknet_thread.name)
                else:
                    logging.info("任务ID %s: 时间间隔不足，还需等待 %s 天", task_id, time_period - days_passed)
        except Error as exc:
            logging.error("数据库操作错误: %s", exc)
        except Exception as exc:
            logging.error("执行过程中发生错误: %s", exc)
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()
                logging.info("数据库连接已关闭")


def start_task_scheduler(task_id=None):
    scheduler = TaskScheduler(task_id)
    scheduler.start()
    return scheduler


def get_active_threads():
    active_threads = []
    for thread in global_threads[:]:
        if thread.is_alive():
            active_threads.append(thread)
        else:
            global_threads.remove(thread)
    return active_threads


def wait_for_all_threads():
    for thread in get_active_threads():
        thread.join()
        logging.info("线程已完成: %s", thread.name)
