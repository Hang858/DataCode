import os


SUPPORTED_EXTENSIONS = {
    "txt",
    "xls",
    "xlsx",
    "csv",
    "docx",
    "html",
    "htm",
    "xml",
    "json",
    "log",
    "md",
    "conf",
    "cfg",
    "ini",
    "css",
}

BATCH_SIZE = 1000
ROW_CHUNK_SIZE = int(os.getenv("OFFLINE_ROW_CHUNK_SIZE", "5000"))
FILE_FINGERPRINT_BYTES = int(os.getenv("OFFLINE_FILE_FINGERPRINT_BYTES", str(1024 * 1024)))
UNPROCESSED_THRESHOLD = 0.8
NAME_DUPLICATE_THRESHOLD = 0.8


def env_bool(name, default=False):
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


COPY_FAILED_FILES = env_bool("OFFLINE_COPY_FAILED_FILES", False)
LOG_DIR = os.getenv("OFFLINE_LOG_DIR", "logs/offline_data_processing")

OPENSEARCH_INDEX = "offline_private"
OPENSEARCH_IMPORT_INDEX = "offline_import_file"
OPENSEARCH_SHARDS = 12
OPENSEARCH_REPLICAS = 0
OPENSEARCH_REFRESH_INTERVAL = "30s"
OPENSEARCH_CONFIG = {
    "hosts": [{"host": "192.168.23.203", "port": 9200}],
    "http_auth": ("admin", "MyStrongPass123!"),
    "use_ssl": True,
    "verify_certs": False,
    "ssl_show_warn": False,
    "timeout": 60,
    "max_retries": 3,
    "retry_on_timeout": True,
}
