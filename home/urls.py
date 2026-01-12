from django.urls import path, include
from . import views
urlpatterns = [
    path('', views.home, name='home'),
    path('chatbot/', views.chatbot, name='chatbot'),
    path('api/assistant/', views.assistant_api, name='assistant_api'),
    path('discover/<int:product_id>/', views.discover_product, name='discover_product'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('login/', views.login, name='login'),
    path('register/', views.register, name='register'),
]
