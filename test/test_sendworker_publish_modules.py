#!/usr/bin/env python3
"""
Minimal publish probe for datascratch/sendworker Module/7 and Module/9.

It extracts only the DataTerminal connect + sendData part from
datascratch/sendworker/services/send_service.py, without reading MySQL or
OpenSearch.
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
    },
    9: {
        "user_agent": "Module/9",
        "auth_key": "c500b940f7f9cc828b8f7a6dce0115a94423d6fe",
    },
}


def signature(user_agent, auth_key, timestamp):
    raw = f"{user_agent}-{timestamp}-{auth_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def connect(base_url, module):
    config = MODULES[module]
    timestamp = int(time.time())
    headers = {
        "User-Agent": config["user_agent"],
        "Content-Type": "application/json",
    }
    payload = {
        "requestType": 10,
        "time": timestamp,
        "token": signature(config["user_agent"], config["auth_key"], timestamp),
    }
    print(f"\n[connect] module={module} user_agent={config['user_agent']}")
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
    if response.status_code != 200:
        return None
    session = response.cookies.get("SESSION")
    if not session:
        print("ERROR: missing SESSION cookie")
        return None
    return f"SESSION={session}"


def send_data(base_url, module, subtype, task_id, data_id, cookie):
    config = MODULES[module]
    datasource = 3 if subtype == 1002 else 2
    schema_id = 100200 if subtype == 1002 else 100100
    x_tag = {
        "producer": config["user_agent"],
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
                "_id": f"probe-{module}-{subtype}-{data_id}",
                "source": "test_sendworker_publish_modules.py",
                "content": f"module {module} subtype {subtype} publish probe",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
        ),
        "id": data_id,
    }
    headers = {
        "User-Agent": config["user_agent"],
        "Cookie": cookie,
        "Checksum": "123456",
        "X-Tag": json.dumps(x_tag, ensure_ascii=False),
    }

    print(f"\n[sendData] module={module} subtype={subtype} task_id={task_id}")
    print(f"x-tag={headers['X-Tag']}")
    print(f"payload={json.dumps(payload, ensure_ascii=False)}")
    response = requests.post(
        f"{base_url}/data/sendData",
        headers=headers,
        json=payload,
        verify=False,
        timeout=30,
    )
    print(f"status={response.status_code}")
    print(f"body={response.text}")
    return response.status_code == 200


def parse_args():
    parser = argparse.ArgumentParser(description="Test Module/7 and Module/9 DataTerminal publish.")
    parser.add_argument("--base-url", default="http://192.168.23.201:8443")
    parser.add_argument("--modules", type=int, nargs="+", choices=(7, 9), default=[7, 9])
    parser.add_argument("--subtypes", type=int, nargs="+", choices=(1001, 1002), default=[1001, 1002])
    parser.add_argument("--task-id", type=int, default=1)
    parser.add_argument("--data-id", type=int, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    base_data_id = args.data_id or int(time.time() * 1000) % 2_147_483_647
    failed = False

    for module in args.modules:
        cookie = connect(args.base_url, module)
        if not cookie:
            failed = True
            continue
        for offset, subtype in enumerate(args.subtypes):
            ok = send_data(args.base_url, module, subtype, args.task_id, base_data_id + module * 10 + offset, cookie)
            failed = failed or not ok

    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
