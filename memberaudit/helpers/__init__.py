from django.utils.html import format_html

from eveuniverse.models import EveSolarSystem

from allianceauth.eveonline.evelinks import dotlan

from ..utils import create_link_html


def eve_solar_system_to_html(solar_system: EveSolarSystem, show_region=True) -> str:
    if solar_system.is_high_sec:
        color = "green"
    elif solar_system.is_low_sec:
        color = "orange"
    else:
        color = "red"

    region_html = (
        f" / {solar_system.eve_constellation.eve_region.name}" if show_region else ""
    )
    return format_html(
        '{} <span style="color: {}">{}</span>{}',
        create_link_html(dotlan.solar_system_url(solar_system.name), solar_system.name),
        color,
        round(solar_system.security_status, 1),
        region_html,
    )
