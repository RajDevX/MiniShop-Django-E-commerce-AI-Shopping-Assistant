from django.contrib.auth.models import User
from django.test import TestCase

from dashboard.models import Category, Product
from shop.recommendations import get_recommended_products

# Create your tests here.


class RecommendationDiversityTests(TestCase):
    def test_anonymous_recommendations_are_diverse_across_categories(self):
        cat_a = Category.objects.create(name="Cat A", slug="cat-a")
        cat_b = Category.objects.create(name="Cat B", slug="cat-b")
        for i in range(10):
            Product.objects.create(
                name=f"A{i}",
                slug=f"a-{i}",
                description="a",
                price="10.00",
                quantity=10,
                category=cat_a,
            )
        for i in range(10):
            Product.objects.create(
                name=f"B{i}",
                slug=f"b-{i}",
                description="b",
                price="10.00",
                quantity=10,
                category=cat_b,
            )

        qs = get_recommended_products(None, n=5)
        cats = list(qs.values_list("category_id", flat=True))
        self.assertTrue(len(cats) <= 5)
        self.assertTrue(cats.count(cat_a.id) <= 2)
        self.assertTrue(cats.count(cat_b.id) <= 2)
