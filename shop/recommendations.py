from __future__ import annotations

import math
import logging
import os
from typing import Optional

from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.db.models import Case, Count, F, IntegerField, QuerySet, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.conf import settings

from dashboard.models import Product
from payment.models import OrderItem
from shop.models import LikedProduct, ProductInterest
from cart.models import CartItem


DEFAULT_REC_SIZES: tuple[int, ...] = (5,)
DEFAULT_MAX_PER_CATEGORY: int = 2
_LOGGER = logging.getLogger(__name__)


def _obs_enabled() -> bool:
    return bool(getattr(settings, "DEBUG", False) or os.getenv("RECS_OBS", "").strip() == "1")


def _invalidate_user_recs_cache(user_id: int, sizes: tuple[int, ...] = DEFAULT_REC_SIZES) -> None:
    for size in sizes:
        cache.delete(f"recs:u:{user_id}:{size}")


def record_product_interest(user: Optional[User], product: Product, weight: int = 1) -> None:
    if not user or isinstance(user, AnonymousUser) or not getattr(user, "is_authenticated", False):
        return
    interest, _created = ProductInterest.objects.get_or_create(
        user=user,
        product=product,
        defaults={"score": 0},
    )
    ProductInterest.objects.filter(id=interest.id).update(score=F("score") + max(1, int(weight)))
    _invalidate_user_recs_cache(user.id)


def record_cart_interest(user: Optional[User], weight: int = 1) -> None:
    if not user or isinstance(user, AnonymousUser) or not getattr(user, "is_authenticated", False):
        return
    product_ids = list(
        CartItem.objects.filter(user=user).values_list("product_id", flat=True).distinct()
    )
    if not product_ids:
        return
    products = list(Product.objects.filter(id__in=product_ids))
    existing = {
        pi.product_id: pi.id
        for pi in ProductInterest.objects.filter(user=user, product_id__in=product_ids).only("id", "product_id")
    }
    to_create = [
        ProductInterest(user=user, product=product, score=0)
        for product in products
        if product.id not in existing
    ]
    if to_create:
        ProductInterest.objects.bulk_create(to_create, ignore_conflicts=True)
    ProductInterest.objects.filter(user=user, product_id__in=product_ids).update(
        score=F("score") + max(1, int(weight))
    )
    _invalidate_user_recs_cache(user.id)


