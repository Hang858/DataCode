import logging
import shutil
from datetime import datetime
from pathlib import Path

from .config import UNPROCESSED_THRESHOLD
from .core import build_records, determine_title, identify_special_fields
from .readers import get_correct_extension, read_file_rows
from .storage import MySQLRecordStore


class OfflineDataPipeline:
    def __init__(self, root_dir, store=None, unprocessed_dir=None, logger=None):
        self.root_dir = Path(root_dir).resolve()
        self.store = store or MySQLRecordStore()
        self.unprocessed_dir = Path(unprocessed_dir or "未处理").resolve()
        self.logger = logger or logging.getLogger(__name__)

    def process_tree(self):
        self.store.ensure_schema()
        processed = 0
        failed = 0
        for path in self.root_dir.rglob("*"):
            if path.is_dir():
                continue
            try:
                if self.process_file(path):
                    processed += 1
            except Exception as exc:
                failed += 1
                self.logger.exception("处理文件失败: %s, error=%s", path, exc)
                self.copy_to_unprocessed(path)
                source = self.relative_source(path)
                self.store.delete_by_source(source)
        return {"processed": processed, "failed": failed}

    def process_file(self, path):
        extension = get_correct_extension(path.name)
        if not extension:
            self.logger.info("忽略不支持的文件类型: %s", path)
            return False

        data = read_file_rows(path, extension)
        if not data:
            raise ValueError("文件内容为空")

        rows_tags = identify_special_fields(data)
        title = determine_title(data, logger=self.logger.info)
        data_rows = data[1:] if title == 1 and len(data) > 1 else data
        tags_rows = rows_tags[1:] if title == 1 and len(rows_tags) > 1 else rows_tags
        total_rows = len(data_rows)
        if total_rows == 0:
            raise ValueError("无有效数据行")

        unprocessed_rows = sum(1 for row_tags in tags_rows if sum(1 for tag in row_tags if tag) < 2)
        unprocessed_ratio = unprocessed_rows / total_rows
        self.logger.info(
            "文件总行数=%s, 未处理行数=%s, 未处理比例=%.2f%%, file=%s",
            total_rows,
            unprocessed_rows,
            unprocessed_ratio * 100,
            path,
        )
        if unprocessed_ratio >= UNPROCESSED_THRESHOLD:
            raise ValueError(f"未处理行比例达{unprocessed_ratio * 100:.1f}% >= {UNPROCESSED_THRESHOLD * 100}%")

        source = self.relative_source(path)
        insert_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        records = build_records(
            data=data,
            title=title,
            rows_tags=rows_tags,
            leak_channel=path.name,
            source=source,
            insert_time=insert_time,
        )
        inserted = self.store.insert_records(records)
        self.logger.info("插入记录数=%s, file=%s", inserted, path)
        return True

    def relative_source(self, path):
        try:
            return str(path.resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            return str(path.resolve())

    def copy_to_unprocessed(self, path):
        self.unprocessed_dir.mkdir(parents=True, exist_ok=True)
        target = self.unique_target(path)
        shutil.copy2(path, target)
        self.logger.info("已复制到未处理文件夹: %s", target)

    def unique_target(self, source_path):
        candidate = self.unprocessed_dir / source_path.name
        if not candidate.exists():
            return candidate
        stem = source_path.stem
        suffix = source_path.suffix
        counter = 1
        while True:
            candidate = self.unprocessed_dir / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

