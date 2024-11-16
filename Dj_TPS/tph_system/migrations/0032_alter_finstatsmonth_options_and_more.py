# Generated by Django 5.0.6 on 2024-11-14 12:07

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tph_system', '0031_finstatsmonth_finstatsstaff_delete_finstats'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='finstatsmonth',
            options={'ordering': ['date'], 'verbose_name': 'Финансы - компания', 'verbose_name_plural': 'Финансы - компания'},
        ),
        migrations.AlterModelOptions(
            name='finstatsstaff',
            options={'ordering': ['date', 'staff'], 'verbose_name': 'Финансы - сотрудники', 'verbose_name_plural': 'Финансы - сотрудники'},
        ),
        migrations.AlterField(
            model_name='finstatsmonth',
            name='expenses',
            field=models.IntegerField(default=0, verbose_name='Расходы'),
        ),
    ]
