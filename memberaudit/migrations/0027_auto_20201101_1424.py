# Generated by Django 3.1.2 on 2020-11-01 14:24

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("memberaudit", "0026_auto_20201031_1955"),
    ]

    operations = [
        migrations.AlterField(
            model_name="characterwalletjournalentry",
            name="ref_type",
            field=models.CharField(max_length=64),
        ),
    ]