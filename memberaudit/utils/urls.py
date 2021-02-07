import re

from urllib.parse import urljoin

from django.urls import reverse
from django.conf import settings


def get_absolute_url(url_name: str) -> str:
    """Returns absolute URL for the given URL name."""
    return urljoin(get_site_base_url(), reverse(url_name))


# TODO: Only enable for alliance auth
def get_site_base_url() -> str:
    """return base URL for this Alliance Auth site"""
    try:
        match = re.match(r"(.+)\/sso\/callback", settings.ESI_SSO_CALLBACK_URL)
        if match:
            return match.group(1)
    except AttributeError:
        pass

    return ""
