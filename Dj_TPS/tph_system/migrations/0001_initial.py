# Generated by Django 5.0.6 on 2024-05-10 23:28

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Staff',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('f_name', models.CharField(max_length=30)),
                ('name', models.CharField(max_length=30)),
                ('o_name', models.CharField(blank=True, max_length=30)),
                ('date_empl', models.DateField()),
                ('date_dism', models.DateField(null=True)),
            ],
        ),
    ]
