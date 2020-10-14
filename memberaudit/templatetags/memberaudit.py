from django import template
from django.urls import reverse

register = template.Library()


@register.simple_tag
def navactive_2(request, url_name: str, *args):
    """returns the active class name for navs"""
    url = reverse(url_name, args=args)
    if request.path == url:
        return "active"
    else:
        return ""


@register.filter
def evetype_icon_url(eve_type: object, size: int) -> str:
    """generates a icon image URL for the given eve_type
    Returns URL or empty string
    """
    try:
        return eve_type.icon_url(size)
    except AttributeError:
        return ""
