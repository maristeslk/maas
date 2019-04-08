# -*- coding: utf-8 -*-
# Generated by Django 1.11.11 on 2018-12-05 21:21
from __future__ import unicode_literals

from django.db import (
    migrations,
    models,
)


class Migration(migrations.Migration):

    dependencies = [
        ('maasserver', '0182_remove_duplicate_null_ips'),
    ]

    operations = [
        migrations.AddField(
            model_name='node',
            name='hardware_uuid',
            field=models.CharField(blank=True, default=None, max_length=36, null=True, unique=True),
        ),
    ]