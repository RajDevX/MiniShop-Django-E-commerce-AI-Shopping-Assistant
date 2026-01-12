from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.urls import reverse

from dashboard.models import Product


@dataclass(frozen=True)
class AssistantEntities:
    query: str | None = None
    category: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    product_id: int | None = None


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _product_url(request, product: Product) -> str:
    return request.build_absolute_uri(reverse("product_public", kwargs={"slug": product.slug}))


def _add_to_cart_url(request, product: Product) -> str:
    return request.build_absolute_uri(reverse("cart_add", kwargs={"product_id": product.id}))


def validate_intent(intent: str) -> str:
    intent = (intent or "").strip().lower()
    if intent in {"search", "cart_show", "cart_add"}:
        return intent
    return "search"


def coerce_entities(raw: dict) -> AssistantEntities:
    raw = raw if isinstance(raw, dict) else {}
    query = raw.get("query")
    if isinstance(query, str):
        query = query.strip() or None
    else:
        query = None

    category = raw.get("category")
    if isinstance(category, str):
        category = category.strip() or None
    else:
        category = None

    return AssistantEntities(
        query=query,
        category=category,
        min_price=_to_decimal(raw.get("min_price")),
        max_price=_to_decimal(raw.get("max_price")),
        product_id=_to_int(raw.get("product_id")),
    )


def search_products(request, *, entities: AssistantEntities, limit: int = 8) -> list[dict]:
    q = (entities.query or "").strip()
    if not q:
        return []

    qs = Product.objects.select_related("category").filter(quantity__gt=0)
    if entities.category:
        qs = qs.filter(category__name__icontains=entities.category)
    if entities.min_price is not None:
        qs = qs.filter(price__gte=entities.min_price)
    if entities.max_price is not None:
        qs = qs.filter(price__lte=entities.max_price)

    qs = qs.filter(
        Q(name__icontains=q) | Q(description__icontains=q) | Q(category__name__icontains=q)
    ).order_by("-updated_at")

    products = list(qs[: max(1, min(int(limit), 10))])
    payload: list[dict] = []
    for p in products:
        image_url = p.image.url if getattr(p, "image", None) else ""
        if image_url:
            image_url = request.build_absolute_uri(image_url)
        payload.append(
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "price": str(p.price),
                "image_url": image_url,
                "product_url": _product_url(request, p),
                "add_to_cart_url": _add_to_cart_url(request, p),
            }
        )
    return payload
