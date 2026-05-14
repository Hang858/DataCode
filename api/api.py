import uvicorn
from fastapi import FastAPI, Query, HTTPException
from typing import List, Optional, Union
from datetime import date, datetime, timedelta
from pydantic import BaseModel
from opensearchpy import OpenSearch
import urllib3

# 忽略 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= 配置区域 =================
# OpenSearch 连接配置
OPENSEARCH_CONFIG = {
    'hosts': [{'host': '192.168.23.40', 'port': 9200}],
    'http_auth': ('admin', 'MyStrongPass123!'),
    'use_ssl': True,
    'verify_certs': False,
    'ssl_show_warn': False,
    'timeout': 30
}

INDEX_DARKNET = "darknet_index"
INDEX_TELEGRAM = "telegram_index"

# 初始化 OpenSearch 客户端
try:
    os_client = OpenSearch(**OPENSEARCH_CONFIG)
except Exception as e:
    print(f"初始化 OpenSearch 客户端失败: {e}")
# ===========================================

app = FastAPI(
    title="网络态势感知数据接口 (OpenSearch版)",
    description="提供暗网和Telegram数据的统计、排行及趋势分析接口",
    version="v2.0"
)

# --- 响应模型定义 ---
class DailyStats(BaseModel):
    date: str
    count: int

class RankItem(BaseModel):
    name: str
    count: int

class StatsResponse(BaseModel):
    code: int
    msg: str
    data: Union[dict, List, int]

# --- 通用查询执行器 ---
def execute_os_aggs(index_name: str, body: dict):
    try:
        return os_client.search(index=index_name, body=body)
    except Exception as e:
        print(f"OpenSearch Query Error: {e}")
        raise HTTPException(status_code=500, detail=f"搜索引擎查询失败: {str(e)}")


# ===========================================
#                 暗网 (Darknet) 接口
# ===========================================

@app.get("/api/darknet/daily-posts", summary="1. 每日发帖数量新增")
async def get_darknet_daily_posts(
    start_date: date = Query(..., description="开始日期 (YYYY-MM-DD)"),
    end_date: date = Query(..., description="结束日期 (YYYY-MM-DD)")
):
    """统计指定日期范围内，暗网数据的每日新增数量。"""
    body = {
        "size": 0, # 不需要返回具体文档，只要统计结果
        "query": {
            "range": {
                "msg_release_time": {
                    "gte": start_date.isoformat(),
                    "lte": end_date.isoformat()
                }
            }
        },
        "aggs": {
            "daily_posts": {
                "date_histogram": {
                    "field": "msg_release_time",
                    "calendar_interval": "day",
                    "format": "yyyy-MM-dd"
                }
            }
        }
    }
    res = execute_os_aggs(INDEX_DARKNET, body)
    buckets = res.get('aggregations', {}).get('daily_posts', {}).get('buckets', [])
    formatted_data = [{"date": b['key_as_string'], "count": b['doc_count']} for b in buckets]
    
    return {"code": 200, "msg": "success", "data": formatted_data}


@app.get("/api/darknet/site-count", summary="2. 暗网网站数量")
async def get_darknet_site_count():
    """统计暗网网站总数（去重域名）。"""
    body = {
        "size": 0,
        "aggs": {
            "unique_sites": {
                "cardinality": {
                    "field": "root_domain.keyword" # 使用 keyword 字段进行精确去重
                }
            }
        }
    }
    res = execute_os_aggs(INDEX_DARKNET, body)
    total = res.get('aggregations', {}).get('unique_sites', {}).get('value', 0)
    return {"code": 200, "msg": "success", "data": total}


@app.get("/api/darknet/daily-posts-cn", summary="3. 涉我每日发帖数量新增")
async def get_darknet_daily_cn(
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期")
):
    """统计涉及中国（regions_country=中国）的每日发帖数。"""
    body = {
        "size": 0,
        "query": {
            "bool": {
                "must": [
                    {"match": {"regions_country": "中国"}}
                ],
                "filter": [
                    {
                        "range": {
                            "msg_release_time": {
                                "gte": start_date.isoformat(),
                                "lte": end_date.isoformat()
                            }
                        }
                    }
                ]
            }
        },
        "aggs": {
            "daily_posts": {
                "date_histogram": {
                    "field": "msg_release_time",
                    "calendar_interval": "day",
                    "format": "yyyy-MM-dd"
                }
            }
        }
    }
    res = execute_os_aggs(INDEX_DARKNET, body)
    buckets = res.get('aggregations', {}).get('daily_posts', {}).get('buckets', [])
    formatted_data = [{"date": b['key_as_string'], "count": b['doc_count']} for b in buckets]
    return {"code": 200, "msg": "success", "data": formatted_data}


