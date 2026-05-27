from django.db import migrations, models


def deduplicate_param_tables(apps, schema_editor):
    ParamSubmission = apps.get_model("db_display", "ParamSubmission")
    ParamConfig = apps.get_model("db_display", "ParamConfig")

    duplicate_submission_task_ids = (
        ParamSubmission.objects.values_list("task_id", flat=True)
        .order_by()
        .distinct()
    )
    for task_id in duplicate_submission_task_ids:
        if not task_id:
            continue
        rows = list(ParamSubmission.objects.filter(task_id=task_id).order_by("-created_at", "-id"))
        for row in rows[1:]:
            row.delete()

    duplicate_config_task_ids = (
        ParamConfig.objects.values_list("task_id", flat=True)
        .order_by()
        .distinct()
    )
    for task_id in duplicate_config_task_ids:
        if not task_id:
            continue
        rows = list(ParamConfig.objects.filter(task_id=task_id).order_by("-created_at", "-id"))
        for row in rows[1:]:
            row.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("db_display", "0004_paramsubmission_telegram_paramsubmission_darknet"),
    ]

    operations = [
        migrations.RunPython(deduplicate_param_tables, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="paramsubmission",
            name="task_id",
            field=models.CharField(max_length=255, unique=True),
        ),
        migrations.AlterField(
            model_name="paramconfig",
            name="task_id",
            field=models.CharField(max_length=255, unique=True),
        ),
    ]
