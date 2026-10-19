from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("board", "0004_post_source_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="text_hash",
            field=models.CharField(
                blank=True, db_index=True, editable=False, max_length=64, null=True
            ),
        ),
    ]
