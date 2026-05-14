import hashlib

from django.db import models


class ParamSubmission(models.Model):
    id = models.AutoField(primary_key=True)
    task_id = models.CharField(max_length=255, unique=True)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    telegram = models.BooleanField(default=False)
    darknet = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'param_submissions'
        managed = True  # 允许Django管理此表的创建和修改

class ParamConfig(models.Model):
    id = models.AutoField(primary_key=True)
    task_id = models.CharField(max_length=255, unique=True)
    time_period = models.CharField(max_length=255, blank=True, null=True)
    send_time = models.CharField(max_length=255, blank=True, null=True)
    telegram = models.BooleanField(default=False)
    darknet = models.BooleanField(default=False)
    created_at = models.DateField(auto_now_add=True)

    class Meta:
        db_table = 'param_config'
        managed = True


class ParamTaskFilter(models.Model):
    DATASET_CHOICES = [
        ("telegram", "Telegram"),
        ("darknet", "Darknet"),
    ]

    id = models.AutoField(primary_key=True)
    task_id = models.CharField(max_length=255)
    dataset = models.CharField(max_length=32, choices=DATASET_CHOICES)
    search_field = models.CharField(max_length=255, blank=True, null=True)
    operator = models.CharField(max_length=32, default="auto")
    search_value = models.TextField(blank=True, null=True)
    connector = models.CharField(max_length=8, default="AND")
    enabled = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'param_task_filters'
        managed = True
        indexes = [
            models.Index(fields=["task_id", "dataset", "enabled", "sort_order"]),
        ]


class StatsCache(models.Model):
    cache_key = models.CharField(max_length=64, unique=True)
    dataset = models.CharField(max_length=32)
    distinct_count = models.BigIntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'stats_cache'
        managed = True


class ExportTask(models.Model):
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
    ]

    dataset = models.CharField(max_length=32)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    file_name = models.CharField(max_length=255, blank=True, null=True)
    file_path = models.TextField(blank=True, null=True)
    filters_json = models.JSONField(default=dict)
    row_count = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'export_task'
        managed = True
