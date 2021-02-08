from typing import Optional

from django.utils.functional import lazy
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _


DEFAULT_ICON_SIZE = 32
format_html_lazy = lazy(format_html, str)


# old: add_bs_label_html
def bootstrap_label_html(text: str, label: str = "default") -> str:
    """create Bootstrap label and return HTML"""
    return format_html('<div class="label label-{}">{}</div>', label, text)


# old: create_bs_glyph_html
def bootstrap_glyph_html(glyph_name: str) -> str:
    return format_html(
        '<span class="glyphicon glyphicon-{}"></span>', glyph_name.lower()
    )


# old: create_bs_glyph_2_html
def bootstrap_glyph_2_html(glyph_name, tooltip_text=None, color="initial"):
    if tooltip_text:
        tooltip_html = mark_safe(
            'aria-hidden="true" data-toggle="tooltip" data-placement="top" '
            'title="{}"'.format(tooltip_text)
        )
    else:
        tooltip_html = ""
    return format_html(
        '<span class="glyphicon glyphicon-{}"'
        ' style="color:{};"{}></span>'.format(glyph_name.lower(), color, tooltip_html)
    )


def bootstrap_icon_plus_name_html(
    icon_url,
    name,
    size: int = DEFAULT_ICON_SIZE,
    avatar: bool = False,
    url: str = None,
    text: str = None,
) -> str:
    """returns HTML to display an icon next to a name. Can also be a link."""
    name_html = link_html(url, name, new_window=False) if url else name
    if text:
        name_html = format_html("{}&nbsp;{}", name_html, text)

    return format_html(
        "{}&nbsp;&nbsp;&nbsp;{}",
        image_html(
            icon_url, classes=["ra-avatar", "img-circle"] if avatar else [], size=size
        ),
        name_html,
    )


# old: create_bs_button_html
def bootstrap_link_button_html(
    url: str, glyph_name: str, button_type: str, disabled: bool = False
) -> str:
    """returns bootstrap link button and return HTML"""
    return format_html(
        '<a href="{}" class="btn btn-{}"{}>{}</a>',
        url,
        button_type,
        mark_safe(' disabled="disabled"') if disabled else "",
        bootstrap_glyph_html(glyph_name),
    )


# old: create_fa_button_html
def fontawesome_link_button_html(
    url: str,
    fa_code: str,
    button_type: str,
    tooltip: str = None,
    disabled: bool = False,
) -> str:
    """create fontawesome button and return HTML"""
    return format_html(
        '<a href="{}" class="btn btn-{}"{}>{}{}</a>',
        url,
        button_type,
        mark_safe(f' title="{tooltip}"') if tooltip else "",
        mark_safe(' disabled="disabled"') if disabled else "",
        mark_safe(f'<i class="{fa_code}"></i>'),
    )


def humanize_value(value: float, precision: int = 2) -> str:
    """returns given value in human readable and abbreviated form
    e.g. 1234678 -> 1.23m
    """
    value = float(value)
    for exponent, identifier in [(12, "t"), (9, "b"), (6, "m"), (3, "k")]:
        if value >= pow(10, exponent):
            return f"{value / pow(10, exponent):,.{precision}f}{identifier}"

    return f"{value:,.{precision}f}"


def image_html(src: str, classes: list = None, size: int = None) -> str:
    classes_str = format_html('class="{}"', (" ".join(classes)) if classes else "")
    size_html = format_html('width="{}" height="{}"', size, size) if size else ""
    return format_html('<img {} {} src="{}">', classes_str, size_html, src)


# old: create_link_html
def link_html(url: str, label: str, new_window: bool = True) -> str:
    """create html link and return HTML"""
    return format_html(
        '<a href="{}"{}>{}</a>',
        url,
        mark_safe(' target="_blank"') if new_window else "",
        label,
    )


# old: add_no_wrap_html
def no_wrap_html(text: str) -> str:
    """add no-wrap HTML to text"""
    return format_html('<span class="text-nowrap;">{}</span>', mark_safe(text))


def yesno_str(value: bool) -> str:
    """returns yes/no for boolean as string and with localization"""
    return _("yes") if value is True else _("no")


def yesnonone_str(value: Optional[bool]) -> str:
    """returns yes/no/none for boolean as string and with localization"""
    if value is True:
        return _("yes")
    elif value is False:
        return _("no")
    else:
        return ""
