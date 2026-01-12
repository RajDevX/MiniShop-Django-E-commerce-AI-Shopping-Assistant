from django.contrib import admin

from shop.models import LikedProduct, ProductInterest


@admin.register(ProductInterest)
class ProductInterestAdmin(admin.ModelAdmin):
    list_display = ("user", "product", "score", "updated_at")
    list_select_related = ("user", "product")
    search_fields = ("user__username", "product__name")
    ordering = ("-updated_at",)


@admin.register(LikedProduct)
class LikedProductAdmin(admin.ModelAdmin):
    list_display = ("user", "product", "created_at")
    list_select_related = ("user", "product")
    search_fields = ("user__username", "product__name")
    ordering = ("-created_at",)
