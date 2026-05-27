import hashlib
import logging
import shutil
from datetime import datetime
from pathlib import Path

from .config import COPY_FAILED_FILES, FILE_FINGERPRINT_BYTES, ROW_CHUNK_SIZE, UNPROCESSED_THRESHOLD
from .core import build_records, determine_title, identify_special_fields
from .readers import get_correct_extension, iter_file_row_chunks
from .storage import build_record_store


class OfflineDataPipeline:
    def __init__(self, root_dir, store=None, unprocessed_dir=None, logger=None):
        self.root_dir = Path(root_dir).resolve()
        self.store = store or build_record_store()
        self.unprocessed_dir = Path(unprocessed_dir or "未处理").resolve()
        self.logger = logger or logging.getLogger(__name__)

    def process_tree(self):
        self.logger.info("开始处理目录: %s", self.root_dir)
        self.store.ensure_schema()
        self.logger.info("存储初始化完成，开始扫描文件: %s", self.root_dir)
        scanned = 0
        processed = 0
        failed = 0
        skipped = 0
        unsupported = 0
        for path in self.root_dir.rglob("*"):
            if path.is_dir():
                continue
            scanned += 1
            try:
                result = self.process_file(path)
                if result == "processed":
                    processed += 1
                elif result == "skipped":
                    skipped += 1
                elif result == "unsupported":
                    unsupported += 1
            except Exception as exc:
                failed += 1
                self.logger.exception("处理文件失败: %s, error=%s", path, exc)
                source = self.relative_source(path)
                file_key = self.file_key(path)
                self.store.delete_by_source(source)
                self.mark_failed(file_key, exc)
                if COPY_FAILED_FILES:
                    self.copy_to_unprocessed(path)
        if scanned == 0:
            self.logger.warning("目录下没有扫描到任何文件: %s", self.root_dir)
        result = {
            "scanned": scanned,
            "processed": processed,
            "failed": failed,
            "skipped": skipped,
            "unsupported": unsupported,
        }
        self.logger.info("目录处理统计: %s", result)
        return result

    def process_file(self, path):
        extension = get_correct_extension(path.name)
        if not extension:
            self.logger.info("忽略不支持的文件类型: %s", path)
            return "unsupported"

        source = self.relative_source(path)
        stat = path.stat()
        file_mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        file_key = self.file_key(path, stat=stat)
        if self.should_skip_file(file_key, stat.st_size):
            self.logger.info("跳过已成功处理的相同文件: %s, file_key=%s", path, file_key)
            return "skipped"

        self.store.delete_by_source(source)
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.mark_started(path, source, file_key, started_at, stat=stat, file_mtime=file_mtime)
        total_rows = 0
        unprocessed_rows = 0
        inserted = 0

        insert_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        saw_data = False
        headers = None
        for chunk_idx, data in enumerate(iter_file_row_chunks(path, extension, ROW_CHUNK_SIZE), start=1):
            if not data:
                continue
            saw_data = True
            chunk_total_rows, chunk_unprocessed_rows, chunk_inserted = self.process_rows_chunk(
                data=data,
                path=path,
                source=source,
                insert_time=insert_time,
                chunk_idx=chunk_idx,
                headers=headers,
            )
            if chunk_idx == 1 and self.first_chunk_has_header(data):
                headers = data[0]
            total_rows += chunk_total_rows
            unprocessed_rows += chunk_unprocessed_rows
            inserted += chunk_inserted

        if not saw_data:
            raise ValueError("文件内容为空")

        self.mark_success(file_key, total_rows, unprocessed_rows, inserted)
        self.logger.info("插入记录数=%s, file=%s", inserted, path)
        return "processed"

    def first_chunk_has_header(self, data):
        return determine_title(data, logger=self.logger.info) == 1

    def process_rows_chunk(self, data, path, source, insert_time, chunk_idx, headers=None):
        rows_tags = identify_special_fields(data)
        title = determine_title(data, logger=self.logger.info) if chunk_idx == 1 else 0
        skip_header = title == 1 and chunk_idx == 1
        current_headers = data[0] if skip_header and data else headers
        data_rows = data[1:] if skip_header and len(data) > 1 else data
        tags_rows = rows_tags[1:] if skip_header and len(rows_tags) > 1 else rows_tags
        total_rows = len(data_rows)
        if total_rows == 0:
            raise ValueError("无有效数据行")

        unprocessed_rows = sum(1 for row_tags in tags_rows if sum(1 for tag in row_tags if tag) < 2)
        unprocessed_ratio = unprocessed_rows / total_rows
        self.logger.info(
            "文件块=%s, 行数=%s, 未处理行数=%s, 未处理比例=%.2f%%, file=%s",
            chunk_idx,
            total_rows,
            unprocessed_rows,
            unprocessed_ratio * 100,
            path,
        )
        if unprocessed_ratio >= UNPROCESSED_THRESHOLD:
            raise ValueError(f"未处理行比例达{unprocessed_ratio * 100:.1f}% >= {UNPROCESSED_THRESHOLD * 100}%")

        records = build_records(
            data=data,
            title=title,
            rows_tags=rows_tags,
            leak_channel=path.name,
            source=source,
            insert_time=insert_time,
            headers=current_headers,
            skip_header=skip_header,
        )
        inserted = self.store.insert_records(records)
        return total_rows, unprocessed_rows, inserted

    def should_skip_file(self, file_key, file_size):
        if not hasattr(self.store, "get_file_status"):
            return False
        status = self.store.get_file_status(file_key)
        if not status:
            return False
        return (
            status.get("status") == "success"
            and int(status.get("file_size") or -1) == int(file_size)
        )

    def mark_started(self, path, source, file_key, started_at, stat=None, file_mtime=None):
        if not hasattr(self.store, "mark_started"):
            return
        stat = stat or path.stat()
        file_mtime = file_mtime or datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        self.store.mark_started(
            source=source,
            file_key=file_key,
            file_name=path.name,
            file_size=stat.st_size,
            file_mtime=file_mtime,
            started_at=started_at,
        )

    def mark_success(self, file_key, total_rows, unprocessed_rows, inserted_rows):
        if hasattr(self.store, "mark_success"):
            self.store.mark_success(
                file_key=file_key,
                total_rows=total_rows,
                unprocessed_rows=unprocessed_rows,
                inserted_rows=inserted_rows,
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )

    def mark_failed(self, file_key, error_message):
        if hasattr(self.store, "mark_failed"):
            self.store.mark_failed(
                file_key=file_key,
                error_message=error_message,
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )

    def normalize_datetime(self, value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return str(value)

    def file_key(self, path, stat=None):
        stat = stat or path.stat()
        digest = hashlib.sha256()
        digest.update(str(stat.st_size).encode("utf-8"))
        with open(path, "rb") as file_obj:
            head = file_obj.read(FILE_FINGERPRINT_BYTES)
            digest.update(head)
            if stat.st_size > FILE_FINGERPRINT_BYTES:
                file_obj.seek(max(0, stat.st_size - FILE_FINGERPRINT_BYTES))
                digest.update(file_obj.read(FILE_FINGERPRINT_BYTES))
        return digest.hexdigest()

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
