# 离线数据处理重构目录

这个目录用于后续大改，避免直接破坏现有 `offline_data.py`。

## 模块边界

- `core.py`: 核心识别逻辑，包括身份证、手机号、银行卡、姓名识别，以及表头判断和记录构造。
- `readers.py`: 文件读取和解析，当前保留原脚本的整文件读取方式，后续 CSV/TXT 可以在这里改成流式读取。
- `storage.py`: 存储接口，当前实现 MySQL 写入，并补了常用查询字段索引。
- `pipeline.py`: 数据流编排，负责遍历文件、解析、识别、写入、失败文件归档。
- `main.py`: 命令行入口。

## 运行

```bash
python3 -m offline_data_processing.main -f test
```

## 后续 10 亿级改造优先级

1. 将 `readers.py` 的 CSV/TXT 改为迭代器，避免整文件进内存。
2. 将 `pipeline.py` 改成按 chunk 判断和写入，不再对整个文件一次性 `identify_special_fields`。
3. 将 `storage.py` 抽象出 OpenSearch 或分区 MySQL 实现。
4. 增加文件状态表，替代 `old.log` 这类本地文件断点。
5. 按查询需求补充索引、分区或写入 OpenSearch。

