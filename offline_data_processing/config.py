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
UNPROCESSED_THRESHOLD = 0.8
NAME_DUPLICATE_THRESHOLD = 0.8

DB_CONFIG = {
    "host": "192.168.1.40",
    "database": "offline",
    "user": "root",
    "password": "MyPass123!",
    "auth_plugin": "caching_sha2_password",
    "connect_timeout": 30,
    "buffered": True,
}

