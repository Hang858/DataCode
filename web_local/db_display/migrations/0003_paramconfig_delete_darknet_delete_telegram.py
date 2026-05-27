from django.db import migrations, models


def create_paramconfig_if_missing(apps, schema_editor):
    connection = schema_editor.connection
    table_name = "param_config"

    existing_tables = set(connection.introspection.table_names())
    if table_name in existing_tables:
        return

    schema_editor.execute(
        """
        CREATE TABLE param_config (
            id integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
            task_id varchar(255) NULL,
            time_period varchar(255) NULL,
            send_time varchar(255) NULL,
            telegram bool NOT NULL DEFAULT 0,
            darknet bool NOT NULL DEFAULT 0,
            created_at date NOT NULL
        )
        """
    )


class Migration(migrations.Migration):

    dependencies = [
        ("db_display", "0002_statscache_exporttask"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(create_paramconfig_if_missing, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.CreateModel(
                    name="ParamConfig",
                    fields=[
                        ("id", models.AutoField(primary_key=True, serialize=False)),
                        ("task_id", models.CharField(blank=True, max_length=255, null=True)),
                        (
                            "time_period",
                            models.CharField(blank=True, max_length=255, null=True),
                        ),
                        ("send_time", models.CharField(blank=True, max_length=255, null=True)),
                        ("telegram", models.BooleanField(default=False)),
                        ("darknet", models.BooleanField(default=False)),
                        ("created_at", models.DateField(auto_now_add=True)),
                    ],
                    options={
                        "db_table": "param_config",
                        "managed": True,
                    },
                ),
                migrations.DeleteModel(
                    name="Darknet",
                ),
                migrations.DeleteModel(
                    name="Telegram",
                ),
            ],
        ),
    ]
