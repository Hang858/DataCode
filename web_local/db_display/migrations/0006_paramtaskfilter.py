from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("db_display", "0005_deduplicate_param_tables_and_unique_task_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="ParamTaskFilter",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("task_id", models.CharField(max_length=255)),
                ("dataset", models.CharField(choices=[("telegram", "Telegram"), ("darknet", "Darknet")], max_length=32)),
                ("search_field", models.CharField(blank=True, max_length=255, null=True)),
                ("operator", models.CharField(default="auto", max_length=32)),
                ("search_value", models.TextField(blank=True, null=True)),
                ("connector", models.CharField(default="AND", max_length=8)),
                ("enabled", models.BooleanField(default=True)),
                ("sort_order", models.IntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "param_task_filters",
                "managed": True,
            },
        ),
        migrations.AddIndex(
            model_name="paramtaskfilter",
            index=models.Index(fields=["task_id", "dataset", "enabled", "sort_order"], name="db_display_task_id_5d30f7_idx"),
        ),
    ]
