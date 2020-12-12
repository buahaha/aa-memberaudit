"""
common definitions we use in our views
"""

from typing import Optional

from django.utils.html import format_html
from django.utils.translation import gettext_lazy

from allianceauth.services.hooks import get_extension_logger

from memberaudit import __title__
from memberaudit.app_settings import MEMBERAUDIT_APP_NAME
from memberaudit.models import Character
from memberaudit.utils import LoggerAddTag, create_link_html


from memberaudit.views.constants import DEFAULT_ICON_SIZE, MY_DATETIME_FORMAT

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


def yesnonone_str(value: Optional[bool]) -> str:
    """returns yes/no/none for boolean as string and with localization"""
    if value is True:
        return gettext_lazy("yes")
    elif value is False:
        return gettext_lazy("no")
    else:
        return ""


def create_img_html(src: str, classes: list = None, size: int = None) -> str:
    classes_str = format_html('class="{}"', (" ".join(classes)) if classes else "")
    size_html = format_html('width="{}" height="{}"', size, size) if size else ""
    return format_html('<img {} {} src="{}">', classes_str, size_html, src)


def create_icon_plus_name_html(
    icon_url,
    name,
    size: int = DEFAULT_ICON_SIZE,
    avatar: bool = False,
    url: str = None,
    text: str = None,
) -> str:
    """create HTML to display an icon next to a name. Can also be a link."""
    name_html = create_link_html(url, name, new_window=False) if url else name
    if text:
        name_html = format_html("{}&nbsp;{}", name_html, text)

    return format_html(
        "{}&nbsp;&nbsp;&nbsp;{}",
        create_img_html(
            icon_url, classes=["ra-avatar", "img-circle"] if avatar else [], size=size
        ),
        name_html,
    )


def create_main_organization_html(main_character) -> str:
    return format_html(
        "{}{}",
        main_character.corporation_name,
        f" [{main_character.alliance_ticker}]" if main_character.alliance_name else "",
    )


def add_common_context(request, context: dict) -> dict:
    """adds the common context used by all view"""
    unregistered_count = Character.objects.unregistered_characters_of_user_count(
        request.user
    )
    new_context = {
        **{
            "app_title": MEMBERAUDIT_APP_NAME,
            "unregistered_count": unregistered_count,
            "MY_DATETIME_FORMAT": MY_DATETIME_FORMAT,
        },
        **context,
    }
    return new_context
