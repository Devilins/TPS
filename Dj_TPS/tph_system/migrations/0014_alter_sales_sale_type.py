# Generated by Django 5.0.6 on 2024-08-14 11:23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tph_system', '0013_refsandtips'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sales',
            name='sale_type',
            field=models.CharField(choices=[('Email (фото)', 'Email (фото)'), ('Email (все)', 'Email (все)'), ('Вин. магн.', 'Вин. магн.'), ('Ср. магн.', 'Ср. магн.'), ('Бол. магн.', 'Бол. магн.'), ('Печать 10x15', 'Печать 10x15'), ('Печать 15x20', 'Печать 15x20'), ('Печать A4', 'Печать A4')], default='', max_length=40),
        ),
    ]