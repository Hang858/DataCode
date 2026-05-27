import datetime
import hashlib
import json
import threading
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_exempt
from openpyxl import Workbook

from .models import ExportTask, ParamConfig, ParamSubmission, ParamTaskFilter, StatsCache
from .services import (
    export_darknet_data,
    export_telegram_data,
    get_darknet_stats,
    get_telegram_stats,
    search_darknet_data,
    search_telegram_data,
)


TELEGRAM_FIELD_MAPPING = {
    "_id": "_id",
    "消息内容": "content_text",
    "群组ID": "chat_id",
    "群组名称": "chat_name",
    "事件": "event",
    "文件扩展名": "file_extension",
    "行业": "industry",
    "媒体文件URL": "media_file_url",
    "媒体类型": "media_type",
    "消息日期": "message_date",
    "消息ID": "message_id",
    "消息时间": "message_time",
    "组织": "org",
    "地区": "regions",
    "发送者名字": "sender_first_name",
    "发送者姓氏": "sender_last_name",
    "发送者ID": "sender_id",
    "发送者电话": "sender_phone",
    "发送者用户名": "sender_username",
    "标签": "tags",
    "页面类型": "type",
    "子文件": "sub_file",
}

TELEGRAM_SEARCH_FIELD_OPTIONS = [
    ("", "全局搜索 (自动匹配核心字段)"),
    ("content_text", "消息内容"),
    ("chat_name", "群组名称"),
    ("org", "组织"),
    ("event", "事件"),
    ("industry", "行业"),
    ("tags", "标签"),
    ("sender_first_name", "发送者名字"),
    ("sender_last_name", "发送者姓氏"),
    ("_id", "_id (原始ID)"),
    ("chat_id", "群组ID"),
    ("message_id", "消息ID"),
    ("sender_id", "发送者ID"),
    ("sender_username", "发送者用户名"),
]

DARKNET_FIELD_NAME_MAPPING = {
    "_id": "_id",
    "网页标题": "title",
    "网页URL": "url",
    "来源": "source",
    "机构": "institution",
    "详情解析": "detail_analysis",
    "事件": "event",
    "行业": "industry",
    "作者": "author",
    "标题(中文)": "title_cn",
    "消息描述": "message_description",
    "路径": "path",
    "城市": "city",
    "国家": "country",
    "省份": "province",
    "根域名": "root_domain",
    "标签": "tags",
    "顶级域名": "top_level_domain",
    "用户ID": "user_id",
    "消息截图": "message_screenshot",
    "关键词": "keywords",
}

DARKNET_FIELD_MAPPING = {
    "detail_analysis": "detail_parsing",
    "institution": "org",
    "title_cn": "msg_title_cn",
    "message_description": "msg_description",
    "city": "regions_city",
    "country": "regions_country",
    "province": "regions_province",
    "top_level_domain": "toplv_domain",
    "author": "msg_author",
    "message_screenshot": "msg_sample_ss",
    "keywords": "msg_keyword",
}

DARKNET_SEARCH_FIELD_OPTIONS = [
    ("", "全局搜索 (自动匹配核心字段)"),
    ("title", "网页标题"),
    ("msg_author", "作者"),
    ("msg_title_cn", "标题(中文)"),
    ("msg_description", "消息描述"),
    ("event", "事件 (模糊搜索)"),
    ("_id", "_id (原始ID)"),
    ("url", "网页URL"),
    ("root_domain", "根域名"),
    ("toplv_domain", "顶级域名"),
    ("user_id", "用户ID"),
    ("industry", "行业 (精确匹配)"),
    ("tags", "标签 (精确匹配)"),
]

EXPORT_DIR = Path(settings.BASE_DIR) / "tmp_exports"
EXPORT_MAX_ROWS = 100000


def format_array_field(value):
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return value


def parse_search_after_cursor(request):
    search_after_param = request.GET.get("search_after")
    if not search_after_param:
        return None

    try:
        return json.loads(search_after_param)
    except (TypeError, json.JSONDecodeError):
        return None


