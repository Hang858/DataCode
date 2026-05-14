import urllib3
from django.conf import settings
from opensearchpy import OpenSearch

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TELEGRAM_LIST_SOURCE_FIELDS = [
    "original_id",
    "timestamp",
    "chat_id",
    "chat_name",
    "content_text",
    "event",
    "file_extension",
    "industry",
    "media_file_url",
    "media_type",
    "message_date",
    "message_id",
    "message_time",
    "org",
    "regions",
    "sender_first_name",
    "sender_last_name",
    "sender_id",
    "sender_phone",
    "sender_username",
    "tags",
    "page_type",
    "child_file",
]

DARKNET_LIST_SOURCE_FIELDS = [
    "original_id",
    "title",
    "url",
    "msg_release_time",
    "source",
    "status_code",
    "org",
    "detail_parsing",
    "event",
    "industry",
    "is_read",
    "msg_author",
    "msg_title_cn",
    "msg_description",
    "path",
    "regions_city",
    "regions_country",
    "regions_province",
    "root_domain",
    "tags",
    "timestamp",
    "toplv_domain",
    "update_time",
    "user_id",
    "to_new",
    "child_file",
]

TELEGRAM_EXPORT_SOURCE_FIELDS = [
    "timestamp",
    "chat_id",
    "chat_name",
    "content_text",
    "message_date",
    "message_id",
    "message_time",
    "sender_first_name",
    "sender_last_name",
    "sender_id",
    "sender_phone",
    "sender_username",
]

DARKNET_EXPORT_SOURCE_FIELDS = [
    "title",
    "url",
    "msg_release_time",
    "source",
    "msg_author",
    "msg_description",
    "root_domain",
    "timestamp",
    "toplv_domain",
]

os_client = OpenSearch(
    hosts=settings.OPENSEARCH_CONFIG["hosts"],
    http_auth=settings.OPENSEARCH_CONFIG["http_auth"],
    use_ssl=settings.OPENSEARCH_CONFIG["use_ssl"],
    verify_certs=settings.OPENSEARCH_CONFIG["verify_certs"],
    ssl_show_warn=settings.OPENSEARCH_CONFIG["ssl_show_warn"],
    timeout=settings.OPENSEARCH_CONFIG["timeout"],
    max_retries=settings.OPENSEARCH_CONFIG["max_retries"],
    retry_on_timeout=settings.OPENSEARCH_CONFIG["retry_on_timeout"],
)


def build_telegram_query(
    start_date=None,
    end_date=None,
    search_field=None,
    search_value=None,
    search_after_cursor=None,
    size=50,
    source_fields=None,
):
    body = {
        "size": size,
        "_source": source_fields or TELEGRAM_LIST_SOURCE_FIELDS,
        "query": {
            "bool": {
                "must": [],
                "filter": [],
            }
        },
        "sort": [
            {"message_time": {"order": "desc"}},
            {"original_id": {"order": "desc"}},
        ],
    }

    if search_after_cursor:
        body["search_after"] = search_after_cursor
    else:
        body["from"] = 0

    if start_date or end_date:
        date_range = {}
        if start_date:
            date_range["gte"] = start_date
        if end_date:
            date_range["lte"] = end_date
        body["query"]["bool"]["filter"].append({"range": {"message_time": date_range}})

    if search_value:
        if search_field:
            actual_field = "original_id" if search_field == "_id" else search_field
            keyword_fields = ["original_id", "chat_id", "message_id", "sender_id", "sender_username"]

            if actual_field in keyword_fields:
                body["query"]["bool"]["filter"].append({"term": {actual_field: search_value}})
            else:
                body["query"]["bool"]["must"].append({"match": {actual_field: search_value}})
        else:
            body["query"]["bool"]["must"].append(
                {
                    "multi_match": {
                        "query": search_value,
                        "fields": ["content_text", "chat_name", "org", "sender_first_name", "sender_last_name"],
                        "analyzer": "smartcn",
                    }
                }
            )

    return body


def search_telegram_data(start_date=None, end_date=None, search_field=None, search_value=None, search_after_cursor=None, size=50):
    body = build_telegram_query(
        start_date=start_date,
        end_date=end_date,
        search_field=search_field,
        search_value=search_value,
        search_after_cursor=search_after_cursor,
        size=size,
        source_fields=TELEGRAM_LIST_SOURCE_FIELDS,
    )

    try:
        response = os_client.search(index="telegram_index", body=body)
        hits = response["hits"]["hits"]
        results = [hit["_source"] for hit in hits]

        for index, hit in enumerate(hits):
            results[index]["os_doc_id"] = hit["_id"]

        next_cursor = hits[-1].get("sort") if hits else None
        return results, next_cursor
    except Exception as exc:
        print(f"OpenSearch Query Error: {exc}")
        return [], None


def get_telegram_stats(start_date=None, end_date=None, search_field=None, search_value=None):
    body = build_telegram_query(
        start_date=start_date,
        end_date=end_date,
        search_field=search_field,
        search_value=search_value,
        size=0,
    )
    body.pop("sort", None)
    body.pop("from", None)
    body = {
        **body,
        "aggs": {
            "distinct_chat_ids": {
                "cardinality": {
                    "field": "chat_id",
                }
            }
        },
    }

    try:
        response = os_client.search(index="telegram_index", body=body)
        return {"distinct_count": response["aggregations"]["distinct_chat_ids"]["value"]}
    except Exception as exc:
        print(f"OpenSearch Telegram Stats Error: {exc}")
        return {"distinct_count": None}


