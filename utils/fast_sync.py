import pymysql
from pymysql.cursors import SSDictCursor
from opensearchpy import OpenSearch
from datetime import datetime, date
import urllib3
import logging
from tqdm import tqdm  # 引入进度条库
from opensearchpy.helpers import parallel_bulk

# 1. 忽略 SSL 警告，并关闭 OpenSearch 底层的疯狂刷屏日志
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.getLogger("opensearch").setLevel(logging.WARNING)

# ================= 配置区 =================
MYSQL_CONFIG = {
    'host': '192.168.23.204',
    'port': 3306,
    'user': 'root',
    'password': 'MyPass123!',  # 替换成你的密码
    'database': 'online',
    'charset': 'utf8mb4'
}

OPENSEARCH_CONFIG = {
    'hosts': [{'host': '192.168.23.204', 'port': 9200}],
    'http_auth': ('admin', 'MyStrongPass123!'),
    'use_ssl': True,
    'verify_certs': False,
    'ssl_show_warn': False
}
# ==========================================

def get_mysql_conn(dict_cursor=True):
    # 如果 dict_cursor 为 True，使用流式字典游标；否则使用普通游标（用于查总数）
    cursor_cls = SSDictCursor if dict_cursor else pymysql.cursors.Cursor
    return pymysql.connect(**MYSQL_CONFIG, cursorclass=cursor_cls)

def get_os_client():
    return OpenSearch(**OPENSEARCH_CONFIG)


def normalize_time_value(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    return value

def get_total_count(table_name):
    """获取 MySQL 表的总数据量，用于进度条展示"""
    conn = get_mysql_conn(dict_cursor=False)
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        total = cursor.fetchone()[0]
    conn.close()
    return total

def generate_bulk_actions(mysql_conn, table_name, index_name, pbar):
    with mysql_conn.cursor() as cursor:
        # 正式迁移请去掉 LIMIT，如果是测试可以加上 LIMIT 10000
        cursor.execute(f"SELECT * FROM {table_name}") 
        
        while True:
            row = cursor.fetchone()
            if not row:
                break
                
            # 时间格式转换
            for key, value in row.items():
                row[key] = normalize_time_value(value)
            
            if "_id" in row:
                row["original_id"] = row.pop("_id")
            
            # 更新进度条
            pbar.update(1)
            
            yield {
                "_index": index_name,
                "_id": row["id"],
                "_source": row
            }


def get_bulk_options(table_name):
    if table_name == "darknet":
        return {
            "thread_count": 1,
            "chunk_size": 20,
            "queue_size": 4,
        }
    return {
        "thread_count": 8,
        "chunk_size": 50,
        "queue_size": 16,
    }

def sync_table(table_name, index_name):
    print(f"\n🚀 开始计算 [{table_name}] 表的总数据量...")
    total_count = get_total_count(table_name)
    print(f"📊 [{table_name}] 共有 {total_count} 条数据待迁移。")

    mysql_conn = get_mysql_conn(dict_cursor=True)
    os_client = get_os_client()
    bulk_options = get_bulk_options(table_name)
    
    try:
        with tqdm(total=total_count, desc=f"同步 {table_name}", unit="条") as pbar:
            success_count = 0
            errors = []
            
            # 使用 parallel_bulk 进行多线程高并发写入
            for success, info in parallel_bulk(
                os_client, 
                generate_bulk_actions(mysql_conn, table_name, index_name, pbar),
                thread_count=bulk_options["thread_count"],
                chunk_size=bulk_options["chunk_size"],
                queue_size=bulk_options["queue_size"],
                raise_on_error=False,
                raise_on_exception=False
            ):
                if success:
                    success_count += 1
                else:
                    errors.append(info)
            
        print(f"\n✅ 同步完成！成功: {success_count} 条。")
        
        if errors:
            print(f"⚠️ 注意！有 {len(errors)} 条数据同步失败！")
            with open(f"{table_name}_errors.log", "w", encoding="utf-8") as f:
                for err in errors:
                    f.write(str(err) + "\n")
            print(f"📄 错误详情已保存到 {table_name}_errors.log")
        elif success_count == total_count:
            print("🎉 完美迁移，0 错误！")

        os_client.indices.refresh(index=index_name)
        print(f"🔄 已刷新索引: {index_name}")
            
    except Exception as e:
        print(f"\n❌ 发生致命错误: {e}")
    finally:
        mysql_conn.close()

if __name__ == "__main__":
    sync_table("telegram", "telegram_index")
    # 如果 telegram 跑通了，再解除下面这行的注释跑 darknet
    sync_table("darknet", "darknet_index")
