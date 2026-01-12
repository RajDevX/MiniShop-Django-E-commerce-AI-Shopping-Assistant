"""
URL configuration for minishop project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from django.http import HttpResponse
from shop import views as shop_views


def favicon(request):
    return HttpResponse(status=204)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('favicon.ico', favicon),
    # Backward-compatible redirects for template links/bookmarks
    path('index.html', RedirectView.as_view(pattern_name='home', permanent=False)),
    path('cart.html', RedirectView.as_view(pattern_name='cart', permanent=False)),
    path('checkout.html', RedirectView.as_view(pattern_name='checkout', permanent=False)),
    path('product/<slug:slug>/', shop_views.product_public, name='product_public'),
    path('', include('home.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('shop/', include('shop.urls')),
    path('cart/', include('cart.urls')),
    path('blog/', include('blog.urls')),
    path('payment/', include('payment.urls')),
]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
