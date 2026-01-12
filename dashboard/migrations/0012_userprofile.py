from django.db import migrations, models
from django.conf import settings


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0011_alter_navbar_number"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("avatar", models.ImageField(blank=True, null=True, upload_to="avatars/")),
                (
                    "user",
                    models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="profile", to=settings.AUTH_USER_MODEL),
                ),
            ],
        ),
    ]

