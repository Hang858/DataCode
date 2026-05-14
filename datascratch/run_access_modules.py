#!/usr/bin/env python3
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
LOG_ROOT = PROJECT_DIR / "logs" / "access_modules"


MODULES = [
    {
        "name": "access_module_7",
        "runner": "sendworker.runners.module7",
        "data_source_env": "SENDWORKER_MODULE7_DATA_SOURCE",
    },
    {
        "name": "access_module_9",
        "runner": "sendworker.runners.module9",
        "data_source_env": "SENDWORKER_MODULE9_DATA_SOURCE",
    },
]


def build_env(module):
    env = os.environ.copy()
    pythonpath = str(BASE_DIR)
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env["PYTHONPATH"] = pythonpath
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("SENDWORKER_DATA_SOURCE", "opensearch")
    env[module["data_source_env"]] = "opensearch"
    return env


def start_module(module):
    log_dir = LOG_ROOT / module["name"]
    log_dir.mkdir(parents=True, exist_ok=True)
    console_log_path = log_dir / "console.log"
    console_log = console_log_path.open("ab", buffering=0)

    cmd = [
        sys.executable,
        "-u",
        "-c",
        f"from {module['runner']} import main; main()",
    ]
    process = subprocess.Popen(
        cmd,
        cwd=log_dir,
        env=build_env(module),
        stdout=console_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return process, console_log, console_log_path, log_dir


def stop_process(process, timeout=10):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=timeout)


def main():
    running = []
    shutting_down = False

    def request_shutdown(_signum, _frame):
        nonlocal shutting_down
        shutting_down = True
        print("received stop signal, stopping access modules...")

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    print(f"log root: {LOG_ROOT}")
    try:
        for module in MODULES:
            process, console_log, console_log_path, log_dir = start_module(module)
            running.append((module, process, console_log))
            print(f"started {module['name']} pid={process.pid}")
            print(f"  console: {console_log_path}")
            print(f"  module logs: {log_dir}")

        print("both access modules are running. press Ctrl+C to stop.")
        while not shutting_down:
            failed = []
            for module, process, _console_log in running:
                code = process.poll()
                if code is not None:
                    failed.append((module["name"], code))
            if failed:
                for name, code in failed:
                    print(f"{name} exited with code {code}")
                raise SystemExit(1)
            time.sleep(5)
    except KeyboardInterrupt:
        print("stopping access modules...")
    finally:
        for _module, process, console_log in running:
            stop_process(process)
            console_log.close()
        print("stopped")


if __name__ == "__main__":
    main()
