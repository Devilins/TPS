# Generated by Django 5.0.6 on 2024-11-24 09:47

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tph_system', '0032_alter_finstatsmonth_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashwithdrawn',
            name='comment',
            field=models.TextField(blank=True, null=True, verbose_name='Комментарий'),
        ),
    ]
