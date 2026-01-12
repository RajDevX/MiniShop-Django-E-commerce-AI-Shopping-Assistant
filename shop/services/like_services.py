from __future__ import annotations

from typing import Iterable, Set

from django.contrib.auth.models import AnonymousUser, User

from shop.models import LikedProduct


def liked_product_ids_for_user(user: User | AnonymousUser | None, product_ids: Iterable[int]) -> Set[int]:
    if not user or isinstance(user, AnonymousUser) or not getattr(user, "is_authenticated", False):
        return set()
    ids = [int(pid) for pid in product_ids if pid is not None]
    if not ids:
        return set()
    return set(
        LikedProduct.objects.filter(user=user, product_id__in=ids).values_list("product_id", flat=True)
    )

