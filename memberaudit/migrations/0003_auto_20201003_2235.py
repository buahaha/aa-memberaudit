# Generated by Django 3.1.1 on 2020-10-03 22:35

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("eveuniverse", "0002_load_eveunit"),
        ("memberaudit", "0002_location"),
    ]

    operations = [
        migrations.AlterField(
            model_name="location",
            name="eve_solar_system",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_DEFAULT,
                to="eveuniverse.evesolarsystem",
            ),
        ),
        migrations.AlterField(
            model_name="location",
            name="eve_type",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_DEFAULT,
                to="eveuniverse.evetype",
            ),
        ),
    ]
