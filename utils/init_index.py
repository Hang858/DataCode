from opensearchpy import OpenSearch
import urllib3

# 忽略本地自签名证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 连接刚才启动的本地集群
client = OpenSearch(
    hosts=[{'host': '192.168.23.204', 'port': 9200}],
    http_auth=('admin', 'MyStrongPass123!'),
    use_ssl=True,
    verify_certs=False,
    ssl_show_warn=False
)

def create_telegram_index(index_name):
    # 如果索引已经存在，先删掉（确保我们建立的是全新的）
    if client.indices.exists(index=index_name):
        client.indices.delete(index=index_name)
        print(f"清理了旧的 {index_name}")

    # 核心：定义你的“表结构”和“集群规则”
    index_body = {
        "settings": {
            "index": {
                # 【为 WSL2 量身定制】我们有 3 个 Data 节点，设为 3 个分片，刚好一人分担一个！
                "number_of_shards": 30,   
                # 测试阶段不需要副本，节省一半硬盘空间
                "number_of_replicas": 0, 
                # 正常查询保持准实时；批量导入脚本会临时改成 -1，完成后恢复
                "refresh_interval": "30s"
            }
        },
        "mappings": {
            # 禁止 OpenSearch 瞎猜！如果有我们没定义的字段进来了，直接忽略（不建索引，但会存下来）
            "dynamic": "false", 
            "properties": {
                # 1. 那些你绝对要用 input 框去模糊搜索的字段（设为 text）
                "id": { "type": "long" },
                "content_text": { "type": "text", "analyzer": "smartcn" },
                "chat_name": { "type": "text", "analyzer": "smartcn" },
                "org": { "type": "text", "analyzer": "smartcn" },
                "sender_first_name": { "type": "text", "analyzer": "smartcn" },
                "sender_last_name": { "type": "text", "analyzer": "smartcn" },
                "event": { "type": "text", "analyzer": "smartcn" },
                "industry": { "type": "text", "analyzer": "smartcn" },
                "tags": { "type": "text", "analyzer": "smartcn" },
                
                # 2. 那些你只用来做下拉框筛选、或者完全相等的字段（设为 keyword）
                "original_id": { "type": "keyword" },
                "chat_id": { "type": "keyword" },           # <--- 新增：用于群组去重统计和精准过滤
                "message_id": { "type": "keyword" },        # <--- 新增
                "sender_id": { "type": "keyword" },         # <--- 新增
                "sender_username": { "type": "keyword" },
                "child_file": { "type": "keyword" },
                
                # 3. 时间字段（方便未来做时间范围筛选）
                "message_date": {
                    "type": "date",
                    "format": "yyyy-MM-dd HH:mm:ss||yyyy-MM-dd"
                },
                "message_time": {
                    "type": "date",
                    "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time"
                },
                "timestamp": {
                    "type": "date",
                    "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time"
                }
            }
        }
    }

    # 执行创建
    client.indices.create(index=index_name, body=index_body)
    print(f"✅ 成功创建规范化索引: {index_name}")

def create_darknet_index(index_name):
    # 如果索引已经存在，先删掉（确保我们建立的是全新的）
    if client.indices.exists(index=index_name):
        client.indices.delete(index=index_name)
        print(f"清理了旧的 {index_name}")

    # 核心：定义你的“表结构”和“集群规则”
    index_body = {
        "settings": {
            "index": {
                # 【为 WSL2 量身定制】我们有 3 个 Data 节点，设为 3 个分片，刚好一人分担一个！
                "number_of_shards": 30,   
                # 测试阶段不需要副本，节省一半硬盘空间
                "number_of_replicas": 0, 
                # 正常查询保持准实时；批量导入脚本会临时改成 -1，完成后恢复
                "refresh_interval": "30s"
            }
        },
        "mappings": {
            # 禁止 OpenSearch 瞎猜！如果有我们没定义的字段进来了，直接忽略（不建索引，但会存下来）
            "dynamic": "false", 
            "properties": {
                # 1. 那些你绝对要用 input 框去模糊搜索的字段（设为 text）
                "id": { "type": "long" },
                "title": { "type": "text", "analyzer": "standard" },
                "msg_author": { "type": "text", "analyzer": "standard" },
                "msg_title_cn": { "type": "text", "analyzer": "smartcn" },
                "url": { "type": "text", "analyzer": "standard" },
                "msg_description": { "type": "text", "analyzer": "smartcn" },

                "event": { "type": "text", "analyzer": "smartcn" },
                "industry": { "type": "text", "analyzer": "smartcn" },
                "tags": { "type": "text", "analyzer": "smartcn" },
                
                # 2. 那些你只用来做下拉框筛选、或者完全相等的字段（设为 keyword）
                "original_id": { "type": "keyword" },
                "root_domain": { "type": "keyword" },       # <--- 新增：用于暗网去重统计
                "toplv_domain": { "type": "keyword" },      # <--- 新增
                "user_id": { "type": "keyword" },
                "child_file": { "type": "keyword" },
                
                # 3. 时间字段（方便未来做时间范围筛选）
                "msg_release_time": {
                    "type": "date",
                    "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time"
                },
                "timestamp": {
                    "type": "date",
                    "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time"
                }
            }
        }
    }

    # 执行创建
    client.indices.create(index=index_name, body=index_body)
    print(f"✅ 成功创建规范化索引: {index_name}")

if __name__ == "__main__":
    create_telegram_index("telegram_index")
    # 如果你还需要暗网的数据，把下面这行取消注释
    create_darknet_index("darknet_index")