def is_ajax_request(request):
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.GET.get("ajax") == "true"
    )


def build_ajax_response(data, next_cursor):
    return JsonResponse(
        {
            "data": data,
            "next_cursor": next_cursor,
            "has_more": bool(next_cursor),
        }
    )


def absolute_url(request, route_name, *args):
    return request.build_absolute_uri(route_name if route_name.startswith(("http://", "https://")) else route_name)


def get_next_cursor_json(next_cursor):
    return json.dumps(next_cursor) if next_cursor else ""


def get_embed_api_base_url(request):
    configured = getattr(settings, "EMBED_API_BASE_URL", "")
    if configured:
        return configured.rstrip("/")
    return request.build_absolute_uri("/").rstrip("/")


def get_stats_cache_key(dataset_key, start_date=None, end_date=None, search_field=None, search_value=None):
    params = {
        "start_date": start_date or "",
        "end_date": end_date or "",
        "search_field": search_field or "",
        "search_value": search_value or "",
    }
    raw_key = f"{dataset_key}:{json.dumps(params, ensure_ascii=False, sort_keys=True)}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def get_cached_stats(cache_key):
    stats = StatsCache.objects.filter(cache_key=cache_key).first()
    if not stats:
        return {}
    return {
        "dataset": stats.dataset,
        "distinct_count": stats.distinct_count,
        "updated_at": stats.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


def update_cached_stats(cache_key, dataset_key, distinct_count):
    stats, _ = StatsCache.objects.update_or_create(
        cache_key=cache_key,
        defaults={
            "dataset": dataset_key,
            "distinct_count": distinct_count,
        },
    )
    return {
        "dataset": stats.dataset,
        "distinct_count": stats.distinct_count,
        "updated_at": stats.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


def upsert_unique_param_row(model, task_id, defaults):
    rows = list(model.objects.filter(task_id=task_id).order_by("-created_at", "-id"))
    if rows:
        row = rows[0]
        for field_name, value in defaults.items():
            setattr(row, field_name, value)
        row.save(update_fields=[*defaults.keys()])
        stale_ids = [stale.id for stale in rows[1:]]
        if stale_ids:
            model.objects.filter(id__in=stale_ids).delete()
        return row, False
    return model.objects.create(task_id=task_id, **defaults), True


def create_task_filter(task_id, dataset, search_field, search_value, sort_order):
    search_field = (search_field or "").strip()
    search_value = (search_value or "").strip()
    if not search_value:
        return None
    row = ParamTaskFilter.objects.create(
        task_id=task_id,
        dataset=dataset,
        search_field=search_field or None,
        operator="auto",
        search_value=search_value,
        connector="AND",
        enabled=True,
        sort_order=sort_order,
    )
    return row


def upsert_task_filter(task_id, dataset, search_field, search_value):
    ParamTaskFilter.objects.filter(task_id=task_id, dataset=dataset).delete()
    return create_task_filter(task_id, dataset, search_field, search_value, 1)


def upsert_task_filters(task_id, dataset, filters):
    ParamTaskFilter.objects.filter(task_id=task_id, dataset=dataset).delete()
    rows = []
    for index, item in enumerate(filters, start=1):
        row = create_task_filter(
            task_id,
            dataset,
            item.get("search_field"),
            item.get("search_value"),
            index,
        )
        if row:
            rows.append(row)
    return rows


def normalize_filter_rows(filters, limit=3):
    rows = []
    for item in filters[:limit]:
        rows.append(
            {
                "search_field": item.get("search_field") or "",
                "search_value": item.get("search_value") or "",
            }
        )
    while len(rows) < limit:
        rows.append({"search_field": "", "search_value": ""})
    return rows


def build_setparams_context(
    task_id=None,
    start_date=None,
    end_date=None,
    telegram_checked=False,
    darknet_checked=False,
    telegram_search_field="",
    telegram_search_value="",
    darknet_filters=None,
    submitted=False,
    error_message=None,
    has_record=False,
):
    normalized_darknet_filters = normalize_filter_rows(darknet_filters or [])
    return {
        "task_id": task_id,
        "start_date": start_date,
        "end_date": end_date,
        "telegram_checked": telegram_checked,
        "darknet_checked": darknet_checked,
        "telegram_search_field": telegram_search_field or "",
        "telegram_search_value": telegram_search_value or "",
        "darknet_filters": normalized_darknet_filters,
        "darknet_filter_1": normalized_darknet_filters[0],
        "darknet_filter_2": normalized_darknet_filters[1],
        "darknet_filter_3": normalized_darknet_filters[2],
        "telegram_search_field_options": TELEGRAM_SEARCH_FIELD_OPTIONS,
        "darknet_search_field_options": DARKNET_SEARCH_FIELD_OPTIONS,
        "submitted": submitted,
        "error_message": error_message,
        "has_record": has_record,
    }


def build_workbook_bytes(sheet_title, headers, rows):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_title
    worksheet.append(headers)

    for row in rows:
        worksheet.append(row)

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output.getvalue()


def build_excel_response(filename, sheet_title, headers, rows):
    output_bytes = build_workbook_bytes(sheet_title, headers, rows)

    response = HttpResponse(
        output_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def create_export_task(dataset, filters_json):
    return ExportTask.objects.create(
        dataset=dataset,
        status=ExportTask.STATUS_PENDING,
        filters_json=filters_json,
    )


def run_export_task(task_id):
    task = ExportTask.objects.get(id=task_id)
    task.status = ExportTask.STATUS_RUNNING
    task.error_message = ""
    task.save(update_fields=["status", "error_message", "updated_at"])

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    filters = task.filters_json or {}

    try:
        if task.dataset == "telegram":
            actual_search_field = TELEGRAM_FIELD_MAPPING.get(filters.get("search_field"), filters.get("search_field"))
            items = export_telegram_data(
                start_date=filters.get("start_date"),
                end_date=filters.get("end_date"),
                search_field=actual_search_field,
                search_value=filters.get("search_value"),
                limit=EXPORT_MAX_ROWS,
            )
            rows = build_telegram_export_rows(items)
            headers = [
                "时间戳",
                "群组ID",
                "群组名称",
                "消息内容",
                "消息日期",
                "消息ID",
                "消息时间",
                "发送者名字",
                "发送者姓氏",
                "发送者ID",
                "发送者电话",
                "发送者用户名",
            ]
            sheet_title = "Telegram"
        else:
            search_field = filters.get("search_field")
            search_value = filters.get("search_value")
            actual_search_field = search_field
            if search_field and search_value:
                english_field = DARKNET_FIELD_NAME_MAPPING.get(search_field, search_field)
                actual_search_field = DARKNET_FIELD_MAPPING.get(english_field, english_field)
            items = export_darknet_data(
                start_date=filters.get("start_date"),
                end_date=filters.get("end_date"),
                search_field=actual_search_field,
                search_value=search_value,
                limit=EXPORT_MAX_ROWS,
            )
            rows = build_darknet_export_rows(items)
            headers = [
                "网页标题",
                "网页URL",
                "发布时间",
                "来源",
                "作者",
                "消息描述",
                "根域名",
                "时间戳",
                "顶级域名",
            ]
            sheet_title = "Darknet"

        file_name = f"{task.dataset}_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        file_path = EXPORT_DIR / file_name
        file_path.write_bytes(build_workbook_bytes(sheet_title, headers, rows))

        task.status = ExportTask.STATUS_SUCCESS
        task.file_name = file_name
        task.file_path = str(file_path)
        task.row_count = len(rows)
        task.save(update_fields=["status", "file_name", "file_path", "row_count", "updated_at"])
    except Exception as exc:
        task.status = ExportTask.STATUS_FAILED
        task.error_message = str(exc)
        task.save(update_fields=["status", "error_message", "updated_at"])


def start_export_task_async(task_id):
    thread = threading.Thread(target=run_export_task, args=(task_id,), daemon=True)
    thread.start()


def normalize_telegram_item(item):
    return {
        "id": item.get("id", ""),
        "id_field": item.get("original_id", item.get("_id", "")),
        "timestamp": item.get("timestamp", ""),
        "chat_id": item.get("chat_id", ""),
        "chat_name": item.get("chat_name", ""),
        "content_text": item.get("content_text", ""),
        "content_text_md5": item.get("content_text_md5", ""),
        "event": format_array_field(item.get("event", [])),
        "file_extension": item.get("file_extension", ""),
        "hot": item.get("hot", ""),
        "industry": format_array_field(item.get("industry", [])),
        "media_file_url": item.get("media_file_url", ""),
        "media_type": item.get("media_type", ""),
        "message_date": item.get("message_date", ""),
        "message_id": item.get("message_id", ""),
        "message_time": item.get("message_time", ""),
        "org": format_array_field(item.get("org", [])),
        "regions": format_array_field(item.get("regions", [])),
        "sender_first_name": item.get("sender_first_name", ""),
        "sender_last_name": item.get("sender_last_name", ""),
        "sender_id": item.get("sender_id", ""),
        "sender_phone": item.get("sender_phone", ""),
        "sender_username": item.get("sender_username", ""),
        "tags": format_array_field(item.get("tags", [])),
        "page_type": item.get("page_type", ""),
        "child_file": item.get("child_file", ""),
    }


def normalize_darknet_item(item):
    return {
        "id": item.get("id", ""),
        "id_field": item.get("original_id", item.get("_id", "")),
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "msg_release_time": item.get("msg_release_time", ""),
        "source": item.get("source", ""),
        "status_code": item.get("status_code", ""),
        "org": format_array_field(item.get("org", [])) if item.get("org") else "无",
        "body_md5": item.get("body_md5", ""),
        "description": item.get("description", ""),
        "detail_parsing": item.get("detail_parsing", ""),
        "event": format_array_field(item.get("event", [])),
        "industry": format_array_field(item.get("industry", [])),
        "is_read": item.get("is_read", ""),
        "msg_author": item.get("msg_author", ""),
        "msg_title_cn": item.get("msg_title_cn", ""),
        "msg_description": item.get("msg_description", ""),
        "path": item.get("path", ""),
        "regions_city": format_array_field(item.get("regions_city", [])),
        "regions_country": format_array_field(item.get("regions_country", [])),
        "regions_province": format_array_field(item.get("regions_province", [])),
        "root_domain": item.get("root_domain", ""),
        "tags": format_array_field(item.get("tags", [])),
        "timestamp": item.get("timestamp", ""),
        "toplv_domain": item.get("toplv_domain", ""),
        "update_time": item.get("update_time", ""),
        "user_id": item.get("user_id", ""),
        "to_new": item.get("to_new", ""),
        "body": item.get("body", ""),
        "msg_sample_ss": item.get("msg_sample_ss", ""),
        "msg_keyword": item.get("msg_keyword", ""),
        "msg_webpage_ss": item.get("msg_webpage_ss", ""),
        "child_file": item.get("child_file", ""),
    }


def build_telegram_export_rows(items):
    rows = []
    for item in items:
        rows.append(
            [
                item.get("timestamp", ""),
                item.get("chat_id", ""),
                item.get("chat_name", ""),
                item.get("content_text", ""),
                item.get("message_date", ""),
                item.get("message_id", ""),
                item.get("message_time", ""),
                item.get("sender_first_name", ""),
                item.get("sender_last_name", ""),
                item.get("sender_id", ""),
                item.get("sender_phone", ""),
                item.get("sender_username", ""),
            ]
        )
    return rows


def build_darknet_export_rows(items):
    rows = []
    for item in items:
        rows.append(
            [
                item.get("title", ""),
                item.get("url", ""),
                item.get("msg_release_time", ""),
                item.get("source", ""),
                item.get("msg_author", ""),
                item.get("msg_description", ""),
                item.get("root_domain", ""),
                item.get("timestamp", ""),
                item.get("toplv_domain", ""),
            ]
        )
    return rows


@xframe_options_exempt
def telegram_view(request):
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    search_field = request.GET.get("search_field")
    search_value = request.GET.get("search_value")
    actual_search_field = TELEGRAM_FIELD_MAPPING.get(search_field, search_field)

    results, next_cursor = search_telegram_data(
        start_date=start_date,
        end_date=end_date,
        search_field=actual_search_field,
        search_value=search_value,
        search_after_cursor=parse_search_after_cursor(request),
        size=50,
    )

    processed_data = [normalize_telegram_item(item) for item in results]

    if is_ajax_request(request):
        return build_ajax_response(processed_data, next_cursor)

    stats_cache_key = get_stats_cache_key(
        "telegram",
        start_date=start_date,
        end_date=end_date,
        search_field=actual_search_field,
        search_value=search_value,
    )
    stats_cache = get_cached_stats(stats_cache_key)
    embed_api_base_url = get_embed_api_base_url(request)

    return render(
        request,
        "db_display/telegram.html",
        {
            "telegram_data": processed_data,
            "next_cursor_json": get_next_cursor_json(next_cursor),
            "distinct_chat_ids_count": stats_cache.get("distinct_count"),
            "stats_updated_at": stats_cache.get("updated_at"),
            "search_field_options": TELEGRAM_SEARCH_FIELD_OPTIONS,
            "export_max_rows": EXPORT_MAX_ROWS,
            "embed_api_base_url": embed_api_base_url,
            "telegram_absolute_url": f"{embed_api_base_url}/telegram/",
            "telegram_stats_refresh_absolute_url": f"{embed_api_base_url}/telegram/stats-refresh/",
            "telegram_export_create_absolute_url": f"{embed_api_base_url}/telegram/export-create/",
            "export_task_status_template_absolute_url": f"{embed_api_base_url}/export-task/0/status/",
            "export_task_download_template_absolute_url": f"{embed_api_base_url}/export-task/0/download/",
        },
    )


@xframe_options_exempt
def darknet_view(request):
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    search_field = request.GET.get("search_field")
    search_value = request.GET.get("search_value")

    actual_search_field = search_field
    if search_field and search_value:
        english_field = DARKNET_FIELD_NAME_MAPPING.get(search_field, search_field)
        actual_search_field = DARKNET_FIELD_MAPPING.get(english_field, english_field)

    results, next_cursor = search_darknet_data(
        start_date=start_date,
        end_date=end_date,
        search_field=actual_search_field,
        search_value=search_value,
        search_after_cursor=parse_search_after_cursor(request),
        size=50,
    )

    processed_data = [normalize_darknet_item(item) for item in results]

    if is_ajax_request(request):
        return build_ajax_response(processed_data, next_cursor)

    stats_cache_key = get_stats_cache_key(
        "darknet",
        start_date=start_date,
        end_date=end_date,
        search_field=actual_search_field,
        search_value=search_value,
    )
    stats_cache = get_cached_stats(stats_cache_key)
    embed_api_base_url = get_embed_api_base_url(request)

    return render(
        request,
        "db_display/darknet.html",
        {
            "darknet_data": processed_data,
            "next_cursor_json": get_next_cursor_json(next_cursor),
            "distinct_root_domains_count": stats_cache.get("distinct_count"),
            "stats_updated_at": stats_cache.get("updated_at"),
            "search_field_options": DARKNET_SEARCH_FIELD_OPTIONS,
            "export_max_rows": EXPORT_MAX_ROWS,
            "embed_api_base_url": embed_api_base_url,
            "darknet_absolute_url": f"{embed_api_base_url}/darknet/",
            "darknet_stats_refresh_absolute_url": f"{embed_api_base_url}/darknet/stats-refresh/",
            "darknet_export_create_absolute_url": f"{embed_api_base_url}/darknet/export-create/",
            "export_task_status_template_absolute_url": f"{embed_api_base_url}/export-task/0/status/",
            "export_task_download_template_absolute_url": f"{embed_api_base_url}/export-task/0/download/",
        },
    )


@csrf_exempt
@xframe_options_exempt
def telegram_stats_refresh(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    search_field = request.GET.get("search_field")
    search_value = request.GET.get("search_value")
    actual_search_field = TELEGRAM_FIELD_MAPPING.get(search_field, search_field)

    stats = get_telegram_stats(
        start_date=start_date,
        end_date=end_date,
        search_field=actual_search_field,
        search_value=search_value,
    )
    if stats["distinct_count"] is None:
        return JsonResponse({"error": "统计更新失败"}, status=500)

    cache_key = get_stats_cache_key(
        "telegram",
        start_date=start_date,
        end_date=end_date,
        search_field=actual_search_field,
        search_value=search_value,
    )
    cached = update_cached_stats(cache_key, "telegram", stats["distinct_count"])
    cached["total_count"] = stats.get("total_count")
    return JsonResponse(cached)


@csrf_exempt
@xframe_options_exempt
def darknet_stats_refresh(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    search_field = request.GET.get("search_field")
    search_value = request.GET.get("search_value")

    actual_search_field = search_field
    if search_field and search_value:
        english_field = DARKNET_FIELD_NAME_MAPPING.get(search_field, search_field)
        actual_search_field = DARKNET_FIELD_MAPPING.get(english_field, english_field)

    stats = get_darknet_stats(
        start_date=start_date,
        end_date=end_date,
        search_field=actual_search_field,
        search_value=search_value,
    )
    if stats["distinct_count"] is None:
        return JsonResponse({"error": "统计更新失败"}, status=500)

    cache_key = get_stats_cache_key(
        "darknet",
        start_date=start_date,
        end_date=end_date,
        search_field=actual_search_field,
        search_value=search_value,
    )
    cached = update_cached_stats(cache_key, "darknet", stats["distinct_count"])
    cached["total_count"] = stats.get("total_count")
    return JsonResponse(cached)


@xframe_options_exempt
def home(request):
    return render(request, "db_display/home.html")


@xframe_options_exempt
def setparams_view(request):
    task_id = request.GET.get("task") or request.GET.get("task_id")

    if request.method == "POST":
        task_id = request.POST.get("task_id") or task_id
        start_date = request.POST.get("start_date")
        end_date = request.POST.get("end_date")
        telegram_checked = request.POST.get("telegram") == "on"
        darknet_checked = request.POST.get("darknet") == "on"
        telegram_search_field = request.POST.get("telegram_search_field")
        telegram_search_value = request.POST.get("telegram_search_value")
        darknet_filters = [
            {
                "search_field": request.POST.get(f"darknet_search_field_{index}") or "",
                "search_value": request.POST.get(f"darknet_search_value_{index}") or "",
            }
            for index in range(1, 4)
        ]

        if not task_id:
            context = build_setparams_context(
                task_id=task_id,
                start_date=start_date,
                end_date=end_date,
                telegram_checked=telegram_checked,
                darknet_checked=darknet_checked,
                telegram_search_field=telegram_search_field,
                telegram_search_value=telegram_search_value,
                darknet_filters=darknet_filters,
                error_message="缺少 task_id，无法保存参数",
            )
            return render(request, "db_display/setparams.html", context)

        if not telegram_checked and not darknet_checked:
            context = build_setparams_context(
                task_id=task_id,
                start_date=start_date,
                end_date=end_date,
                telegram_checked=telegram_checked,
                darknet_checked=darknet_checked,
                telegram_search_field=telegram_search_field,
                telegram_search_value=telegram_search_value,
                darknet_filters=darknet_filters,
                error_message="必须选择一个数据源",
            )
            return render(request, "db_display/setparams.html", context)

        if start_date and end_date:
            upsert_unique_param_row(
                ParamSubmission,
                task_id=task_id,
                defaults={
                    "start_date": parse_date(start_date) if start_date else None,
                    "end_date": parse_date(end_date) if end_date else None,
                    "telegram": telegram_checked,
                    "darknet": darknet_checked,
                },
            )
            if telegram_checked:
                upsert_task_filter(task_id, "telegram", telegram_search_field, telegram_search_value)
            else:
                ParamTaskFilter.objects.filter(task_id=task_id, dataset="telegram").delete()
            if darknet_checked:
                upsert_task_filters(task_id, "darknet", darknet_filters)
            else:
                ParamTaskFilter.objects.filter(task_id=task_id, dataset="darknet").delete()

            context = build_setparams_context(
                task_id=task_id,
                start_date=start_date,
                end_date=end_date,
                telegram_checked=telegram_checked,
                darknet_checked=darknet_checked,
                telegram_search_field=telegram_search_field,
                telegram_search_value=telegram_search_value,
                darknet_filters=darknet_filters,
                submitted=True,
                has_record=True,
            )
        else:
            context = build_setparams_context(
                task_id=task_id,
                start_date=start_date,
                end_date=end_date,
                telegram_checked=telegram_checked,
                darknet_checked=darknet_checked,
                telegram_search_field=telegram_search_field,
                telegram_search_value=telegram_search_value,
                darknet_filters=darknet_filters,
                error_message="请选择完整的起止日期",
            )

        return render(request, "db_display/setparams.html", context)

    if task_id:
        try:
            submission = ParamSubmission.objects.filter(task_id=task_id).order_by("-created_at").first()
            task_filters = {
                row.dataset: row
                for row in ParamTaskFilter.objects.filter(task_id=task_id, enabled=True).order_by("dataset", "sort_order", "id")
            }
            darknet_filter_rows = [
                {"search_field": row.search_field, "search_value": row.search_value}
                for row in ParamTaskFilter.objects.filter(task_id=task_id, dataset="darknet", enabled=True).order_by("sort_order", "id")[:3]
            ]
            telegram_filter = task_filters.get("telegram")
            if submission:
                context = build_setparams_context(
                    task_id=task_id,
                    start_date=submission.start_date.strftime("%Y-%m-%d") if submission.start_date else "",
                    end_date=submission.end_date.strftime("%Y-%m-%d") if submission.end_date else "",
                    telegram_checked=submission.telegram,
                    darknet_checked=submission.darknet,
                    telegram_search_field=telegram_filter.search_field if telegram_filter else "",
                    telegram_search_value=telegram_filter.search_value if telegram_filter else "",
                    darknet_filters=darknet_filter_rows,
                    has_record=True,
                )
            else:
                context = build_setparams_context(
                    task_id=task_id,
                    start_date=request.GET.get("start_date"),
                    end_date=request.GET.get("end_date"),
                    telegram_search_field=telegram_filter.search_field if telegram_filter else "",
                    telegram_search_value=telegram_filter.search_value if telegram_filter else "",
                    darknet_filters=darknet_filter_rows,
                )
        except Exception as exc:
            context = build_setparams_context(
                task_id=task_id,
                start_date=request.GET.get("start_date"),
                end_date=request.GET.get("end_date"),
                error_message=f"查询失败: {exc}",
            )
    else:
        context = build_setparams_context(
            task_id=task_id,
            start_date=request.GET.get("start_date"),
            end_date=request.GET.get("end_date"),
        )

    return render(request, "db_display/setparams.html", context)


@xframe_options_exempt
def parameter_config_view(request):
    task_id = request.GET.get("task") or request.GET.get("task_id")

    if request.method == "POST":
        task_id = request.POST.get("task_id")
        telegram_checked = request.POST.get("telegram") == "on"
        darknet_checked = request.POST.get("darknet") == "on"
        time_period = request.POST.get("time_period")
        send_days = request.POST.get("send_days")

        base_context = {
            "task_id": task_id,
            "telegram_checked": telegram_checked,
            "darknet_checked": darknet_checked,
            "time_period": time_period,
            "send_days": send_days,
            "submitted": False,
        }

        if not task_id:
            base_context["error_message"] = "缺少 task_id，无法保存参数配置"
            return render(request, "db_display/parameter_config.html", base_context)

        if not telegram_checked and not darknet_checked:
            base_context["error_message"] = "必须选择一个数据源"
            return render(request, "db_display/parameter_config.html", base_context)

        if not time_period or not send_days:
            base_context["error_message"] = "时间周期和发送天数不能为空"
            return render(request, "db_display/parameter_config.html", base_context)

        try:
            upsert_unique_param_row(
                ParamConfig,
                task_id=task_id,
                defaults={
                    "time_period": time_period,
                    "send_time": send_days,
                    "telegram": telegram_checked,
                    "darknet": darknet_checked,
                },
            )

            base_context["submitted"] = True
            base_context["success_message"] = "参数配置已成功保存"
        except Exception as exc:
            base_context["error_message"] = f"保存失败: {exc}"

        return render(request, "db_display/parameter_config.html", base_context)

    context = {
        "task_id": task_id or "",
        "telegram_checked": False,
        "darknet_checked": False,
        "time_period": "",
        "send_days": "",
        "submitted": False,
        "has_record": False,
    }

    if not task_id:
        return render(request, "db_display/parameter_config.html", context)

    try:
        config = ParamConfig.objects.filter(task_id=task_id).first()
        if config:
            context.update(
                {
                    "telegram_checked": config.telegram,
                    "darknet_checked": config.darknet,
                    "time_period": config.time_period,
                    "send_days": config.send_time,
                    "has_record": True,
                    "info_message": f"task {task_id} 已存在",
                }
            )
        else:
            context.update(
                {
                    "task_id": task_id,
                    "telegram_checked": False,
                    "darknet_checked": False,
                    "time_period": "",
                    "send_days": "",
                    "submitted": False,
                    "has_record": False,
                }
            )
    except Exception as exc:
        context["error_message"] = f"查询失败: {exc}"

    return render(request, "db_display/parameter_config.html", context)


@xframe_options_exempt
def telegram_export_excel(request):
    return JsonResponse({"error": "请通过异步导出接口发起任务"}, status=405)


@xframe_options_exempt
def darknet_export_excel(request):
    return JsonResponse({"error": "请通过异步导出接口发起任务"}, status=405)


@csrf_exempt
@xframe_options_exempt
def telegram_export_create(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    filters_json = {
        "start_date": request.GET.get("start_date"),
        "end_date": request.GET.get("end_date"),
        "search_field": request.GET.get("search_field"),
        "search_value": request.GET.get("search_value"),
    }
    task = create_export_task("telegram", filters_json)
    start_export_task_async(task.id)
    return JsonResponse({"task_id": task.id, "status": task.status})


@csrf_exempt
@xframe_options_exempt
def darknet_export_create(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    filters_json = {
        "start_date": request.GET.get("start_date"),
        "end_date": request.GET.get("end_date"),
        "search_field": request.GET.get("search_field"),
        "search_value": request.GET.get("search_value"),
    }
    task = create_export_task("darknet", filters_json)
    start_export_task_async(task.id)
    return JsonResponse({"task_id": task.id, "status": task.status})


@xframe_options_exempt
def export_task_status(request, task_id):
    task = ExportTask.objects.filter(id=task_id).first()
    if not task:
        return JsonResponse({"error": "任务不存在"}, status=404)

    return JsonResponse(
        {
            "task_id": task.id,
            "status": task.status,
            "row_count": task.row_count,
            "file_name": task.file_name,
            "error_message": task.error_message,
        }
    )


@xframe_options_exempt
def export_task_download(request, task_id):
    task = ExportTask.objects.filter(id=task_id, status=ExportTask.STATUS_SUCCESS).first()
    if not task or not task.file_path:
        raise Http404("导出文件不存在")

    file_path = Path(task.file_path)
    if not file_path.exists():
        raise Http404("导出文件不存在")

    return FileResponse(
        file_path.open("rb"),
        as_attachment=True,
        filename=task.file_name or file_path.name,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def parse_date(date_str):
    try:
        if "-" in date_str:
            return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        if "/" in date_str:
            return datetime.datetime.strptime(date_str, "%Y/%m/%d").date()
        return None
    except Exception:
        return None
