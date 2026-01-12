from django.shortcuts import get_object_or_404, redirect, render
from django.conf import settings
from django.db import connection, reset_queries
import logging
import os
import time
import uuid
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from decimal import Decimal, InvalidOperation
from dashboard.models import ( Category, Product)
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.core.paginator import Paginator
from shop.services.shop_services import ShopServices
from shop.recommendations import get_recommended_products, record_product_interest
from shop.services.like_services import liked_product_ids_for_user
from shop.models import LikedProduct
# Create your views here.

_LOGGER = logging.getLogger(__name__)


def _obs_enabled() -> bool:
    return bool(getattr(settings, "DEBUG", False) or os.getenv("RECS_OBS", "").strip() == "1")


def _get_request_id(request) -> str:
    return request.META.get("HTTP_X_REQUEST_ID") or uuid.uuid4().hex

def _parse_decimal_param(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def shop(request):
    highlight_id = request.GET.get('highlight')
    highlight_product_id = int(highlight_id) if (highlight_id and highlight_id.isdigit()) else None

    product = Product.objects.all().select_related('category').order_by('-id')
    min_price = _parse_decimal_param(request.GET.get("min_price"))
    max_price = _parse_decimal_param(request.GET.get("max_price"))
    if min_price is not None:
        product = product.filter(price__gte=min_price)
    if max_price is not None:
        product = product.filter(price__lte=max_price)

    if highlight_product_id is not None:
        product = product.annotate(
            _highlight=Case(
                When(id=highlight_product_id, then=0),
                default=1,
                output_field=IntegerField(),
            )
        ).order_by('_highlight', '-id')
    paginator = Paginator(product, 10)
       
    # Current page number get karega
    page_number = request.GET.get('page')
    products = paginator.get_page(page_number)
    liked_product_ids = liked_product_ids_for_user(request.user, [p.id for p in products])
    qs = request.GET.copy()
    qs.pop("page", None)
    querystring = qs.urlencode()
    category = Category.objects.filter(parent__isnull=True).prefetch_related('subcategories').order_by('-id')
    category_data = []

    for cat in category:
        cat_data = {
            'id': cat.id,
            'name': cat.name,
            'slug': cat.slug,
            'parent': cat.parent.id if cat.parent else None,
            'sub_count': cat.subcategories.count(),
            'sub_categories': []
        }

        for sub_cat in cat.subcategories.all().order_by('-id'):
            cat_data['sub_categories'].append({
                'id': sub_cat.id,
                'name': sub_cat.name,
                'slug': sub_cat.slug,
                'parent': sub_cat.parent.id if sub_cat.parent else None
            })

        category_data.append(cat_data)
    context={
        'category_data':category_data,
        'products':products,
        'highlight_product_id': highlight_product_id,
        'querystring': querystring,
        'liked_product_ids': liked_product_ids,
    }
    return render(request, 'shop/shop.html', context)

def product_detail_by_slug(request, slug):
    product = get_object_or_404(Product.objects.select_related("category"), slug=slug)
    return redirect("product_detail", product_id=product.id)

def product_public(request, slug):
    """
    Public product detail URL: /product/<slug>/
    Keeps logic consistent with `product_detail`.
    """
    product = get_object_or_404(Product.objects.select_related("category"), slug=slug)
    record_product_interest(request.user, product, weight=1)
    if _obs_enabled():
        request_id = _get_request_id(request)
        reset_queries()
        start = time.perf_counter()
        recommended_products = (
            get_recommended_products(request.user, n=5)
            .exclude(id=product.id)
            .select_related("category")
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        _LOGGER.info(
            "recs_obs request_id=%s view=product_public elapsed_ms=%.2f db_queries=%s",
            request_id,
            elapsed_ms,
            len(connection.queries),
        )
    else:
        recommended_products = (
            get_recommended_products(request.user, n=5)
            .exclude(id=product.id)
            .select_related("category")
        )
    context = {
        "product": product,
        "recommended_products": recommended_products,
        "liked_product_ids": liked_product_ids_for_user(
            request.user, [product.id, *list(recommended_products.values_list("id", flat=True))]
        ),
    }
    return render(request, "shop/product_detail.html", context)


def product_detail(request, product_id):
    product = get_object_or_404(Product.objects.select_related("category"), id=product_id)
    record_product_interest(request.user, product, weight=1)
    if _obs_enabled():
        request_id = _get_request_id(request)
        reset_queries()
        start = time.perf_counter()
        recommended_products = (
            get_recommended_products(request.user, n=5)
            .exclude(id=product.id)
            .select_related("category")
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        _LOGGER.info(
            "recs_obs request_id=%s view=product_detail elapsed_ms=%.2f db_queries=%s",
            request_id,
            elapsed_ms,
            len(connection.queries),
        )
    else:
        recommended_products = (
            get_recommended_products(request.user, n=5)
            .exclude(id=product.id)
            .select_related("category")
        )
    context = {
        'product': product,
        'recommended_products': recommended_products,
        "liked_product_ids": liked_product_ids_for_user(
            request.user, [product.id, *list(recommended_products.values_list("id", flat=True))]
        ),
    }
    return render(request, 'shop/product_detail.html', context)

def category_products(request, slug):
    shop_service = ShopServices()
    success, message, products = shop_service.get_category_products(request, slug)
    if not success:
        return render(request, 'shop/shop.html', message)
    qs = request.GET.copy()
    qs.pop("page", None)
    querystring = qs.urlencode()
    category = Category.objects.filter(parent__isnull=True).prefetch_related('subcategories').order_by('-id')
    category_data = []

    for cat in category:
        cat_data = {
            'id': cat.id,
            'name': cat.name,
            'slug': cat.slug,
            'parent': cat.parent.id if cat.parent else None,
            'sub_count': cat.subcategories.count(),
            'sub_categories': []
        }

        for sub_cat in cat.subcategories.all().order_by('-id'):
            cat_data['sub_categories'].append({
                'id': sub_cat.id,
                'name': sub_cat.name,
                'slug': sub_cat.slug,
                'parent': sub_cat.parent.id if sub_cat.parent else None
            })

        category_data.append(cat_data)
    context={
        'products':products,
        'category_data':category_data,
        'querystring': querystring,
        'liked_product_ids': liked_product_ids_for_user(request.user, [p.id for p in products] if products else []),
    }
    return render(request, 'shop/shop.html', context)


def product_search(request):
    query = (request.GET.get("q") or "").strip()
    products_qs = Product.objects.select_related("category")

    if query:
        products_qs = products_qs.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(category__name__icontains=query)
        ).annotate(
            relevance=Case(
                When(name__icontains=query, then=Value(0)),
                When(description__icontains=query, then=Value(1)),
                When(category__name__icontains=query, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        ).order_by("relevance", "-updated_at")
    else:
        products_qs = products_qs.none()

    paginator = Paginator(products_qs, 10)
    page_number = request.GET.get("page")
    products = paginator.get_page(page_number)

    context = {
        "query": query,
        "products": products,
        "liked_product_ids": liked_product_ids_for_user(request.user, [p.id for p in products] if products else []),
    }
    return render(request, "shop/search_results.html", context)


def api_product_search(request):
    """
    JSON API for product suggestions.

    Query params:
      - q: search string
      - max_price: optional numeric filter (inclusive)

    Returns: { "results": [ {id, name, slug, price, image_url, product_url, add_to_cart_url} ] }
    """
    query = (request.GET.get("q") or "").strip()[:200]
    max_price_raw = (request.GET.get("max_price") or "").strip()

    if not query:
        return JsonResponse({"results": []})

    products_qs = (
        Product.objects.select_related("category")
        .filter(quantity__gt=0)
        .filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(category__name__icontains=query)
        )
        .annotate(
            relevance=Case(
                When(name__icontains=query, then=Value(0)),
                When(description__icontains=query, then=Value(1)),
                When(category__name__icontains=query, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        )
        .order_by("relevance", "-updated_at")
    )

    if max_price_raw:
        try:
            max_price = Decimal(max_price_raw)
        except (InvalidOperation, ValueError):
            max_price = None
        if max_price is not None:
            products_qs = products_qs.filter(price__lte=max_price)

    products = list(products_qs[:5])

    results = []
    for product in products:
        image_url = product.image.url if getattr(product, "image", None) else ""
        if image_url:
            image_url = request.build_absolute_uri(image_url)

        product_url = request.build_absolute_uri(
            reverse("product_public", kwargs={"slug": product.slug})
        )
        add_to_cart_url = request.build_absolute_uri(
            reverse("cart_add", kwargs={"product_id": product.id})
        )

        results.append(
            {
                "id": product.id,
                "name": product.name,
                "slug": product.slug,
                "price": str(product.price),
                "image_url": image_url,
                "product_url": product_url,
                "add_to_cart_url": add_to_cart_url,
            }
        )

    return JsonResponse({"results": results})


@login_required(login_url="login")
@require_POST
def toggle_like(request, product_id: int):
    product = get_object_or_404(Product, id=product_id)
    liked, created = LikedProduct.objects.get_or_create(user=request.user, product=product)
    if created:
        # Strong positive signal for recommendations.
        record_product_interest(request.user, product, weight=3)
        return JsonResponse({"liked": True})
    liked.delete()
    return JsonResponse({"liked": False})
    
    
