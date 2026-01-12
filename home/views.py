from django.shortcuts import get_object_or_404, redirect, render
from django.conf import settings
from django.db import connection, reset_queries
import logging
import os
import time
import uuid
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .forms import (SignUpForm, loginForm)
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction
from django.db.models import Count
from django.urls import reverse
from django.core.cache import cache
from django.db.models import Case, IntegerField, When
from django.middleware.csrf import get_token
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from dashboard.models import Product
from dashboard.models import Category
from cart.models import CartItem
from payment.models import OrderItem
from shop.models import LikedProduct, ProductInterest
from shop.recommendations import get_recommended_products, record_product_interest
from shop.services.like_services import liked_product_ids_for_user
# Create your views here.

from .assistant_bridge import coerce_entities, search_products, validate_intent

_LOGGER = logging.getLogger(__name__)


def _obs_enabled() -> bool:
    return bool(getattr(settings, "DEBUG", False) or os.getenv("RECS_OBS", "").strip() == "1")


def _get_request_id(request) -> str:
    return request.META.get("HTTP_X_REQUEST_ID") or uuid.uuid4().hex


def home(request):
    hero_products = list(Product.objects.order_by('-id')[:2])
    if _obs_enabled():
        request_id = _get_request_id(request)
        reset_queries()
        start = time.perf_counter()
        recommended_products = get_recommended_products(request.user, n=5).select_related("category")
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        _LOGGER.info(
            "recs_obs request_id=%s view=home elapsed_ms=%.2f db_queries=%s",
            request_id,
            elapsed_ms,
            len(connection.queries),
        )
    else:
        recommended_products = get_recommended_products(request.user, n=5).select_related("category")
    if request.user.is_authenticated:
        has_cart = CartItem.objects.filter(user=request.user).exists()
        has_watchlist = LikedProduct.objects.filter(user=request.user).exists()
        has_interest = ProductInterest.objects.filter(user=request.user).exists()

        recommended_section_title = "Recommended for you"
        if has_cart and has_watchlist:
            recommended_section_subtitle = "Based on items in your cart and your watchlist"
        elif has_cart:
            recommended_section_subtitle = "Based on items in your cart"
        elif has_watchlist:
            recommended_section_subtitle = "Based on items in your watchlist"
        elif has_interest:
            recommended_section_subtitle = "Based on what you viewed"
        else:
            recommended_section_subtitle = "Popular picks based on what shoppers are viewing and buying"
    else:
        recommended_section_title = "Trending now"
        recommended_section_subtitle = "Popular picks based on what shoppers are viewing and buying"

    recommended_ids = list(recommended_products.values_list("id", flat=True))
    cache_key = f"home:sections:{request.user.id if request.user.is_authenticated else 'anon'}:{','.join(map(str, recommended_ids))}"
    cached = cache.get(cache_key)
    if cached:
        category_sections = []
        liked_source_ids: list[int] = list(recommended_ids)
        for section in cached:
            product_ids = section["product_ids"]
            if product_ids:
                order_by_case = Case(
                    *[When(id=product_id, then=idx) for idx, product_id in enumerate(product_ids)],
                    output_field=IntegerField(),
                )
                products = (
                    Product.objects.filter(id__in=product_ids)
                    .select_related("category")
                    .order_by(order_by_case)
                )
            else:
                products = Product.objects.none()
            seed_product = (
                Product.objects.select_related("category")
                .filter(id=section.get("seed_product_id"))
                .first()
            )
            if seed_product:
                liked_source_ids.append(seed_product.id)
            liked_source_ids.extend(product_ids or [])
            category_sections.append(
                {
                    "title": section["title"],
                    "category": Category.objects.filter(id=section["category_id"]).first(),
                    "seed_product": seed_product,
                    "subtitle": section.get("subtitle"),
                    "products": products,
                }
            )
        liked_product_ids = liked_product_ids_for_user(request.user, liked_source_ids)
        context = {
            "hero_products": hero_products,
            "recommended_products": recommended_products,
            "recommended_section_title": recommended_section_title,
            "recommended_section_subtitle": recommended_section_subtitle,
            "category_sections": category_sections,
            "liked_product_ids": liked_product_ids,
        }
        return render(request, 'home/index.html', context)

    category_sections = []

    def _similar_products(seed: Product, *, exclude_ids: set[int], limit: int = 4) -> list[Product]:
        """
        Returns products similar to `seed` using category-recency fallback.
        """
        if not seed or not seed.category_id:
            return []

        products: list[Product] = []

        if len(products) < limit:
            products.extend(
                list(
                    Product.objects.filter(category=seed.category, quantity__gt=0)
                    .exclude(id__in=exclude_ids | {p.id for p in products})
                    .select_related("category")
                    .order_by("-updated_at")[: (limit - len(products))]
                )
            )
        return products

    if request.user.is_authenticated:
        seed_sources = []

        cart_product_ids = list(
            CartItem.objects.filter(user=request.user)
            .order_by("-added_at")
            .values_list("product_id", flat=True)
            .distinct()[:20]
        )
        if cart_product_ids:
            seed_sources.append(("From your cart", cart_product_ids))

        watchlist_product_ids = list(
            LikedProduct.objects.filter(user=request.user)
            .order_by("-created_at")
            .values_list("product_id", flat=True)[:20]
        )
        interest_product_ids = list(
            ProductInterest.objects.filter(user=request.user)
            .order_by("-score", "-updated_at")
            .values_list("product_id", flat=True)[:30]
        )
        watchlist_and_chat_ids: list[int] = []
        seen_watch_chat: set[int] = set()
        for pid in [*watchlist_product_ids, *interest_product_ids]:
            if int(pid) in seen_watch_chat:
                continue
            watchlist_and_chat_ids.append(int(pid))
            seen_watch_chat.add(int(pid))
            if len(watchlist_and_chat_ids) >= 30:
                break
        if watchlist_and_chat_ids:
            seed_sources.append(("From your watchlist & activity", watchlist_and_chat_ids))

        # Fallback: if none of the above, base sections on recommendations.
        if not seed_sources:
            seed_sources.append(("Recommended", recommended_ids))
    else:
        shifted = recommended_ids[1:] + recommended_ids[:1] if recommended_ids else []
        seed_sources = [("Trending", recommended_ids), ("Trending", shifted)]

    seed_products: list[tuple[str, Product]] = []
    seen_seed_ids: set[int] = set()
    for label, product_ids in seed_sources:
        for product_id in product_ids:
            if product_id in seen_seed_ids:
                continue
            product = Product.objects.select_related("category").filter(id=product_id).first()
            if not product:
                continue
            if not product.category_id:
                continue
            seed_products.append((label, product))
            seen_seed_ids.add(product_id)
            if len(seed_products) >= 2:
                break
        if len(seed_products) >= 2:
            break

    # If we still couldn't pick 2 seeds with categories, fill from most-popular categories.
    if len(seed_products) < 2:
        filler_categories = list(
            Category.objects.annotate(product_count=Count("products"))
            .filter(product_count__gt=0)
            .order_by("-product_count", "-updated_at")
        )
        for category in filler_categories:
            product = (
                Product.objects.filter(category=category)
                .exclude(id__in=recommended_ids)
                .order_by("-updated_at")
                .first()
            )
            if not product:
                continue
            seed_products.append(("Popular", product))
            if len(seed_products) >= 2:
                break

    subtitle_by_label = {
        "From your cart": "Because it’s in your cart",
        "From your watchlist & activity": "Because you liked it or viewed it",
        "Because you bought": "Based on your purchases",
        "Recommended": "Based on your activity",
        "Trending": "Popular right now",
        "Popular": "Popular in this category",
    }

    used_titles: set[str] = set()
    cache_payload = []
    exclude_ids: set[int] = set(recommended_ids)
    for label, seed in seed_products[:2]:
        category = seed.category
        exclude_ids |= {seed.id}
        products = _similar_products(seed, exclude_ids=exclude_ids, limit=4)
        exclude_ids |= {p.id for p in products}
        title = f"{label}: Similar to {seed.name}"
        if title in used_titles:
            title = f"{label}: More like {seed.name}"
        used_titles.add(title)
        subtitle = subtitle_by_label.get(label)
        category_sections.append(
            {
                "title": title,
                "category": category,
                "seed_product": seed,
                "subtitle": subtitle,
                "products": products,
            }
        )
        cache_payload.append(
            {
                "title": title,
                "category_id": category.id,
                "seed_product_id": seed.id,
                "subtitle": subtitle,
                "product_ids": [p.id for p in products],
            }
        )
    cache.set(cache_key, cache_payload, timeout=120)
    liked_source_ids: list[int] = list(recommended_ids)
    for section in category_sections:
        if section.get("seed_product"):
            liked_source_ids.append(section["seed_product"].id)
        liked_source_ids.extend([p.id for p in section.get("products") or []])
    context = {
        "hero_products": hero_products,
        "recommended_products": recommended_products,
        "recommended_section_title": recommended_section_title,
        "recommended_section_subtitle": recommended_section_subtitle,
        "category_sections": category_sections,
        "liked_product_ids": liked_product_ids_for_user(request.user, liked_source_ids),
    }
    return render(request, 'home/index.html', context)


