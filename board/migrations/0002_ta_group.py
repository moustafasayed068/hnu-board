from django.contrib.auth.management import create_permissions
from django.db import migrations

GROUP_NAME = "Teaching assistants"

# TAs write posts and may only look at the academic structure.
TA_PERMISSIONS = [
    "add_post",
    "change_post",
    "delete_post",
    "view_post",
    "view_academicyear",
    "view_program",
    "view_course",
]


def create_ta_group(apps, schema_editor):
    # Permissions are normally created after all migrations finish (post_migrate),
    # so on a fresh database they do not exist yet. Create them now.
    app_config = apps.get_app_config("board")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    group, _ = Group.objects.get_or_create(name=GROUP_NAME)
    group.permissions.set(
        Permission.objects.filter(content_type__app_label="board", codename__in=TA_PERMISSIONS)
    )


def delete_ta_group(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name=GROUP_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("board", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(create_ta_group, delete_ta_group),
    ]
