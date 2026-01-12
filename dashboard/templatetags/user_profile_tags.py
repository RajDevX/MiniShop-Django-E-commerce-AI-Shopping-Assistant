from __future__ import annotations

from django import template
from django.templatetags.static import static

from django.contrib.auth.models import AnonymousUser

from dashboard.models import UserProfile


register = template.Library()


@register.simple_tag
def user_avatar_url(user) -> str:
    if not user or isinstance(user, AnonymousUser) or not getattr(user, "is_authenticated", False):
        return static("home/images/person_1.jpg")
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if getattr(profile, "avatar", None):
        try:
            return profile.avatar.url
        except Exception:
            return static("home/images/person_1.jpg")
    return static("home/images/person_1.jpg")

