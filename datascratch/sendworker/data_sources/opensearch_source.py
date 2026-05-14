import logging
from contextlib import AbstractContextManager
from datetime import date, datetime, time, timedelta

import urllib3
from opensearchpy import OpenSearch, helpers

from sendworker.config import (
    OPENSEARCH_CONFIG,
    OPENSEARCH_INDEXES,
    OPENSEARCH_QUERY_CONFIG,
    get_opensearch_slice_delta,
)
from sendworker.data_sources.mysql_source import MySQLDataSource

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.getLogger("opensearch").setLevel(logging.WARNING)


TELEGRAM_SOURCE_FIELDS = [
    "id",
    "original_id",
    "_id",
    "chat_id",
    "chat_name",
    "content_text",
    "content_text_md5",
    "event",
    "file_extension",
    "hot",
    "identical_msg_num",
    "industry",
    "media_file_url",
    "media_type",
    "message_date",
    "message_id",
    "message_time",
    "message_time_old_list",
    "org",
    "regions",
    "sender_first_name",
    "sender_id",
    "sender_last_name",
    "sender_phone",
    "sender_username",
    "tags",
    "page_type",
    "timestamp",
    "child_file",
]


DARKNET_SOURCE_FIELDS = [
    "id",
    "original_id",
    "_id",
    "body_md5",
    "description",
    "detail_parsing",
    "event",
    "industry",
    "is_read",
    "msg_author",
    "msg_title_cn",
    "msg",
    "msg_description",
    "msg_release_time",
    "org",
    "page_type",
    "path",
    "regions_city",
    "regions_country",
    "regions_province",
    "root_domain",
    "source",
    "status_code",
    "tags",
    "timestamp",
    "title",
    "toplv_domain",
    "update_time",
    "url",
    "user_id",
    "to_new",
    "body",
    "msg_sample_ss",
    "msg_keyword",
    "msg_webpage_ss",
    "child_file",
]


TELEGRAM_KEYWORD_FIELDS = {"original_id", "chat_id", "message_id", "sender_id", "sender_username"}
DARKNET_KEYWORD_FIELDS = {"original_id", "root_domain", "toplv_domain", "user_id"}
TELEGRAM_GLOBAL_FIELDS = ["content_text", "chat_name", "org", "sender_first_name", "sender_last_name"]
DARKNET_GLOBAL_FIELDS = ["title", "msg_author", "msg_title_cn", "msg_description", "event"]


class OpenSearchConnection(AbstractContextManager):
    def __init__(self, mysql_source, opensearch_client):
        self._mysql_connection = mysql_source.get_connection()
        self._opensearch_client = opensearch_client
        self.task_id = None
        self._task_filter_cache = {}

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def cursor(self, *args, **kwargs):
        return self._mysql_connection.cursor(*args, **kwargs)

    def is_connected(self):
        return self._mysql_connection.is_connected()

    def close(self):
        if self._mysql_connection and self._mysql_connection.is_connected():
            self._mysql_connection.close()

    @property
    def opensearch(self):
        return self._opensearch_client


