from django.core.management.base import BaseCommand
from django.db import transaction

from dashboard.models import Category
from django.conf import settings
from django.core.files.base import ContentFile

import os
import random


class Command(BaseCommand):
    help = "Seed a default category tree (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-products",
            type=int,
            default=0,
            help="Also create N sample products (requires factory_boy/faker).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        tree = [
            ("Books & Stationery", ["Educational Books", "Stationery", "Books"]),
            ("Sports & Outdoors", ["Fitness", "Sports Equipment"]),
            ("Beauty & Personal Care", ["Personal Care", "Beauty"]),
        ]

        def pick_local_image():
            image_dir = os.path.join(settings.BASE_DIR, "media", "product")
            try:
                candidates = [
                    name
                    for name in os.listdir(image_dir)
                    if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                ]
            except FileNotFoundError:
                return None
            if not candidates:
                return None
            filename = random.choice(candidates)
            path = os.path.join(image_dir, filename)
            with open(path, "rb") as handle:
                return ContentFile(handle.read(), name=filename)

        created_main = 0
        created_sub = 0

        for parent_name, children in tree:
            parent, parent_created = Category.objects.get_or_create(
                name=parent_name, parent=None
            )
            if parent_created:
                created_main += 1
            if hasattr(parent, "image") and not parent.image:
                content = pick_local_image()
                if content:
                    parent.image.save(content.name, content, save=True)

            for child_name in children:
                child, child_created = Category.objects.get_or_create(
                    name=child_name, parent=parent
                )
                if child_created:
                    created_sub += 1
                if hasattr(child, "image") and not child.image:
                    content = pick_local_image()
                    if content:
                        child.image.save(content.name, content, save=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Categories seeded. Created main={created_main}, sub={created_sub}."
            )
        )

        product_count = int(options.get("with_products") or 0)
        if product_count <= 0:
            return

        try:
            from dashboard.factories import ProductFactory
        except Exception as exc:  # pragma: no cover
            self.stdout.write(
                self.style.ERROR(
                    "Could not import ProductFactory. Install factory_boy/faker or run without --with-products.\n"
                    f"Error: {exc}"
                )
            )
            return

        ProductFactory.create_batch(product_count)
        self.stdout.write(
            self.style.SUCCESS(f"Created {product_count} sample products successfully!")
        )