def discover_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    record_product_interest(request.user, product)
    shop_url = reverse('shop')
    return redirect(f"{shop_url}?highlight={product.id}#product-{product.id}")

def about(request):
    return render(request, 'home/pages/about/about.html')

def contact(request):
    return render(request, 'home/pages/contact/contact.html')

@xframe_options_sameorigin
def chatbot(request):
    get_token(request)
    return render(request, "home/chatbot.html")


@require_POST
def assistant_api(request):
    """
    Bridge layer endpoint.
    Input JSON: {"intent": "...", "entities": {...}}
    Output JSON: {"reply": "...", "products": [...]}
    """
    try:
        import json

        payload = json.loads((request.body or b"{}").decode("utf-8"))
    except Exception:
        return JsonResponse({"reply": "Invalid request.", "products": []}, status=400)

    intent = validate_intent(payload.get("intent"))
    entities = coerce_entities(payload.get("entities"))

    if intent != "search":
        return JsonResponse(
            {
                "reply": "Tell me what you’re looking for (for example: “laptops under $500”).",
                "products": [],
            }
        )

    products = search_products(request, entities=entities, limit=8)
    if not products:
        return JsonResponse(
            {
                "reply": "I couldn’t find a matching product. Try different keywords or adjust your budget.",
                "products": [],
            }
        )

    return JsonResponse(
        {
            "reply": f"Here are the products I found for “{entities.query}”:",
            "products": products,
        }
    )
def login(request):
    if request.method == 'POST':
        form = loginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                auth_login(request, user)
                messages.success(request, 'Welcome Back')
                return redirect('vendor_dashboard')
            else:
                messages.error(request, 'Invalid Credentials')
                return redirect('login')
    else:
        form = loginForm()
    return render(request, 'home/pages/auth/login.html', {'form': form})

def register(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                form.save()
                username = form.cleaned_data.get('username')
                password = form.cleaned_data.get('password1')
                user = authenticate(username=username, password=password)
                auth_login(request, user)
                messages.success(request, 'Welcome Back')
                return redirect('vendor_dashboard')
        else:
            messages.error(request, 'Invalid Credentials')
            return redirect('register')
    else:
        form = SignUpForm()
    return render(request, 'home/pages/auth/register.html', {'form': form})
