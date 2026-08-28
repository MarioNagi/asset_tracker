from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracking', '0006_maintenance_invoice_unique'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transfer',
            name='item_id',
            field=models.CharField(
                help_text='Enter the tool internal number or the car numeric ID.',
                max_length=100,
            ),
        ),
    ]
