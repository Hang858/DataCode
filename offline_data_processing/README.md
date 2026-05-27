# 离线数据处理重构目录

这个目录用于后续大改，避免直接破坏现有 `offline_data.py`。

## 模块边界

- `core.py`: 核心识别逻辑，包括身份证、手机号、银行卡、姓名识别，以及表头判断和记录构造。
- `readers.py`: 文件读取和解析，当前保留原脚本的整文件读取方式，后续 CSV/TXT 可以在这里改成流式读取。
- `storage.py`: 存储接口，写入 OpenSearch 主数据索引和文件状态索引。
- `pipeline.py`: 数据流编排，负责遍历文件、解析、识别、写入、失败文件归档。
- `main.py`: 命令行入口。

## 运行

```bash
python3 -m offline_data_processing.main -f test
```

`-f` 后面传要递归处理的目录路径，例如：

```bash
python3 -m offline_data_processing.main -f /data/offline-input
```

默认失败文件不再复制到 `未处理` 目录，只在 OpenSearch `offline_import_file` 索引里记录失败状态和原因。如果确实需要复制失败文件：

```bash
OFFLINE_COPY_FAILED_FILES=true python3 -m offline_data_processing.main -f /data/offline-input
```

支持文件级断点续跑：

- 已成功处理且 `source`、文件大小、文件修改时间都未变化的文件会直接跳过。
- 上次处理中断或失败的文件，再次运行会先按 `source` 删除 OpenSearch 里的旧残留数据，然后重新处理。
- 如果文件内容变了，文件大小或修改时间变化后会自动重新处理。

大文件读取按块处理，默认每 5000 行处理并写入一批，避免 1G+ 的 txt/csv/xlsx 一次性进入内存。可调整：

```bash
OFFLINE_ROW_CHUNK_SIZE=10000 python3 -m offline_data_processing.main -f /data/offline-input
```

其中 txt、csv、xlsx 走流式读取；xls、docx、html、json 仍按文件格式限制使用整文件解析。

日志默认写入 `logs/offline_data_processing`：

- `all.log`: 全部日志。
- `debug.log`: 仅 `DEBUG`。
- `info.log`: 仅 `INFO`。
- `error.log`: 仅 `ERROR`。

可以指定日志级别和日志目录：

```bash
python3 -m offline_data_processing.main -f /data/offline-input --log-level DEBUG --log-dir /data/offline-logs
```

## OpenSearch 初始化

按当前单机配置可以使用本目录下的 Docker Compose：

```bash
cd offline_data_processing
export OPENSEARCH_DATA_ROOT=/data/opensearch-offline
export OPENSEARCH_INITIAL_ADMIN_PASSWORD='MyStrongPass123!'
docker-compose -f docker-compose.opensearch.yml up -d
```

`OPENSEARCH_DATA_ROOT` 要换成 220T 机械盘上的实际目录，避免数据落到系统盘或 Docker 默认目录。
如果你的 Docker 是 Compose v2，也可以把 `docker-compose` 换成 `docker compose`。

创建索引：

```bash
cd ..
python3 -m offline_data_processing.init_opensearch_index
```

如果确认要删除旧索引并重建：

```bash
python3 -m offline_data_processing.init_opensearch_index --delete-existing
```

默认主数据写入 `192.168.23.203:9200` 上的 OpenSearch 索引 `offline_private`，索引配置为 12 主分片、0 副本，文件处理状态写入 OpenSearch 索引 `offline_import_file`。运行：

```bash
python3 -m offline_data_processing.main -f /data/offline-input
```

`offline_import_file` 索引用来记录每个文件的导入状态：

- `source`: 文件路径，唯一。
- `file_name`: 文件名。
- `file_size`: 文件大小。
- `file_mtime`: 文件修改时间。
- `status`: `processing` / `success` / `failed`。
- `total_rows`: 文件有效数据行数。
- `unprocessed_rows`: 识别字段少于 2 个的行数。
- `inserted_rows`: 写入 OpenSearch 的记录数。
- `error_message`: 失败原因。
- `started_at` / `finished_at`: 处理开始和结束时间。

当前 OpenSearch 文档字段：

- `id_card`: 身份证号，`keyword` 精确查。
- `phone`: 手机号，`keyword` 精确查。
- `person_name`: 姓名，`keyword` 精确查。
- `bank_card`: 银行卡号，`keyword` 精确查。
- `raw_data`: 原始行 JSON，`ngram` 分词，用于包含式模糊查。
- `leak_channel`: 文件名。
- `source`: 文件路径。
- `insert_time`: 入库时间。

## 后续 10 亿级改造优先级

1. 将 `readers.py` 的 CSV/TXT 改为迭代器，避免整文件进内存。
2. 将 `pipeline.py` 改成按 chunk 判断和写入，不再对整个文件一次性 `identify_special_fields`。
3. 将 `readers.py` 的大文件读取改为流式解析，减少内存占用。
4. 增加导入任务批次 ID，方便追踪整批文件。
5. 按查询需求补充索引、分区或写入 OpenSearch。