class OpenSearchDataSource:
    """
    Mixed data source:
    - task parameter tables still use MySQL
    - telegram/darknet data rows come from OpenSearch
    - row fetching is streamed by time slices to avoid loading everything in memory
    """

    def __init__(
        self,
        mysql_source=None,
        opensearch_config=None,
        index_names=None,
        query_config=None,
        extra_filters=None,
    ):
        self.mysql_source = mysql_source or MySQLDataSource()
        self.opensearch_config = opensearch_config or OPENSEARCH_CONFIG
        self.index_names = index_names or OPENSEARCH_INDEXES
        self.query_config = query_config or OPENSEARCH_QUERY_CONFIG
        self.extra_filters = extra_filters or {}
        self._client = None

    def set_extra_filters(self, telegram_filters=None, darknet_filters=None):
        if telegram_filters is not None:
            self.extra_filters["telegram"] = telegram_filters
        if darknet_filters is not None:
            self.extra_filters["darknet"] = darknet_filters

    def _get_client(self):
        if self._client is None:
            self._client = OpenSearch(**self.opensearch_config)
        return self._client

    def get_connection(self):
        return OpenSearchConnection(self.mysql_source, self._get_client())

    def resolve_telegram_time_range(self, cursor, task_id, module, start_date, end_date):
        return self.mysql_source.resolve_telegram_time_range(cursor, task_id, module, start_date, end_date)

    def fetch_submission_flags(self, cursor, task_id):
        return self.mysql_source.fetch_submission_flags(cursor, task_id)

    def fetch_task_filters(self, cursor, task_id, dataset):
        return self.mysql_source.fetch_task_filters(cursor, task_id, dataset)

    def resolve_darknet_time_range(self, cursor, task_id, module, start_date, end_date):
        return self.mysql_source.resolve_darknet_time_range(cursor, task_id, module, start_date, end_date)

    def fetch_scheduler_configs(self, cursor, task_id=None):
        return self.mysql_source.fetch_scheduler_configs(cursor, task_id)

    def fetch_telegram_rows(self, connection, start_date, end_date):
        date_ranges = self._iterate_date_slices(start_date, end_date, get_opensearch_slice_delta("telegram"))
        extra_filters = self.extra_filters.get("telegram")
        for slice_start, slice_end in date_ranges:
            task_filters = self._fetch_task_filters_from_connection(connection, "telegram")
            body = {
                "size": self.query_config["page_size"],
                "_source": TELEGRAM_SOURCE_FIELDS,
                "query": {
                    "bool": {
                        "filter": [
                            {
                                "range": {
                                    "message_date": {
                                        "gte": slice_start.strftime("%Y-%m-%d"),
                                        "lte": slice_end.strftime("%Y-%m-%d"),
                                    }
                                }
                            }
                        ]
                    }
                },
                "timeout": self.query_config["timeout"],
            }
            self._append_search_filters(body, task_filters, TELEGRAM_KEYWORD_FIELDS, TELEGRAM_GLOBAL_FIELDS)
            self._append_extra_filters(body, extra_filters)
            yield from self._scan_hits(connection.opensearch, self.index_names["telegram"], body)

    def fetch_darknet_rows(self, connection, start_date, end_date):
        date_ranges = self._iterate_date_slices(start_date, end_date, get_opensearch_slice_delta("darknet"))
        extra_filters = self.extra_filters.get("darknet")
        for slice_start, slice_end in date_ranges:
            task_filters = self._fetch_task_filters_from_connection(connection, "darknet")
            body = {
                "size": self.query_config["page_size"],
                "_source": DARKNET_SOURCE_FIELDS,
                "query": {
                    "bool": {
                        "filter": [
                            {
                                "range": {
                                    "timestamp": {
                                        "gte": self._slice_start_datetime(slice_start),
                                        "lte": self._slice_end_datetime(slice_end),
                                    }
                                }
                            }
                        ]
                    }
                },
                "timeout": self.query_config["timeout"],
            }
            self._append_search_filters(body, task_filters, DARKNET_KEYWORD_FIELDS, DARKNET_GLOBAL_FIELDS)
            self._append_extra_filters(body, extra_filters)
            yield from self._scan_hits(connection.opensearch, self.index_names["darknet"], body)

    def _fetch_task_filters_from_connection(self, connection, dataset):
        task_id = getattr(connection, "task_id", None)
        if task_id is None:
            return []
        cache = getattr(connection, "_task_filter_cache", None)
        if cache is not None and dataset in cache:
            return cache[dataset]
        cursor = connection.cursor(dictionary=True, buffered=True)
        try:
            task_filter = self.fetch_task_filters(cursor, task_id, dataset)
            if cache is not None:
                cache[dataset] = task_filter
            return task_filter
        finally:
            cursor.close()

    def _append_search_filters(self, body, task_filters, keyword_fields, global_fields):
        if not task_filters:
            return
        for task_filter in task_filters:
            self._append_search_filter(body, task_filter, keyword_fields, global_fields)

    def _append_search_filter(self, body, task_filter, keyword_fields, global_fields):
        search_field = task_filter.get("search_field")
        search_value = task_filter.get("search_value")
        if not search_value:
            return
        bool_query = body["query"]["bool"]
        if search_field:
            actual_field = "original_id" if search_field == "_id" else search_field
            if actual_field in keyword_fields:
                bool_query["filter"].append({"term": {actual_field: search_value}})
            else:
                bool_query.setdefault("must", []).append({"match": {actual_field: search_value}})
            logging.debug("追加任务字段过滤: field=%s value=%s", actual_field, search_value)
        else:
            bool_query.setdefault("must", []).append(
                {
                    "multi_match": {
                        "query": search_value,
                        "fields": global_fields,
                        "analyzer": "smartcn",
                    }
                }
            )
            logging.debug("追加任务全局过滤: value=%s", search_value)

    def _scan_hits(self, client, index_name, body):
        try:
            for hit in helpers.scan(
                client=client,
                index=index_name,
                query=body,
                preserve_order=False,
                size=self.query_config["page_size"],
                request_timeout=self.opensearch_config.get("timeout", 30),
            ):
                source = hit.get("_source", {}) or {}
                if "original_id" in source and "_id" not in source:
                    source["_id"] = source["original_id"]
                if "id" not in source and hit.get("_id") is not None:
                    source["id"] = hit.get("_id")
                yield source
        except Exception as exc:
            logging.error("OpenSearch 查询失败，index=%s, error=%s", index_name, exc)
            raise

    def _append_extra_filters(self, body, extra_filters):
        if not extra_filters:
            return
        filter_list = body["query"]["bool"]["filter"]
        for item in extra_filters:
            filter_list.append(item)

    def _iterate_date_slices(self, start_date, end_date, slice_delta):
        current = self._to_date(start_date)
        end = self._to_date(end_date)
        while current <= end:
            slice_end = min(current + slice_delta - timedelta(days=1), end)
            yield current, slice_end
            current = slice_end + timedelta(days=1)

    def _to_date(self, value):
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return datetime.fromisoformat(text).date()

    def _slice_start_datetime(self, value):
        return datetime.combine(value, time.min).isoformat(timespec="microseconds")

    def _slice_end_datetime(self, value):
        return datetime.combine(value, time.max).isoformat(timespec="microseconds")
