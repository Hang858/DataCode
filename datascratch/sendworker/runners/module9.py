import logging

from sendworker.config import MODULE_9_RECV_API_CONFIG, get_data_source_name
from sendworker.data_sources.factory import build_data_source
from sendworker.receiver import create_receiver
from sendworker.services import send_service
from sendworker.services.scheduler_service import start_task_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

send_service.set_data_source(build_data_source(get_data_source_name(9)))

receiver = create_receiver(MODULE_9_RECV_API_CONFIG)


def _start_scheduler(task_id, *_args):
    scheduler_thread = start_task_scheduler(task_id)
    receiver.telegram_threads.append(scheduler_thread)


receiver.on_start_telegram = _start_scheduler
receiver.on_start_darknet = _start_scheduler


def receive_commands():
    return receiver.receive_commands()


def main():
    receiver.start().join()