def build_darknet_query(
    start_date=None,
    end_date=None,
    search_field=None,
    search_value=None,
    search_after_cursor=None,
    size=50,
    source_fields=None,
):
    body = {
        "size": size,
        "_source": source_fields or DARKNET_LIST_SOURCE_FIELDS,
        "query": {
            "bool": {
                "must": [],
                "filter": [],
            }
        },
        "sort": [
            {"timestamp": {"order": "desc"}},
            {"original_id": {"order": "desc"}},
        ],
    }

    if search_after_cursor:
        body["search_after"] = search_after_cursor
    else:
        body["from"] = 0

    if start_date or end_date:
        date_range = {}
        if start_date:
            date_range["gte"] = f"{start_date}T00:00:00.000000"
        if end_date:
            date_range["lte"] = f"{end_date}T23:59:59.999999"
        body["query"]["bool"]["filter"].append({"range": {"timestamp": date_range}})

    if search_value:
        if search_field:
            actual_field = "original_id" if search_field == "_id" else search_field
            keyword_fields = ["original_id", "root_domain", "toplv_domain", "user_id"]

            if actual_field in keyword_fields:
                body["query"]["bool"]["filter"].append({"term": {actual_field: search_value}})
            else:
                body["query"]["bool"]["must"].append({"match": {actual_field: search_value}})
        else:
            body["query"]["bool"]["must"].append(
                {
                    "multi_match": {
                        "query": search_value,
                        "fields": ["title", "msg_author", "msg_title_cn", "msg_description", "event"],
                        "analyzer": "smartcn",
                    }
                }
            )

    return body


def search_darknet_data(start_date=None, end_date=None, search_field=None, search_value=None, search_after_cursor=None, size=50):
    body = build_darknet_query(
        start_date=start_date,
        end_date=end_date,
        search_field=search_field,
        search_value=search_value,
        search_after_cursor=search_after_cursor,
        size=size,
        source_fields=DARKNET_LIST_SOURCE_FIELDS,
    )

    try:
        response = os_client.search(index="darknet_index", body=body)
        hits = response["hits"]["hits"]
        results = [hit["_source"] for hit in hits]

        for index, hit in enumerate(hits):
            results[index]["os_doc_id"] = hit["_id"]

        next_cursor = hits[-1].get("sort") if hits else None
        return results, next_cursor
    except Exception as exc:
        print(f"OpenSearch Darknet Query Error: {exc}")
        return [], None


def get_darknet_stats(start_date=None, end_date=None, search_field=None, search_value=None):
    body = build_darknet_query(
        start_date=start_date,
        end_date=end_date,
        search_field=search_field,
        search_value=search_value,
        size=0,
    )
    body.pop("sort", None)
    body.pop("from", None)
    body = {
        **body,
        "aggs": {
            "distinct_root_domains": {
                "cardinality": {
                    "field": "root_domain",
                }
            }
        },
    }

    try:
        response = os_client.search(index="darknet_index", body=body)
        return {"distinct_count": response["aggregations"]["distinct_root_domains"]["value"]}
    except Exception as exc:
        print(f"OpenSearch Darknet Stats Error: {exc}")
        return {"distinct_count": None}


def export_telegram_data(start_date=None, end_date=None, search_field=None, search_value=None, limit=100000, batch_size=200):
    collected = []
    cursor = None

    while len(collected) < limit:
        size = min(batch_size, limit - len(collected))
        body = build_telegram_query(
            start_date=start_date,
            end_date=end_date,
            search_field=search_field,
            search_value=search_value,
            search_after_cursor=cursor,
            size=size,
            source_fields=TELEGRAM_EXPORT_SOURCE_FIELDS,
        )

        try:
            response = os_client.search(index="telegram_index", body=body)
        except Exception as exc:
            print(f"OpenSearch Telegram Export Error: {exc}")
            break

        hits = response["hits"]["hits"]
        if not hits:
            break

        collected.extend(hit["_source"] for hit in hits)
        cursor = hits[-1].get("sort")

        if len(hits) < size:
            break

    return collected


def export_darknet_data(start_date=None, end_date=None, search_field=None, search_value=None, limit=100000, batch_size=200):
    collected = []
    cursor = None

    while len(collected) < limit:
        size = min(batch_size, limit - len(collected))
        body = build_darknet_query(
            start_date=start_date,
            end_date=end_date,
            search_field=search_field,
            search_value=search_value,
            search_after_cursor=cursor,
            size=size,
            source_fields=DARKNET_EXPORT_SOURCE_FIELDS,
        )

        try:
            response = os_client.search(index="darknet_index", body=body)
        except Exception as exc:
            print(f"OpenSearch Darknet Export Error: {exc}")
            break

        hits = response["hits"]["hits"]
        if not hits:
            break

        collected.extend(hit["_source"] for hit in hits)
        cursor = hits[-1].get("sort")

        if len(hits) < size:
            break

    return collected
