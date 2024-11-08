# Generated by Django 5.0.6 on 2024-08-14 11:35

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tph_system', '0014_alter_sales_sale_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='sales',
            name='comment',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='sales',
            name='photographer',
            field=models.ForeignKey(default='', on_delete=django.db.models.deletion.PROTECT, related_name='sale_photographer', to='tph_system.staff'),
        ),
    ]
