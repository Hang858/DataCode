import os
from datetime import timedelta

MODULE_7_RECV_API_CONFIG = {
    "connect_url": "http://192.168.23.201:8443/system/connect",
    "recv_url": "http://192.168.23.201:8443/control/recvCommd",
    "user_agent": "Module/7",
    "auth_key": "c7727529e069a4cfd77c166b49228e5c38455fa3",
    "request_type": 40,
    "command_check_interval": 5,
}

MODULE_9_RECV_API_CONFIG = {
    "connect_url": "http://192.168.23.201:8443/system/connect",
    "recv_url": "http://192.168.23.201:201/control/recvCommd",
    "user_agent": "Module/9",
    "auth_key": "c500b940f7f9cc828b8f7a6dce0115a94423d6fe",
    "request_type": 40,
    "command_check_interval": 5,
}

DB_CONFIG = {
    "host": "192.168.23.204",
    "database": "online",
    "user": "root",
    "password": "MyPass123!",
    "auth_plugin": "caching_sha2_password",
    "max_retries": 5,
    "retry_delay": 5,
}

API_CONFIG_BY_MODULE = {
    7: {
        "connect_url": "http://192.168.23.201:8443/system/connect",
        "send_url": "http://192.168.23.201:8443/data/sendData",
        "user_agent": "Module/7",
        "auth_key": "c7727529e069a4cfd77c166b49228e5c38455fa3",
        "request_type": 10,
    },
    9: {
        "connect_url": "http://192.168.23.201:8443/system/connect",
        "send_url": "http://192.168.23.201:8443/data/sendData",
        "user_agent": "Module/9",
        "auth_key": "c500b940f7f9cc828b8f7a6dce0115a94423d6fe",
        "request_type": 10,
    },
}

DEFAULT_DIRECT_START_DATE = "2024-01-01"
DEFAULT_DIRECT_END_DATE = "2025-08-17"

OPENSEARCH_CONFIG = {
    "hosts": [{"host": "192.168.23.204", "port": 9200}],
    "http_auth": ("admin", "MyStrongPass123!"),
    "use_ssl": True,
    "verify_certs": False,
    "ssl_show_warn": False,
    "timeout": 30,
    "max_retries": 3,
    "retry_on_timeout": True,
}

OPENSEARCH_INDEXES = {
    "telegram": "telegram_index",
    "darknet": "darknet_index",
}

OPENSEARCH_QUERY_CONFIG = {
    "page_size": 1000,
    "timeout": "30s",
    "telegram_slice_days": 1,
    "darknet_slice_days": 1,
}

DATA_SOURCE_CONFIG = {
    "default": "mysql",
    "module7": "mysql",
    "module9": "mysql",
}


def get_data_source_name(module=None):
    if module == 7:
        config_key = "module7"
        env_key = "SENDWORKER_MODULE7_DATA_SOURCE"
    elif module == 9:
        config_key = "module9"
        env_key = "SENDWORKER_MODULE9_DATA_SOURCE"
    else:
        config_key = "default"
        env_key = "SENDWORKER_DATA_SOURCE"

    value = os.getenv(env_key) or DATA_SOURCE_CONFIG.get(config_key) or DATA_SOURCE_CONFIG["default"]
    return str(value).strip().lower()


def get_opensearch_slice_delta(kind):
    if kind == "telegram":
        days = OPENSEARCH_QUERY_CONFIG.get("telegram_slice_days", 1)
    else:
        days = OPENSEARCH_QUERY_CONFIG.get("darknet_slice_days", 1)
    return timedelta(days=max(int(days), 1))
