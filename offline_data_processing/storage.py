import hashlib
import json
import logging

import urllib3
from opensearchpy import OpenSearch, helpers

from .config import (
    BATCH_SIZE,
    OPENSEARCH_CONFIG,
    OPENSEARCH_IMPORT_INDEX,
    OPENSEARCH_INDEX,
    OPENSEARCH_REFRESH_INTERVAL,
    OPENSEARCH_REPLICAS,
    OPENSEARCH_SHARDS,
)


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
LOGGER = logging.getLogger(__name__)


class OpenSearchRecordStore:
    def __init__(
        self,
        opensearch_config=None,
        index_name=OPENSEARCH_INDEX,
        import_index_name=OPENSEARCH_IMPORT_INDEX,
        batch_size=BATCH_SIZE,
        shards=OPENSEARCH_SHARDS,
        replicas=OPENSEARCH_REPLICAS,
        refresh_interval=OPENSEARCH_REFRESH_INTERVAL,
    ):
        self.opensearch_config = opensearch_config or OPENSEARCH_CONFIG
        self.index_name = index_name
        self.import_index_name = import_index_name
        self.batch_size = batch_size
        self.shards = shards
        self.replicas = replicas
        self.refresh_interval = refresh_interval
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = OpenSearch(**self.opensearch_config)
        return self._client

    def ensure_schema(self):
        LOGGER.info("开始初始化 OpenSearch 存储")
        self.ensure_index(self.index_name, self.record_index_body())
        self.ensure_index(self.import_index_name, self.import_index_body())
        LOGGER.info("OpenSearch 存储初始化完成")

    def ensure_index(self, index_name, body):
        LOGGER.info("检查 OpenSearch 索引: %s", index_name)
        if self.client.indices.exists(index=index_name):
            LOGGER.info("OpenSearch 索引已存在: %s", index_name)
            return
        LOGGER.info("创建 OpenSearch 索引: %s", index_name)
        self.client.indices.create(index=index_name, body=body)
        LOGGER.info("OpenSearch 索引创建完成: %s", index_name)

    def record_index_body(self):
        return {
            "settings": {
                "index": {
                    "number_of_shards": self.shards,
                    "number_of_replicas": self.replicas,
                    "refresh_interval": self.refresh_interval,
                    "max_ngram_diff": 10,
                },
                "analysis": {
                    "analyzer": {
                        "raw_ngram_analyzer": {
                            "tokenizer": "raw_ngram_tokenizer",
                            "filter": ["lowercase"],
                        }
                    },
                    "tokenizer": {
                        "raw_ngram_tokenizer": {
                            "type": "ngram",
                            "min_gram": 2,
                            "max_gram": 12,
                            "token_chars": ["letter", "digit", "punctuation", "symbol"],
                        }
                    },
                },
            },
            "mappings": {
                "dynamic": "false",
                "properties": {
                    "record_id": {"type": "keyword"},
                    "id_card": {"type": "keyword"},
                    "phone": {"type": "keyword"},
                    "person_name": {"type": "keyword"},
                    "bank_card": {"type": "keyword"},
                    "raw_data": {
                        "type": "text",
                        "analyzer": "raw_ngram_analyzer",
                        "fields": {
                            "keyword": {"type": "keyword", "ignore_above": 8191},
                        },
                    },
                    "leak_channel": {"type": "keyword"},
                    "source": {"type": "keyword"},
                    "insert_time": {
                        "type": "date",
                        "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time",
                    },
                },
            },
        }

    def import_index_body(self):
        return {
            "settings": {
                "index": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "refresh_interval": "5s",
                }
            },
            "mappings": {
                "dynamic": "false",
                "properties": {
                    "source": {"type": "keyword"},
                    "file_key": {"type": "keyword"},
                    "file_name": {"type": "keyword"},
                    "file_size": {"type": "long"},
                    "file_mtime": {
                        "type": "date",
                        "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time",
                    },
                    "status": {"type": "keyword"},
                    "total_rows": {"type": "long"},
                    "unprocessed_rows": {"type": "long"},
                    "inserted_rows": {"type": "long"},
                    "error_message": {"type": "text"},
                    "started_at": {
                        "type": "date",
                        "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time",
                    },
                    "finished_at": {
                        "type": "date",
                        "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time",
                    },
                    "updated_at": {
                        "type": "date",
                        "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time",
                    },
                },
            },
        }

    def insert_records(self, records):
        actions = []
        total = 0
        for record in records:
            doc = self.record_to_document(record)
            actions.append(
                {
                    "_op_type": "index",
                    "_index": self.index_name,
                    "_id": doc["record_id"],
                    "_source": doc,
                }
            )
            if len(actions) >= self.batch_size:
                total += self.bulk_insert(actions)
                actions.clear()
        if actions:
            total += self.bulk_insert(actions)
        return total

    def bulk_insert(self, actions):
        success_count = 0
        for ok, item in helpers.streaming_bulk(
            self.client,
            actions,
            chunk_size=self.batch_size,
            request_timeout=self.opensearch_config.get("timeout", 60),
            raise_on_error=False,
        ):
            if ok:
                success_count += 1
            else:
                raise RuntimeError(f"OpenSearch 写入失败: {item}")
        return success_count

    def record_to_document(self, record):
        return {
            "record_id": self.record_id(record),
            "id_card": record.id_card,
            "phone": record.phone,
            "person_name": record.person_name,
            "bank_card": record.bank_card,
            "raw_data": record.raw_data,
            "leak_channel": record.leak_channel,
            "source": record.source,
            "insert_time": record.insert_time,
        }

    def record_id(self, record):
        raw_data = record.raw_data
        try:
            raw_data = json.dumps(json.loads(record.raw_data), ensure_ascii=False, sort_keys=True)
        except (TypeError, json.JSONDecodeError):
            pass
        key = "\x1f".join(
            [
                record.source or "",
                record.id_card or "",
                record.phone or "",
                record.person_name or "",
                record.bank_card or "",
                raw_data or "",
            ]
        )
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def delete_by_source(self, source):
        response = self.client.delete_by_query(
            index=self.index_name,
            body={"query": {"term": {"source": source}}},
            conflicts="proceed",
            refresh=True,
            request_timeout=self.opensearch_config.get("timeout", 60),
        )
        return response.get("deleted", 0)

    def get_file_status(self, file_key):
        doc_id = self.file_status_id(file_key)
        try:
            response = self.client.get(index=self.import_index_name, id=doc_id)
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404:
                return None
            raise
        return response.get("_source")

    def mark_started(self, source, file_key=None, file_name=None, file_size=None, file_mtime=None, started_at=None):
        now = started_at
        self.upsert_file_status(
            file_key,
            {
                "source": source,
                "file_key": file_key,
                "file_name": file_name,
                "file_size": file_size,
                "file_mtime": file_mtime,
                "status": "processing",
                "total_rows": 0,
                "unprocessed_rows": 0,
                "inserted_rows": 0,
                "error_message": None,
                "started_at": started_at,
                "finished_at": None,
                "updated_at": now,
            },
        )

    def mark_success(self, file_key, total_rows, unprocessed_rows, inserted_rows, finished_at=None):
        self.update_file_status(
            file_key,
            {
                "status": "success",
                "total_rows": total_rows,
                "unprocessed_rows": unprocessed_rows,
                "inserted_rows": inserted_rows,
                "error_message": None,
                "finished_at": finished_at,
                "updated_at": finished_at,
            },
        )

    def mark_failed(
        self,
        file_key,
        error_message,
        total_rows=0,
        unprocessed_rows=0,
        inserted_rows=0,
        finished_at=None,
    ):
        self.update_file_status(
            file_key,
            {
                "status": "failed",
                "total_rows": total_rows,
                "unprocessed_rows": unprocessed_rows,
                "inserted_rows": inserted_rows,
                "error_message": str(error_message)[:8191],
                "finished_at": finished_at,
                "updated_at": finished_at,
            },
        )

    def upsert_file_status(self, file_key, body):
        self.client.index(
            index=self.import_index_name,
            id=self.file_status_id(file_key),
            body=body,
            refresh=True,
            request_timeout=self.opensearch_config.get("timeout", 60),
        )

    def update_file_status(self, file_key, fields):
        self.client.update(
            index=self.import_index_name,
            id=self.file_status_id(file_key),
            body={"doc": fields, "doc_as_upsert": True},
            refresh=True,
            request_timeout=self.opensearch_config.get("timeout", 60),
        )

    def file_status_id(self, file_key):
        return hashlib.sha256((file_key or "").encode("utf-8")).hexdigest()


def build_record_store():
    return OpenSearchRecordStore()
