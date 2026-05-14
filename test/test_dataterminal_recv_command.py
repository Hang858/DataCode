#!/usr/bin/env python3
"""
Minimal command receive probe for DataTerminal /control/recvCommd.

It authenticates with /system/connect and then calls /control/recvCommd once
or in a loop, printing detailed request/response information.
"""

import argparse
import hashlib
import json
import time

import requests


requests.packages.urllib3.disable_warnings()


MODULES = {
    7: {
        "user_agent": "Module/7",
        "auth_key": "c7727529e069a4cfd77c166b49228e5c38455fa3",
        "request_type": 40,
    },
    9: {
        "user_agent": "Module/9",
        "auth_key": "c500b940f7f9cc828b8f7a6dce0115a94423d6fe",
        "request_type": 40,
    },
}


def make_token(user_agent, auth_key, timestamp):
    raw = f"{user_agent}-{timestamp}-{auth_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def connect(base_url, module):
    cfg = MODULES[module]
    timestamp = int(time.time())
    payload = {
        "requestType": cfg["request_type"],
        "time": timestamp,
        "token": make_token(cfg["user_agent"], cfg["auth_key"], timestamp),
    }
    headers = {
        "User-Agent": cfg["user_agent"],
        "Content-Type": "application/json",
    }

    print("\n=== CONNECT ===")
    print(f"url={base_url}/system/connect")
    print(f"headers={headers}")
    print(f"payload={json.dumps(payload, ensure_ascii=False)}")
    response = requests.post(
        f"{base_url}/system/connect",
        headers=headers,
        json=payload,
        verify=False,
        timeout=20,
    )
    print(f"status={response.status_code}")
    print(f"headers={dict(response.headers)}")
    print(f"body={response.text}")

    session = response.cookies.get("SESSION")
    if response.status_code != 200 or not session:
        raise RuntimeError("connect failed or SESSION cookie missing")
    return f"SESSION={session}"


def print_response_body(text):
    print(f"body_length={len(text)}")
    print("raw_body_begin")
    print(text)
    print("raw_body_end")
    lines = text.splitlines()
    print(f"line_count={len(lines)}")
    for idx, line in enumerate(lines, 1):
        print(f"line[{idx}]={line}")
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                print(f"line[{idx}]_json={json.dumps(json.loads(stripped), ensure_ascii=False, indent=2)}")
            except json.JSONDecodeError as exc:
                print(f"line[{idx}]_json_error={exc}")


def recv_command(base_url, module, cookie, timeout, round_index=None):
    cfg = MODULES[module]
    headers = {
        "User-Agent": cfg["user_agent"],
        "Cookie": cookie,
    }

    print("\n=== RECV COMMAND ===")
    if round_index is not None:
        print(f"round={round_index}")
    print(f"time={time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"url={base_url}/control/recvCommd")
    print(f"headers={headers}", flush=True)
    start = time.time()
    try:
        response = requests.get(
            f"{base_url}/control/recvCommd",
            headers=headers,
            verify=False,
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        print(f"timeout after {elapsed:.2f}s; no HTTP response body was received", flush=True)
        return False
    except requests.exceptions.RequestException as exc:
        elapsed = time.time() - start
        print(f"request_exception after {elapsed:.2f}s: {exc!r}", flush=True)
        return False

    elapsed = time.time() - start
    print(f"elapsed={elapsed:.2f}s")
    print(f"status={response.status_code}")
    print(f"headers={dict(response.headers)}")
    print(f"text_repr={response.text!r}")
    print_response_body(response.text)
    return response.status_code == 200


def parse_args():
    parser = argparse.ArgumentParser(description="Test DataTerminal command receiving.")
    parser.add_argument("--base-url", default="http://192.168.23.201:8443")
    parser.add_argument("--module", type=int, choices=sorted(MODULES), default=7)
    parser.add_argument("--timeout", type=int, default=35)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--max-rounds", type=int, default=0, help="0 means infinite when --loop is set.")
    return parser.parse_args()


def main():
    args = parse_args()
    cookie = connect(args.base_url, args.module)

    round_index = 1
    while True:
        recv_command(args.base_url, args.module, cookie, args.timeout, round_index)
        if not args.loop:
            break
        if args.max_rounds and round_index >= args.max_rounds:
            break
        round_index += 1
        print(f"\nsleep {args.interval}s")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