@app.get("/api/darknet/rank/websites", summary="4. 网站活跃排名")
async def get_website_rank(
    limit: Optional[int] = Query(None, description="限制返回数量，不填则返回全部（上限10000）")
):
    """统计发帖数最多的网站排名。"""
    size_limit = limit if limit is not None else 10000
    body = {
        "size": 0,
        "aggs": {
            "top_sites": {
                "terms": {
                    "field": "root_domain.keyword",
                    "size": size_limit
                }
            }
        }
    }
    res = execute_os_aggs(INDEX_DARKNET, body)
    buckets = res.get('aggregations', {}).get('top_sites', {}).get('buckets', [])
    formatted_data = [{"name": b['key'], "count": b['doc_count']} for b in buckets]
    return {"code": 200, "msg": "success", "data": formatted_data}


@app.get("/api/darknet/rank/authors", summary="5. 60天发帖人活跃排名")
async def get_author_rank(
    limit: Optional[int] = Query(None, description="限制返回数量，不填则返回全部（上限10000）")
):
    """统计最近60天内最活跃的作者。"""
    size_limit = limit if limit is not None else 10000
    sixty_days_ago = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S")
    
    body = {
        "size": 0,
        "query": {
            "range": {
                "msg_release_time": {
                    "gte": sixty_days_ago
                }
            }
        },
        "aggs": {
            "top_authors": {
                "terms": {
                    "field": "msg_author.keyword",
                    "size": size_limit
                }
            }
        }
    }
    res = execute_os_aggs(INDEX_DARKNET, body)
    buckets = res.get('aggregations', {}).get('top_authors', {}).get('buckets', [])
    formatted_data = [{"name": b['key'], "count": b['doc_count']} for b in buckets]
    return {"code": 200, "msg": "success", "data": formatted_data}


@app.get("/api/darknet/ransomware-count", summary="6. 勒索组织数量")
async def get_ransomware_count():
    """统计标签包含'黑客组织'的组织数量。"""
    body = {
        "size": 0,
        "query": {
            "match": {
                "tags": "黑客组织"
            }
        },
        "aggs": {
            "unique_orgs": {
                "cardinality": {
                    "field": "org.keyword"
                }
            }
        }
    }
    res = execute_os_aggs(INDEX_DARKNET, body)
    total = res.get('aggregations', {}).get('unique_orgs', {}).get('value', 0)
    return {"code": 200, "msg": "success", "data": total}


# ===========================================
#                 电报 (Telegram) 接口
# ===========================================

@app.get("/api/telegram/group-count", summary="7. 电报群组数量")
async def get_telegram_group_count():
    """统计监控的电报群组总数。"""
    body = {
        "size": 0,
        "aggs": {
            "unique_groups": {
                "cardinality": {
                    "field": "chat_id.keyword"
                }
            }
        }
    }
    res = execute_os_aggs(INDEX_TELEGRAM, body)
    total = res.get('aggregations', {}).get('unique_groups', {}).get('value', 0)
    return {"code": 200, "msg": "success", "data": total}


@app.get("/api/telegram/rank/groups", summary="8. 活跃群组排名")
async def get_telegram_group_rank(
    limit: Optional[int] = Query(None, description="限制返回数量，不填则返回全部（上限10000）")
):
    """统计发言最活跃的群组。"""
    size_limit = limit if limit is not None else 10000
    body = {
        "size": 0,
        "aggs": {
            "top_groups": {
                "terms": {
                    "field": "chat_name.keyword",
                    "size": size_limit
                }
            }
        }
    }
    res = execute_os_aggs(INDEX_TELEGRAM, body)
    buckets = res.get('aggregations', {}).get('top_groups', {}).get('buckets', [])
    formatted_data = [{"name": b['key'], "count": b['doc_count']} for b in buckets]
    return {"code": 200, "msg": "success", "data": formatted_data}


if __name__ == "__main__":
    # 启动服务
    uvicorn.run(app, host="0.0.0.0", port=9090)