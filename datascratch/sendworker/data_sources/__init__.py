"""Data source interfaces."""

from sendworker.data_sources.mysql_source import MySQLDataSource
from sendworker.data_sources.opensearch_source import OpenSearchDataSource
from sendworker.data_sources.factory import build_data_source

__all__ = ["MySQLDataSource", "OpenSearchDataSource", "build_data_source"]
