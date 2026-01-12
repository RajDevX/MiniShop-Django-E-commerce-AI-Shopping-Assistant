from django.urls import path
from . import views

urlpatterns = [
    path('checkout/', views.checkout, name='checkout'),
    path('success/', views.success, name='success'),
    path('cancel/', views.shop_cancel, name='cancel'),
    path('order-success/', views.order_success, name='order_success'),
    path('my-orders/', views.my_orders, name='my_orders'),
    path('orders/<uuid:pk>/', views.order_details, name='order_details'),
    path('orders/<uuid:pk>/cancel/', views.order_cancel, name='order_cancel'),
    path('orders/<uuid:pk>/refund/', views.order_refund_request, name='order_refund_request'),
]
