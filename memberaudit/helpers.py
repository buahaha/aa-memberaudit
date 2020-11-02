from typing import Optional

from django.db import models
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from eveuniverse.models import EveSolarSystem, EveEntity
from allianceauth.eveonline.evelinks import dotlan, evewho

from .utils import create_link_html

import re


def get_or_create_esi_or_none(
    prop_name: str, dct: dict, Model: type
) -> Optional[models.Model]:
    """tries to create a new eveuniverse object from a dictionary entry

    return the object on success or None
    """
    if dct.get(prop_name):
        obj, _ = Model.objects.get_or_create_esi(id=dct.get(prop_name))
    else:
        obj = None

    return obj


def get_or_create_or_none(
    prop_name: str, dct: dict, Model: type
) -> Optional[models.Model]:
    """tries to create a new Django object from a dictionary entry

    return the object on success or None
    """
    if dct.get(prop_name):
        obj, _ = Model.objects.get_or_create(id=dct.get(prop_name))
    else:
        obj = None

    return obj


def get_or_none(prop_name: str, dct: dict, Model: type) -> Optional[models.Model]:
    """tries to create a new Django object from a dictionary entry

    return the object on success or None
    """
    id = dct.get(prop_name)
    if id:
        try:
            return Model.objects.get(id=id)
        except Model.DoesNotExist:
            pass

    return None


def eve_solar_system_to_html(solar_system: EveSolarSystem, show_region=True) -> str:
    if solar_system.is_high_sec:
        css_class = "text-high-sec"
    elif solar_system.is_low_sec:
        css_class = "text-low-sec"
    else:
        css_class = "text-null-sec"

    region_html = (
        f" / {solar_system.eve_constellation.eve_region.name}" if show_region else ""
    )
    return format_html(
        '{} <span class="{}">{}</span>{}',
        create_link_html(dotlan.solar_system_url(solar_system.name), solar_system.name),
        css_class,
        round(solar_system.security_status, 1),
        region_html,
    )


_font_regex = re.compile(
    r'<font (?P<pre>.*?)(size="(?P<size>[0-9]{1,2})")? ?(color="#[0-9a-f]{2}(?P<color>[0-9a-f]{6})")?(?P<post>.*?)>'
)
_link_regex = re.compile(
    r'<a href="(?P<schema>[a-z]+):(?P<first_id>\d+)(//(?P<second_id>\d+))?">'
)


def _font_replace(font_match) -> str:
    pre = font_match.group("pre")  # before the color attr
    size = font_match.group("size")
    color = font_match.group("color")  # the raw color (eg. 'ffffff')
    post = font_match.group("post")  # after the color attr

    if color is None or color == "ffffff":
        color_attr = ""
    else:
        color_attr = f"color: #{color};"
    if size is None:
        size_attr = ""
    else:
        size_attr = f"font-size: {size}pt;"
    return f'<span {pre}style="{color_attr} {size_attr}"{post}>'


def _link_replace(link_match) -> str:
    schema = link_match.group("schema")
    first_id = int(link_match.group("first_id"))
    second_id = link_match.group("second_id")
    if second_id is not None:
        second_id = int(second_id)
    if schema == "showinfo":
        if 1373 <= first_id <= 1386:  # Character
            return f'<a href="{evewho.character_url(second_id)}" target="_blank">'
        elif first_id == 5:  # Solar System
            system_name = EveEntity.objects.resolve_name(second_id)
            return f'<a href="{dotlan.solar_system_url(system_name)}" target="_blank">'
        elif first_id == 2:  # Corporation
            corp_name = EveEntity.objects.resolve_name(second_id)
            return f'<a href="{dotlan.corporation_url(corp_name)}" target="_blank">'
        elif first_id == 16159:  # Alliance
            alliance_name = EveEntity.objects.resolve_name(second_id)
            return f'<a href="{dotlan.alliance_url(alliance_name)}" target="_blank">'
    return """<a href="javascript:showInvalidError();">"""


def eve_xml_to_html(xml: str) -> str:
    x = xml.replace("<br>", "\n")
    x = _font_regex.sub(_font_replace, x)
    x = x.replace("</font>", "</span>")
    x = _link_regex.sub(_link_replace, x)
    # x = strip_tags(x)
    x = x.replace("\n", "<br>")
    return mark_safe(x)
