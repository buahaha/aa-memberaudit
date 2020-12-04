# Generated by Django 3.1.3 on 2020-12-03 22:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("memberaudit", "0006_add_permission"),
    ]

    operations = [
        migrations.AddField(
            model_name="character",
            name="mailing_lists",
            field=models.ManyToManyField(
                related_name="characters", to="memberaudit.MailEntity"
            ),
        ),
    ]