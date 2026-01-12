import os
import random
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from dashboard.models import Category, Product


class Command(BaseCommand):
    help = "Seed products for specific categories using local images from media/product (no network)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--per-category",
            type=int,
            default=5,
            help="How many products to add per category.",
        )
        parser.add_argument(
            "--ensure-at-least",
            type=int,
            default=0,
            help="If set, top up each category to at least this many products (instead of always adding).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        per_category = int(options.get("per_category") or 0)
        ensure_at_least = int(options.get("ensure_at_least") or 0)
        if per_category <= 0 and ensure_at_least <= 0:
            self.stdout.write(self.style.ERROR("Nothing to do. Use --per-category > 0 or --ensure-at-least > 0."))
            return

        tree = [
            ("Books & Stationery", ["Educational Books", "Stationery", "Books"]),
            ("Sports & Outdoors", ["Fitness", "Sports Equipment"]),
            ("Beauty & Personal Care", ["Personal Care", "Beauty"]),
        ]

        def get_or_create_category(name, parent):
            category, _ = Category.objects.get_or_create(name=name, parent=parent)
            return category

        def pick_local_image():
            image_dir = os.path.join(settings.BASE_DIR, "media", "product")
            try:
                candidates = [
                    name
                    for name in os.listdir(image_dir)
                    if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                ]
            except FileNotFoundError:
                candidates = []

            if not candidates:
                return None

            filename = random.choice(candidates)
            path = os.path.join(image_dir, filename)
            with open(path, "rb") as handle:
                return ContentFile(handle.read(), name=filename)

        def unique_product_name(category_name):
            # Ensure unique slug, since Product.save() doesn't resolve conflicts.
            token = secrets.token_hex(3)
            return f"{category_name} {token}".title()

        def unique_slug(name):
            base = slugify(name)[:45] or secrets.token_hex(3)
            slug = base
            counter = 1
            while Product.objects.filter(slug=slug).exists():
                slug = f"{base}-{counter}"
                counter += 1
            return slug

        def create_product_for_category(category):
            name = unique_product_name(category.name)
            product = Product(
                category=category,
                name=name,
                slug=unique_slug(name),
                description=f"Popular {category.name} item.",
                price=Decimal(random.randint(199, 9999)) / Decimal(100),
                quantity=random.randint(1, 20),
            )

            image_content = pick_local_image()
            if image_content:
                product.image.save(image_content.name, image_content, save=False)
            else:
                # Avoid crashing if no images exist; ImageField is required.
                raise RuntimeError(
                    "No local images found in media/product. Add at least one image file to seed products."
                )

            product.save()
            return product

        categories = []
        for parent_name, children in tree:
            parent = get_or_create_category(parent_name, None)
            categories.append(parent)
            for child_name in children:
                child = get_or_create_category(child_name, parent)
                categories.append(child)

        created = 0
        for category in categories:
            if ensure_at_least > 0:
                existing = Product.objects.filter(category=category).count()
                to_create = max(0, ensure_at_least - existing)
            else:
                to_create = per_category

            for _ in range(to_create):
                create_product_for_category(category)
                created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded products for {len(categories)} categories. Created {created} products."
            )
        )

