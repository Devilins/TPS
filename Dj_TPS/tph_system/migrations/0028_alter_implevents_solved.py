# Generated by Django 5.0.6 on 2024-11-05 00:22

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tph_system', '0027_alter_salary_options_alter_cashwithdrawn_date_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='implevents',
            name='solved',
            field=models.CharField(choices=[('Да', 'Да'), ('Нет', 'Нет')], max_length=10, null=True, verbose_name='Решено'),
        ),
    ]