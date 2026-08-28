from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracking', '0007_transfer_item_id_as_text'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='accident',
            constraint=models.CheckConstraint(
                check=models.Q(accident_excess__gte=0),
                name='accident_excess_nonnegative',
            ),
        ),
    ]
