import mysql.connector

from .config import BATCH_SIZE, DB_CONFIG


class MySQLRecordStore:
    def __init__(self, db_config=None, batch_size=BATCH_SIZE):
        self.db_config = db_config or DB_CONFIG
        self.batch_size = batch_size

    def connect(self):
        return mysql.connector.connect(**self.db_config)

    def ensure_schema(self):
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS private (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    身份证号 VARCHAR(18) NULL,
                    手机号 VARCHAR(11) NULL,
                    姓名 VARCHAR(255) NULL,
                    银行卡号 VARCHAR(255) NULL,
                    原始数据 JSON NULL,
                    泄露渠道 VARCHAR(255) NULL,
                    来源 VARCHAR(255) NULL,
                    入库时间 DATETIME NULL,
                    INDEX idx_source (来源),
                    INDEX idx_insert_time (入库时间),
                    INDEX idx_id_card (身份证号),
                    INDEX idx_phone (手机号),
                    INDEX idx_name (姓名)
                )
                """
            )
            self._ensure_column(cursor, "泄露渠道", "VARCHAR(255) NULL")
            self._ensure_column(cursor, "来源", "VARCHAR(255) NULL")
            self._ensure_column(cursor, "入库时间", "DATETIME NULL")
            self._ensure_index(cursor, "idx_source", "来源")
            self._ensure_index(cursor, "idx_insert_time", "入库时间")
            self._ensure_index(cursor, "idx_id_card", "身份证号")
            self._ensure_index(cursor, "idx_phone", "手机号")
            self._ensure_index(cursor, "idx_name", "姓名")
            connection.commit()

    def _ensure_column(self, cursor, column_name, column_def):
        cursor.execute("SHOW COLUMNS FROM private LIKE %s", (column_name,))
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE private ADD COLUMN {column_name} {column_def}")

    def _ensure_index(self, cursor, index_name, column_name):
        cursor.execute("SHOW INDEX FROM private WHERE Key_name = %s", (index_name,))
        if not cursor.fetchone():
            cursor.execute(f"CREATE INDEX {index_name} ON private ({column_name})")

    def insert_records(self, records):
        insert_query = """
            INSERT INTO private (
                身份证号, 手机号, 姓名, 银行卡号, 原始数据,
                泄露渠道, 来源, 入库时间
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        total = 0
        batch = []
        with self.connect() as connection:
            cursor = connection.cursor()
            for record in records:
                batch.append(
                    (
                        record.id_card,
                        record.phone,
                        record.person_name,
                        record.bank_card,
                        record.raw_data,
                        record.leak_channel,
                        record.source,
                        record.insert_time,
                    )
                )
                if len(batch) >= self.batch_size:
                    cursor.executemany(insert_query, batch)
                    connection.commit()
                    total += len(batch)
                    batch.clear()
            if batch:
                cursor.executemany(insert_query, batch)
                connection.commit()
                total += len(batch)
        return total

    def delete_by_source(self, source):
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM private WHERE 来源 = %s", (source,))
            connection.commit()
            return cursor.rowcount

