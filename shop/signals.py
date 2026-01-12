from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from cart.models import CartItem
from shop.models import LikedProduct, ProductInterest
from shop.recommendations import _invalidate_user_recs_cache


@receiver(post_save, sender=ProductInterest)
@receiver(post_delete, sender=ProductInterest)
def invalidate_recs_on_interest_change(sender, instance, **kwargs):
    _invalidate_user_recs_cache(instance.user_id)


@receiver(post_save, sender=CartItem)
@receiver(post_delete, sender=CartItem)
def invalidate_recs_on_cart_change(sender, instance, **kwargs):
    _invalidate_user_recs_cache(instance.user_id)


@receiver(post_save, sender=LikedProduct)
@receiver(post_delete, sender=LikedProduct)
def invalidate_recs_on_like_change(sender, instance, **kwargs):
    _invalidate_user_recs_cache(instance.user_id)