def get_recommended_products(user: Optional[User], n: int = 5) -> QuerySet[Product]:
    """
    Returns an ordered queryset of up to `n` recommended products.

    Signals used:
    - Purchases (quantity-weighted)
    - Interest (time-decayed ProductInterest scores)
    - Cart items (quantity-weighted intent)
    - Cancelled orders (weak negative/intent signal; used as seeds only)
    - Collaborative filtering (co-purchases by similar users)
    - Category fallback
    - Anonymous fallback: interleaved top-selling + recent
    """
    if n <= 0:
        return Product.objects.none()

    def _apply_category_diversity(product_ids: list[int], limit: int) -> list[int]:
        """
        Enforces a simple diversity rule: cap items per category.
        Keeps ordering stable.
        """
        if not product_ids or limit <= 0:
            return []
        # Fetch category ids in one query.
        cat_map = {
            int(pid): int(cid) if cid is not None else -1
            for pid, cid in Product.objects.filter(id__in=product_ids).values_list("id", "category_id")
        }
        per_cat: dict[int, int] = {}
        out: list[int] = []
        for pid in product_ids:
            cat_id = cat_map.get(int(pid), -1)
            count = per_cat.get(cat_id, 0)
            if count >= DEFAULT_MAX_PER_CATEGORY:
                continue
            per_cat[cat_id] = count + 1
            out.append(int(pid))
            if len(out) >= limit:
                break
        return out

    def _ordered_qs(product_ids: list[int]) -> QuerySet[Product]:
        if not product_ids:
            return Product.objects.none()
        order_by_case = Case(
            *[When(id=product_id, then=idx) for idx, product_id in enumerate(product_ids)],
            output_field=IntegerField(),
        )
        return Product.objects.filter(id__in=product_ids, quantity__gt=0).order_by(order_by_case)

    def _anon_fallback(limit: int, exclude_ids: set[int] | None = None) -> list[int]:
        exclude_ids = exclude_ids or set()
        top_selling = list(
            Product.objects.filter(quantity__gt=0).exclude(id__in=exclude_ids)
            .annotate(
                sold=Coalesce(Sum("orderitem__quantity"), Value(0)),
            )
            .order_by("-sold", "-updated_at")
            .values_list("id", flat=True)[: limit * 2]
        )
        recent = list(
            Product.objects.filter(quantity__gt=0).exclude(id__in=exclude_ids)
            .order_by("-created_at")
            .values_list("id", flat=True)[: limit * 2]
        )
        out: list[int] = []
        seen: set[int] = set(exclude_ids)
        for i in range(max(len(top_selling), len(recent))):
            for pool in (top_selling, recent):
                if i < len(pool) and pool[i] not in seen:
                    out.append(pool[i])
                    seen.add(pool[i])
                    if len(out) >= limit:
                        return out
        return out

    is_auth = bool(user and not isinstance(user, AnonymousUser) and getattr(user, "is_authenticated", False))

    if not is_auth:
        cache_key = f"recs:anon:{n}"
        cached_ids = cache.get(cache_key)
        if isinstance(cached_ids, list) and cached_ids:
            if _obs_enabled():
                # Observability only: cache hit for anonymous recs.
                _LOGGER.info("recs_obs cache_hit anon n=%s ids=%s", n, len(cached_ids))
            return _ordered_qs([int(x) for x in cached_ids][:n])
        if _obs_enabled():
            # Observability only: cache miss for anonymous recs.
            _LOGGER.info("recs_obs cache_miss anon n=%s", n)

        ids = _apply_category_diversity(_anon_fallback(n * 3), n)
        cache.set(cache_key, ids, timeout=300)  # 5 minutes
        return _ordered_qs(ids)

    assert user is not None
    cache_key = f"recs:u:{user.id}:{n}"
    cached_ids = cache.get(cache_key)
    if isinstance(cached_ids, list) and cached_ids:
        if _obs_enabled():
            # Observability only: cache hit for authenticated recs.
            _LOGGER.info("recs_obs cache_hit user=%s n=%s ids=%s", user.id, n, len(cached_ids))
        return _ordered_qs([int(x) for x in cached_ids][:n])
    if _obs_enabled():
        # Observability only: cache miss for authenticated recs.
        _LOGGER.info("recs_obs cache_miss user=%s n=%s", user.id, n)

    now = timezone.now()
    half_life_days = 14.0
    decay_lambda = math.log(2) / half_life_days

    interest_rows = list(
        ProductInterest.objects.filter(user=user)
        .only("product_id", "score", "updated_at")
        .order_by("-updated_at")[:200]
    )
    interest_scores: dict[int, float] = {}
    if _obs_enabled() and interest_rows:
        # Observability only: signal sanity snapshot (no logic change).
        scores = [float(r.score) for r in interest_rows]
        ages = [
            max(0.0, (now - r.updated_at).total_seconds() / 86400.0)
            for r in interest_rows
        ]
        _LOGGER.info(
            "recs_obs interest_stats user=%s score_min=%.2f score_max=%.2f score_avg=%.2f age_min=%.2f age_max=%.2f",
            user.id,
            min(scores),
            max(scores),
            (sum(scores) / max(1, len(scores))),
            min(ages),
            max(ages),
        )
    for row in interest_rows:
        age_days = max(0.0, (now - row.updated_at).total_seconds() / 86400.0)
        decayed = float(row.score) * math.exp(-decay_lambda * age_days)
        if decayed > 0:
            interest_scores[row.product_id] = interest_scores.get(row.product_id, 0.0) + decayed
        if _obs_enabled():
            # Observability only: time-decay sanity snapshot.
            _LOGGER.debug(
                "recs_obs interest_decay user=%s product=%s age_days=%.2f raw_score=%.2f decayed=%.4f",
                user.id,
                row.product_id,
                age_days,
                float(row.score),
                decayed,
            )

    purchased_qty = {
        r["product_id"]: int(r["qty"] or 0)
        for r in OrderItem.objects.filter(order__user=user, product__quantity__gt=0)
        .values("product_id")
        .annotate(qty=Coalesce(Sum("quantity"), Value(0)))
    }
    cart_qty = {
        r["product_id"]: int(r["qty"] or 0)
        for r in CartItem.objects.filter(user=user, product__quantity__gt=0)
        .values("product_id")
        .annotate(qty=Coalesce(Sum("quantity"), Value(0)))
    }
    cancelled_qty = {
        r["product_id"]: int(r["qty"] or 0)
        for r in OrderItem.objects.filter(order__user=user, order__status="CANCELLED", product__quantity__gt=0)
        .values("product_id")
        .annotate(qty=Coalesce(Sum("quantity"), Value(0)))
    }
    avoid_ids: set[int] = set(cancelled_qty.keys())

    liked_ids = list(
        LikedProduct.objects.filter(user=user).values_list("product_id", flat=True)[:500]
    )

    seed_score: dict[int, float] = {}
    if _obs_enabled():
        # Observability only: seed signal contribution sizes.
        _LOGGER.info(
            "recs_obs signal_counts user=%s likes=%s purchases=%s cart=%s interest=%s cancelled=%s",
            user.id,
            len(liked_ids),
            len(purchased_qty),
            len(cart_qty),
            len(interest_scores),
            len(cancelled_qty),
        )
    for product_id in liked_ids:
        seed_score[int(product_id)] = seed_score.get(int(product_id), 0.0) + 8.0
    for product_id, qty in purchased_qty.items():
        seed_score[product_id] = seed_score.get(product_id, 0.0) + (qty * 5.0)
    for product_id, score in interest_scores.items():
        seed_score[product_id] = seed_score.get(product_id, 0.0) + score
    for product_id, qty in cart_qty.items():
        seed_score[product_id] = seed_score.get(product_id, 0.0) + (qty * 2.0)
    for product_id, qty in cancelled_qty.items():
        # Treat cancelled as "avoid": negative signal.
        seed_score[product_id] = seed_score.get(product_id, 0.0) - (qty * 3.0)

    seed_ids = [
        pid
        for pid, score in sorted(seed_score.items(), key=lambda kv: kv[1], reverse=True)
        if score > 0 and pid not in avoid_ids
    ][: n * 10]
    if _obs_enabled():
        # Observability only: seed size after scoring.
        _LOGGER.info("recs_obs seed_ids user=%s count=%s", user.id, len(seed_ids))
    if not seed_ids:
        ids = _apply_category_diversity(_anon_fallback(n * 3), n)
        cache.set(cache_key, ids, timeout=600)  # 10 minutes
        return _ordered_qs(ids)

    similar_user_ids = list(
        OrderItem.objects.filter(product_id__in=seed_ids, order__user__isnull=False)
        .exclude(order__user=user)
        .values("order__user_id")
        .annotate(shared_qty=Coalesce(Sum("quantity"), Value(0)), shared=Count("product_id", distinct=True))
        .order_by("-shared_qty", "-shared")
        .values_list("order__user_id", flat=True)[:200]
    )

    exclude_seed: set[int] = set(seed_ids) | avoid_ids
    co_purchase_ids = list(
        OrderItem.objects.filter(order__user_id__in=similar_user_ids, product__quantity__gt=0)
        .exclude(product_id__in=exclude_seed)
        .values("product_id")
        .annotate(score=Coalesce(Sum("quantity"), Value(0)))
        .order_by("-score")
        .values_list("product_id", flat=True)[: n * 5]
    )
    if _obs_enabled():
        # Observability only: collaborative pool size.
        _LOGGER.info("recs_obs co_purchase_ids user=%s count=%s", user.id, len(co_purchase_ids))

    category_ids = list(
        Product.objects.filter(id__in=seed_ids)
        .exclude(category_id__isnull=True)
        .values_list("category_id", flat=True)
        .distinct()
    )

    category_rec_ids = list(
        Product.objects.filter(category_id__in=category_ids, quantity__gt=0)
        .exclude(id__in=exclude_seed)
        .exclude(id__in=co_purchase_ids)
        .order_by("-updated_at")
        .values_list("id", flat=True)[: n * 5]
    )
    if _obs_enabled():
        # Observability only: category fallback pool size.
        _LOGGER.info("recs_obs category_rec_ids user=%s count=%s", user.id, len(category_rec_ids))

    ordered_ids: list[int] = []
    seen: set[int] = set(exclude_seed)
    for pool in (co_purchase_ids, category_rec_ids):
        for product_id in pool:
            if product_id not in seen:
                ordered_ids.append(int(product_id))
                seen.add(int(product_id))
            if len(ordered_ids) >= n:
                break
        if len(ordered_ids) >= n:
            break

    if len(ordered_ids) < n:
        ordered_ids.extend(_anon_fallback((n - len(ordered_ids)) * 3, exclude_ids=seen))

    ordered_ids = _apply_category_diversity(ordered_ids, n)
    if len(ordered_ids) < n:
        # Final backfill, still respecting diversity.
        ordered_ids = _apply_category_diversity(
            ordered_ids + _anon_fallback((n - len(ordered_ids)) * 5, exclude_ids=set(ordered_ids)), n
        )
    if _obs_enabled():
        # Observability only: final recommendation count.
        _LOGGER.info("recs_obs final_ordered_ids user=%s count=%s", user.id, len(ordered_ids))
        if not ordered_ids:
            _LOGGER.warning("recs_obs empty_recommendations user=%s n=%s", user.id, n)
        # Observability only: category coverage counts.
        if ordered_ids:
            category_counts = (
                Product.objects.filter(id__in=ordered_ids)
                .values_list("category_id")
                .annotate(count=Count("id"))
            )
            _LOGGER.info(
                "recs_obs category_counts user=%s counts=%s",
                user.id,
                {cid: cnt for cid, cnt in category_counts},
            )
        # Observability only: summary line for dashboards/log aggregation.
        _LOGGER.info(
            "recs_obs summary user=%s seed=%s co_purchase=%s category_pool=%s final=%s",
            user.id,
            len(seed_ids),
            len(co_purchase_ids),
            len(category_rec_ids),
            len(ordered_ids),
        )
    cache.set(cache_key, ordered_ids, timeout=600)  # 10 minutes
    return _ordered_qs(ordered_ids)
