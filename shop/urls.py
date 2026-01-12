from django.urls import path
from . import views

urlpatterns = [
    path('shop/', views.shop, name='shop'),
    path('search/', views.product_search, name='product_search'),
    path('api/product-search/', views.api_product_search, name='api_product_search'),
    path('product/<int:product_id>/detail/', views.product_detail, name='product_detail'),
    path('product/<slug:slug>/detail/', views.product_detail_by_slug, name='product_detail_slug'),
    path('category/<slug:slug>/', views.category_products, name='category_products'),
    path('like/<int:product_id>/toggle/', views.toggle_like, name='toggle_like'),

]
