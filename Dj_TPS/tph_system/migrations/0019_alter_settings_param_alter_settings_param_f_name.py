# Generated by Django 5.0.6 on 2024-09-12 13:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tph_system', '0018_settings_sales_date_upd_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='settings',
            name='param',
            field=models.CharField(max_length=50),
        ),
        migrations.AlterField(
            model_name='settings',
            name='param_f_name',
            field=models.TextField(),
        ),
    ]
