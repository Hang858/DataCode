#!/usr/bin/env python3
"""
Minimal DataTerminal send/receive probe.

This script intentionally does not depend on the crawler or OpenSearch path.
It only verifies:
1. /system/connect authentication
2. /data/sendData publish request
3. optional /data/offsetInfo and /data/recvData consumer request
"""

import argparse
import hashlib
import json
import time

import requests


requests.packages.urllib3.disable_warnings()


def build_token(user_agent, auth_key, timestamp):
    raw = f"{user_agent}-{timestamp}-{auth_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def connect(base_url, user_agent, auth_key, request_type):
    timestamp = int(time.time())
    payload = {
        "requestType": int(request_type),
        "time": timestamp,
        "token": build_token(user_agent, auth_key, timestamp),
    }
    headers = {
        "User-Agent": user_agent,
        "Content-Type": "application/json",
    }

    print(f"\n[connect] {user_agent} requestType={request_type}")
    response = requests.post(
        f"{base_url}/system/connect",
        headers=headers,
        json=payload,
        verify=False,
        timeout=20,
    )
    print(f"status={response.status_code}")
    print(f"body={response.text}")
    print(f"set-cookie={response.headers.get('Set-Cookie')}")
    response.raise_for_status()

    session = response.cookies.get("SESSION")
    if not session:
        raise RuntimeError("connect succeeded but SESSION cookie was not returned")
    return f"SESSION={session}"


def send_data(args, cookie):
    x_tag = {
        "producer": args.producer_user_agent,
        "data_type": args.data_type,
        "data_subtype": args.data_subtype,
        "data_id": args.data_id,
        "datasource": args.datasource,
        "schema_id": args.schema_id,
        "task_id": args.task_id,
        "file_id_list": args.file_id_list,
    }
    payload = {
        "id": args.data_id,
        "message": {
            "probe": "dataterminal-send",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "content": args.message,
        },
    }
    headers = {
        "User-Agent": args.producer_user_agent,
        "Cookie": cookie,
        "Checksum": args.checksum,
        "X-Tag": json.dumps(x_tag, ensure_ascii=False),
    }

    print("\n[sendData]")
    print(f"url={args.base_url}/data/sendData")
    print(f"x-tag={headers['X-Tag']}")
    print(f"payload={json.dumps(payload, ensure_ascii=False)}")
    response = requests.post(
        f"{args.base_url}/data/sendData",
        headers=headers,
        json=payload,
        verify=False,
        timeout=30,
    )
    print(f"status={response.status_code}")
    print(f"body={response.text}")
    return response


def offset_info(args, cookie):
    headers = {
        "User-Agent": args.consumer_user_agent,
        "Cookie": cookie,
        "X-ID": args.x_id,
    }
    print("\n[offsetInfo]")
    response = requests.get(
        f"{args.base_url}/data/offsetInfo",
        headers=headers,
        verify=False,
        timeout=20,
    )
    print(f"status={response.status_code}")
    print(f"body={response.text}")
    return response


def recv_data(args, cookie):
    headers = {
        "User-Agent": args.consumer_user_agent,
        "Cookie": cookie,
        "X-ID": args.x_id,
    }
    print("\n[recvData]")
    response = requests.get(
        f"{args.base_url}/data/recvData",
        headers=headers,
        verify=False,
        timeout=30,
    )
    print(f"status={response.status_code}")
    print(f"body={response.text[:2000]}")
    return response


def parse_args():
    parser = argparse.ArgumentParser(description="Probe DataTerminal send/receive APIs.")
    parser.add_argument("--base-url", default="http://192.168.1.10:8443")
    parser.add_argument("--producer-user-agent", default="Module/2")
    parser.add_argument("--producer-auth-key", default="a29676d1c97b815799e832d7bf3a37b54bc388fc")
    parser.add_argument("--data-type", type=int, default=1)
    parser.add_argument("--data-subtype", type=int, default=1001)
    parser.add_argument("--task-id", type=int, default=1)
    parser.add_argument("--data-id", type=int, default=lambda_default_data_id())
    parser.add_argument("--datasource", type=int, default=2)
    parser.add_argument("--schema-id", type=int, default=100100)
    parser.add_argument("--file-id-list", type=int, nargs="*", default=[])
    parser.add_argument("--checksum", default="123456")
    parser.add_argument("--message", default="hello from dataterminal minimal probe")
    parser.add_argument("--consumer-user-agent", default="")
    parser.add_argument("--consumer-auth-key", default="")
    parser.add_argument("--x-id", default="", help="DataRightID/topic used by recvData and offsetInfo.")
    parser.add_argument("--skip-send", action="store_true")
    parser.add_argument("--recv", action="store_true")
    return parser.parse_args()


def lambda_default_data_id():
    return int(time.time() * 1000) % 2_147_483_647


def main():
    args = parse_args()

    producer_cookie = connect(
        args.base_url,
        args.producer_user_agent,
        args.producer_auth_key,
        10,
    )
    if not args.skip_send:
        send_data(args, producer_cookie)

    if args.recv:
        if not args.consumer_user_agent or not args.consumer_auth_key or not args.x_id:
            raise SystemExit("--recv requires --consumer-user-agent, --consumer-auth-key and --x-id")
        consumer_cookie = connect(
            args.base_url,
            args.consumer_user_agent,
            args.consumer_auth_key,
            20,
        )
        offset_info(args, consumer_cookie)
        recv_data(args, consumer_cookie)


if __name__ == "__main__":
    main()
