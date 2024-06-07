# Generated by Django 5.0.6 on 2024-06-07 01:00

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tph_system', '0008_alter_cashwithdrawn_options_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Tech',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50)),
                ('serial_num', models.CharField(blank=True, max_length=30)),
                ('date_buy', models.DateField()),
                ('warranty_date', models.DateField()),
                ('date_change', models.DateTimeField(auto_now=True)),
                ('store', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tph_system.store')),
            ],
            options={
                'verbose_name': 'Фототехника',
                'verbose_name_plural': 'Фототехника',
                'ordering': ['store', 'name'],
            },
        ),
    ]