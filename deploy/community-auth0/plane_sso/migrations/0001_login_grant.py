import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [migrations.CreateModel(name="LoginGrant", fields=[
        ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
        ("organization", models.CharField(max_length=255)),
        ("expires_at", models.DateTimeField(db_index=True)),
        ("revoked", models.BooleanField(default=False)),
        ("consumed", models.BooleanField(default=False)),
    ])]
