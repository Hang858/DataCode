from django.db import migrations, models


def add_paramsubmission_flags_if_missing(apps, schema_editor):
    ParamSubmission = apps.get_model("db_display", "ParamSubmission")
    table_name = ParamSubmission._meta.db_table
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        existing_columns = {
            column.name for column in connection.introspection.get_table_description(cursor, table_name)
        }

    for field_name in ("telegram", "darknet"):
        if field_name in existing_columns:
            continue
        field = ParamSubmission._meta.get_field(field_name)
        schema_editor.add_field(ParamSubmission, field)


class Migration(migrations.Migration):

    dependencies = [
        ("db_display", "0003_paramconfig_delete_darknet_delete_telegram"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(add_paramsubmission_flags_if_missing, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="paramsubmission",
                    name="telegram",
                    field=models.BooleanField(default=False),
                ),
                migrations.AddField(
                    model_name="paramsubmission",
                    name="darknet",
                    field=models.BooleanField(default=False),
                ),
            ],
        ),
    ]
