from django.db import models
from django.contrib.auth.models import User

from dashboard.models import Product

# Create your models here.


class ProductInterest(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='product_interests')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='interests')
    score = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'product')
        indexes = [
            models.Index(fields=['user', 'score', 'updated_at']),
        ]

    def __str__(self):
        return f"{self.user_id} -> {self.product_id} ({self.score})"


class LikedProduct(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="liked_products")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="liked_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "product")
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["product", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} ❤ {self.product_id}"
