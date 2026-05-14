from sendworker.data_sources.mysql_source import MySQLDataSource
from sendworker.data_sources.opensearch_source import OpenSearchDataSource


def build_data_source(name):
    normalized = str(name).strip().lower()
    if normalized == "mysql":
        return MySQLDataSource()
    if normalized in {"opensearch", "os"}:
        return OpenSearchDataSource()
    raise ValueError(f"Unsupported data source: {name}")
