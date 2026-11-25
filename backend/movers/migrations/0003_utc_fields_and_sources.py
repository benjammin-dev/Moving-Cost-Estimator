from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("movers", "0002_importrun"),
    ]

    operations = [
        migrations.AlterField(
            model_name="mover",
            name="usdot_number",
            field=models.PositiveIntegerField(blank=True, null=True, unique=True, verbose_name="USDOT number"),
        ),
        # Every existing profile came from the FMCSA import. New ones always
        # set their source explicitly, so the field keeps no default.
        migrations.AddField(
            model_name="mover",
            name="source",
            field=models.CharField(
                choices=[("fmcsa", "FMCSA import"), ("utc", "UTC import"), ("staff", "Added by staff")],
                default="fmcsa", help_text="Where the profile came from", max_length=10,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="mover",
            name="utc_company_id",
            field=models.PositiveIntegerField(
                blank=True, null=True, unique=True, verbose_name="UTC company ID",
                help_text="The number in the company's utc.wa.gov/company/... page address",
            ),
        ),
        migrations.AddField(
            model_name="mover",
            name="utc_status",
            field=models.CharField(
                blank=True, max_length=20, verbose_name="UTC status",
                help_text="As the UTC lists it: Active, Pending, Unregulated, Inactive. Blank if not on the UTC list.",
            ),
        ),
        migrations.AddField(
            model_name="mover",
            name="utc_synced_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="UTC synced at"),
        ),
        migrations.AddField(
            model_name="mover",
            name="utc_detail_synced_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="UTC company page read at"),
        ),
        migrations.AddField(
            model_name="importrun",
            name="kind",
            field=models.CharField(choices=[("fmcsa", "FMCSA"), ("utc", "Washington UTC")], default="fmcsa", max_length=10),
        ),
        migrations.AlterField(
            model_name="importrun",
            name="source",
            field=models.CharField(help_text="What was read: the FMCSA dataset, a CSV file, or the UTC lookup", max_length=255),
        ),
    ]
