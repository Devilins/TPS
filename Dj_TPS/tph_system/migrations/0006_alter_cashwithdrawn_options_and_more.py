# Generated by Django 5.0.6 on 2024-05-17 22:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tph_system', '0005_delete_consumables'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='cashwithdrawn',
            options={'verbose_name': 'Выдача зарплаты наличкой', 'verbose_name_plural': 'Выдача зарплаты наличкой'},
        ),
        migrations.AlterModelOptions(
            name='consumablessales',
            options={'verbose_name': 'Потраченные расходники за продажу', 'verbose_name_plural': 'Потраченные расходники за продажу'},
        ),
        migrations.AlterModelOptions(
            name='consumablesstore',
            options={'verbose_name': 'Расходники на точке', 'verbose_name_plural': 'Расходники на точке'},
        ),
        migrations.AlterModelOptions(
            name='salary',
            options={'verbose_name': 'Зарплаты сотрудников', 'verbose_name_plural': 'Зарплаты сотрудников'},
        ),
        migrations.AlterModelOptions(
            name='sales',
            options={'verbose_name': 'Продажи', 'verbose_name_plural': 'Продажи'},
        ),
        migrations.AlterModelOptions(
            name='schedule',
            options={'verbose_name': 'График сотрудников', 'verbose_name_plural': 'График сотрудников'},
        ),
        migrations.AlterModelOptions(
            name='staff',
            options={'verbose_name': 'Сотрудники', 'verbose_name_plural': 'Сотрудники'},
        ),
        migrations.AlterModelOptions(
            name='store',
            options={'verbose_name': 'Точки', 'verbose_name_plural': 'Точки'},
        ),
        migrations.AlterField(
            model_name='sales',
            name='date',
            field=models.DateTimeField(auto_now_add=True),
        ),
    ]
