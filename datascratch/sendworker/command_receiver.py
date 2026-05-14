import base64
import hashlib
import json
import logging
import threading
import time

import requests
from gmssl import Sm4Ctr

from sendworker.services import send_service


def build_recv_api_config(module, connect_url, recv_url, auth_key, request_type=40, command_check_interval=5):
    return {
        "connect_url": connect_url,
        "recv_url": recv_url,
        "user_agent": f"Module/{module}",
        "auth_key": auth_key,
        "request_type": int(request_type),
        "command_check_interval": command_check_interval,
    }


class CommandReceiver:
    def __init__(self, recv_api_config, on_start_telegram=None, on_start_darknet=None):
        self.recv_api_config = recv_api_config
        self.on_start_telegram = on_start_telegram
        self.on_start_darknet = on_start_darknet
        self.cookie = ""
        self.running = True
        self.telegram_threads = []
        self.darknet_threads = []

    def generate_signature(self):
        timestamp = int(time.time())
        raw = f"{self.recv_api_config['user_agent']}-{timestamp}-{self.recv_api_config['auth_key']}"
        return timestamp, hashlib.sha256(raw.encode()).hexdigest()

    def get_cookie(self):
        if self.cookie:
            return self.cookie

        timestamp, signature = self.generate_signature()
        headers = {
            "User-Agent": self.recv_api_config["user_agent"],
            "Content-Type": "application/json",
        }
        payload = {
            "requestType": self.recv_api_config["request_type"],
            "time": timestamp,
            "token": signature,
        }

        try:
            response = requests.post(
                self.recv_api_config["connect_url"],
                headers=headers,
                json=payload,
                verify=False,
            )
            if response.status_code == 200:
                self.cookie = response.headers.get("Set-Cookie", "")
                logging.info("获取cookie成功")
                return self.cookie
            logging.error("获取cookie失败，状态码: %s", response.status_code)
            logging.error("响应内容: %s", response.text)
        except requests.exceptions.RequestException as exc:
            logging.error("获取cookie异常: %s", exc)
        return ""

    def decrypt_command_pair(self, json_data, encrypted_data):
        try:
            combined = f"{json_data}-{self.recv_api_config['auth_key']}"
            sha256_hash = hashlib.sha256(combined.encode("utf-8")).digest()
            key = sha256_hash[:16]
            iv = sha256_hash[16:]
            ciphertext = base64.b64decode(encrypted_data)
            sm4_dec = Sm4Ctr(key, iv)
            decrypted_data = sm4_dec.update(ciphertext)
            decrypted_data += sm4_dec.finish()
            return decrypted_data.decode("utf-8")
        except Exception as exc:
            logging.error("解密命令对 %s, %s 时出错: %s", json_data, encrypted_data, exc)
            return ""

    def handle_received_command(self, lines):
        try:
            for i in range(0, len(lines), 2):
                pair = lines[i:i + 2]
                if len(pair) == 2:
                    try:
                        lines[i + 1] = self.decrypt_command_pair(pair[0], pair[1])
                    except Exception as exc:
                        logging.error("解密命令对 %s 时出错: %s", pair, exc)
                else:
                    logging.warning("剩余未成对的命令行: %s", pair)
            return lines
        except Exception as exc:
            logging.error("处理命令时出错: %s", exc)
            return lines

    def stop_threads_by_task_id(self, task_id):
        send_service.stop_task(task_id)
        for thread_list, label in ((self.telegram_threads, "telegram"), (self.darknet_threads, "darknet")):
            threads_to_remove = []
            logging.info("检查%s线程中task_id为 %s 的线程...", label, task_id)
            for thread in thread_list:
                if f"task_{task_id}" in thread.name:
                    if thread.is_alive():
                        logging.info("已通知%s线程 %s 停止，等待最多1秒...", label, thread.name)
                        thread.join(1.0)
                        if thread.is_alive():
                            logging.info("%s线程 %s 仍在退出中，将由发送循环检查停止标记后结束", label, thread.name)
                        else:
                            logging.info("%s线程 %s 已停止", label, thread.name)
                    threads_to_remove.append(thread)
            for thread in threads_to_remove:
                if thread in thread_list:
                    thread_list.remove(thread)

    def execute_command(self, lines):
        result = []
        try:
            if len(lines) % 2 != 0:
                return result

            for i in range(0, len(lines), 2):
                json_line = lines[i]
                data_line = lines[i + 1] if i + 1 < len(lines) else None
                pair_result = {"pair_index": i // 2 + 1, "schema_id": None, "task_id": None}

                try:
                    if json_line and isinstance(json_line, str) and json_line.strip():
                        json_data = json.loads(json_line)
                        if isinstance(json_data, dict):
                            pair_result["schema_id"] = json_data.get("schema_id")
                            pair_result["task_id"] = json_data.get("task_id")
                except json.JSONDecodeError as exc:
                    logging.error("解析JSON行时出错 (第%s行): %s", i + 1, exc)

                if pair_result["schema_id"] == 500900:
                    if data_line:
                        data_line = json.loads(data_line)
                    task_id = data_line.get("task_id") if isinstance(data_line, dict) else None
                    if task_id:
                        logging.info("接收到停止任务命令，task_id: %s", task_id)
                        self.stop_threads_by_task_id(task_id)
                        logging.info("task_id %s 的所有相关线程已处理完成", task_id)
                    else:
                        logging.warning("接收到停止任务命令，但未获取到有效的task_id")
                elif pair_result["schema_id"] == 500800:
                    data_line = json.loads(data_line)
                    outputs = data_line.get("outputs")
                    if outputs and isinstance(outputs, list):
                        for item in outputs:
                            try:
                                data_subtype = item.get("data_subtype")
                                task_id = item.get("task_id")
                                if data_subtype is None or task_id is None:
                                    logging.warning("输出项缺少必要字段: %s", item)
                                    continue
                                if data_subtype == 1001:
                                    if self.on_start_telegram:
                                        send_service.clear_stop_event(task_id)
                                        self.on_start_telegram(task_id, None, None)
                                elif data_subtype == 1002:
                                    if self.on_start_darknet:
                                        send_service.clear_stop_event(task_id)
                                        self.on_start_darknet(task_id, None, None)
                                else:
                                    logging.warning("未知的data_subtype值: %s", data_subtype)
                            except Exception as exc:
                                logging.error("处理输出项时发生异常: %s, 项目: %s", exc, item)
                else:
                    logging.error("未处理的schema_id: %s", pair_result["schema_id"])

                result.append(pair_result)
            return result
        except Exception as exc:
            logging.error("执行命令时发生异常: %s", exc)
            return []

    def receive_commands(self):
        logging.info("命令接收线程已启动，开始监听命令...")
        while self.running:
            try:
                if not self.cookie:
                    self.cookie = self.get_cookie()
                    if not self.cookie:
                        logging.error(
                            "没有获取到cookie，无法接收命令，将在%s秒后重试",
                            self.recv_api_config["command_check_interval"],
                        )
                        time.sleep(self.recv_api_config["command_check_interval"])
                        continue

                headers = {
                    "User-Agent": self.recv_api_config["user_agent"],
                    "Cookie": self.cookie,
                }
                response = requests.get(
                    self.recv_api_config["recv_url"],
                    headers=headers,
                    verify=False,
                    timeout=30,
                )

                if response.status_code == 200:
                    try:
                        lines = response.text.split("\n")
                        lines = self.handle_received_command(lines)
                        self.execute_command(lines)
                    except Exception as exc:
                        logging.error("处理响应时发生异常: %s", exc)
                else:
                    logging.error("接收命令失败，状态码: %s", response.status_code)
                    logging.error("响应内容: %s", response.text)
                    if response.status_code == 401:
                        self.cookie = ""
                        self.cookie = self.get_cookie()
            except requests.exceptions.Timeout:
                logging.warning("接收命令请求超时")
            except requests.exceptions.RequestException as exc:
                logging.error("接收命令请求异常: %s", exc)
            except Exception as exc:
                logging.error("处理命令时发生异常: %s", exc)

            time.sleep(self.recv_api_config["command_check_interval"])

        logging.info("命令接收线程已停止")

    def start(self):
        thread = threading.Thread(target=self.receive_commands, name="CommandThread", daemon=True)
        thread.start()
        return thread
