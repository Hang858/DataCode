from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("db_display", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="StatsCache",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cache_key", models.CharField(max_length=64, unique=True)),
                ("dataset", models.CharField(max_length=32)),
                ("distinct_count", models.BigIntegerField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "stats_cache",
                "managed": True,
            },
        ),
        migrations.CreateModel(
            name="ExportTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("dataset", models.CharField(max_length=32)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("running", "Running"), ("success", "Success"), ("failed", "Failed")], default="pending", max_length=16)),
                ("file_name", models.CharField(blank=True, max_length=255, null=True)),
                ("file_path", models.TextField(blank=True, null=True)),
                ("filters_json", models.JSONField(default=dict)),
                ("row_count", models.IntegerField(default=0)),
                ("error_message", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "export_task",
                "managed": True,
            },
        ),
    ]
