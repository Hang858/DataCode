#!/usr/bin/env python3
"""
Unified DataTerminal publish test for Module/2, Module/7 and Module/9.

By default it tests task_id 1 and 107 with data_subtype 1001 and 1002.
It does not read MySQL/OpenSearch data; it only tests connect + sendData.
"""

import argparse
import hashlib
import json
import time

import requests


requests.packages.urllib3.disable_warnings()


MODULES = {
    2: {
        "user_agent": "Module/2",
        "auth_key": "a29676d1c97b815799e832d7bf3a37b54bc388fc",
    },
    7: {
        "user_agent": "Module/7",
        "auth_key": "c7727529e069a4cfd77c166b49228e5c38455fa3",
    },
    9: {
        "user_agent": "Module/9",
        "auth_key": "c500b940f7f9cc828b8f7a6dce0115a94423d6fe",
    },
}


def make_token(user_agent, auth_key, timestamp):
    raw = f"{user_agent}-{timestamp}-{auth_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def connect(base_url, module):
    cfg = MODULES[module]
    timestamp = int(time.time())
    response = requests.post(
        f"{base_url}/system/connect",
        headers={
            "User-Agent": cfg["user_agent"],
            "Content-Type": "application/json",
        },
        json={
            "requestType": 10,
            "time": timestamp,
            "token": make_token(cfg["user_agent"], cfg["auth_key"], timestamp),
        },
        verify=False,
        timeout=20,
    )
    print(f"[connect] module={module} status={response.status_code} body={response.text}")
    if response.status_code != 200:
        return None
    session = response.cookies.get("SESSION")
    if not session:
        print(f"[connect] module={module} missing SESSION cookie")
        return None
    return f"SESSION={session}"


def publish(base_url, module, subtype, task_id, cookie, data_id):
    cfg = MODULES[module]
    datasource = 3 if subtype == 1002 else 2
    schema_id = 100200 if subtype == 1002 else 100100
    x_tag = {
        "producer": cfg["user_agent"],
        "data_type": 1,
        "data_subtype": subtype,
        "data_id": data_id,
        "datasource": datasource,
        "schema_id": schema_id,
        "task_id": task_id,
        "file_id_list": [],
    }
    payload = {
        "message": json.dumps(
            {
                "_id": f"matrix-{module}-{subtype}-{task_id}-{data_id}",
                "module": module,
                "data_subtype": subtype,
                "task_id": task_id,
                "content": "DataTerminal publish matrix probe",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
        ),
        "id": data_id,
    }
    response = requests.post(
        f"{base_url}/data/sendData",
        headers={
            "User-Agent": cfg["user_agent"],
            "Cookie": cookie,
            "Checksum": "123456",
            "X-Tag": json.dumps(x_tag, ensure_ascii=False),
        },
        json=payload,
        verify=False,
        timeout=30,
    )
    ok = response.status_code == 200
    result = "OK" if ok else "FAIL"
    print(
        f"[sendData] {result} module={module} subtype={subtype} task_id={task_id} "
        f"status={response.status_code} body={response.text}"
    )
    return ok


def parse_args():
    parser = argparse.ArgumentParser(description="Run a DataTerminal publish test matrix.")
    parser.add_argument("--base-url", default="http://192.168.23.201:8443")
    parser.add_argument("--modules", type=int, nargs="+", choices=sorted(MODULES), default=[2, 7, 9])
    parser.add_argument("--subtypes", type=int, nargs="+", choices=(1001, 1002), default=[1001, 1002])
    parser.add_argument("--task-ids", type=int, nargs="+", default=[1, 107])
    parser.add_argument("--data-id", type=int, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    base_data_id = args.data_id or int(time.time() * 1000) % 2_147_483_647
    failed = 0
    total = 0

    for module in args.modules:
        cookie = connect(args.base_url, module)
        if not cookie:
            failed += len(args.subtypes) * len(args.task_ids)
            continue
        for task_index, task_id in enumerate(args.task_ids):
            for subtype_index, subtype in enumerate(args.subtypes):
                total += 1
                data_id = base_data_id + module * 1000 + task_index * 10 + subtype_index
                if not publish(args.base_url, module, subtype, task_id, cookie, data_id):
                    failed += 1

    print(f"\nsummary: total={total} failed={failed} passed={total - failed}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
