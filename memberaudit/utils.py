"""
Utility functions meant to be used in many apps

Version 1.3.1
"""

import socket
from datetime import datetime, timedelta
import functools
import hashlib
import json
import logging
import os
import re
from typing import Any, Union
from urllib.parse import urljoin

from pytz import timezone

from django.apps import apps
from django.core.cache import cache
from django.conf import settings
from django.contrib.messages.constants import DEBUG, ERROR, SUCCESS, WARNING, INFO
from django.contrib import messages
from django.db import models
from django.test import TestCase
from django.urls import reverse
from django.utils.functional import lazy
from django.utils.html import format_html, mark_safe
from django.utils.translation import gettext_lazy as _


format_html_lazy = lazy(format_html, str)


###################
# logging


class LoggerAddTag(logging.LoggerAdapter):
    """add custom tag to a logger"""

    def __init__(self, my_logger, prefix):
        super(LoggerAddTag, self).__init__(my_logger, {})
        self.prefix = prefix

    def process(self, msg, kwargs):
        return "[%s] %s" % (self.prefix, msg), kwargs


logger = LoggerAddTag(logging.getLogger(__name__), __package__)


def make_logger_prefix(tag: str):
    """creates a function to add logger prefix, which returns tag when used empty"""
    return lambda text="": "{}{}".format(tag, (": " + text) if text else "")


###################
# datetime

# Format for output of datetime for this app
DATETIME_FORMAT = "%Y-%m-%d %H:%M"


def datetime_round_hour(obj) -> datetime:
    """Rounds to nearest hour"""
    return obj.replace(second=0, microsecond=0, minute=0, hour=obj.hour) + timedelta(
        hours=obj.minute // 30
    )


def dt_eveformat(dt: object) -> str:
    """converts a datetime to a string in eve format
    e.g. '2019-06-25T19:04:44'
    """
    dt2 = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    return dt2.isoformat()


def timeuntil_str(duration: timedelta) -> str:
    """return the duration as nicely formatted string.
    Or empty string if duration is negative.

    Format: '[[[999y] [99m]] 99d] 99h 99m 99s'
    """
    seconds = int(duration.total_seconds())
    if seconds > 0:
        periods = [
            # Translators: Abbreviation for years
            (_("y"), 60 * 60 * 24 * 365, False),
            # Translators: Abbreviation for months
            (_("mt"), 60 * 60 * 24 * 30, False),
            # Translators: Abbreviation for days
            (_("d"), 60 * 60 * 24, False),
            # Translators: Abbreviation for hours
            (_("h"), 60 * 60, True),
            # Translators: Abbreviation for months
            (_("m"), 60, True),
            # Translators: Abbreviation for seconds
            (_("s"), 1, True),
        ]
        strings = list()
        for period_name, period_seconds, period_static in periods:
            if seconds >= period_seconds or period_static:
                period_value, seconds = divmod(seconds, period_seconds)
                strings.append("{}{}".format(period_value, period_name))

        result = " ".join(strings)
    else:
        result = ""

    return result


###################
# html


def add_no_wrap_html(text: str) -> str:
    """add no-wrap HTML to text"""
    return format_html('<span style="white-space: nowrap;">{}</span>', mark_safe(text))


def create_link_html(url: str, label: str, new_window: bool = True) -> str:
    """create html link and return HTML"""
    return format_html(
        '<a href="{}"{}>{}</a>',
        url,
        mark_safe(' target="_blank"') if new_window else "",
        label,
    )


def add_bs_label_html(text: str, label: str = "default") -> str:
    """create Bootstrap label and return HTML"""
    return format_html('<div class="label label-{}">{}</div>', label, text)


def create_bs_glyph_html(glyph_name: str) -> str:
    return format_html(
        '<span class="glyphicon glyphicon-{}"></span>', glyph_name.lower()
    )


def create_bs_glyph_2_html(glyph_name, tooltip_text=None, color="initial"):
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


def create_bs_button_html(
    url: str, glyph_name: str, button_type: str, disabled: bool = False
) -> str:
    """create BS botton and return HTML"""
    return format_html(
        '<a href="{}" class="btn btn-{}"{}>{}</a>',
        url,
        button_type,
        mark_safe(' disabled="disabled"') if disabled else "",
        create_bs_glyph_html(glyph_name),
    )


def create_fa_button_html(
    url: str,
    fa_code: str,
    button_type: str,
    tooltip: str = None,
    disabled: bool = False,
) -> str:
    """create BS botton and return HTML"""
    return format_html(
        '<a href="{}" class="btn btn-{}"{}>{}{}</a>',
        url,
        button_type,
        mark_safe(f' title="{tooltip}"') if tooltip else "",
        mark_safe(' disabled="disabled"') if disabled else "",
        mark_safe(f'<i class="{fa_code}"></i>'),
    )


###################
# text


def yesno_str(value: bool) -> str:
    """returns yes/no for boolean as string and with localization"""
    return _("yes") if value is True else _("no")


def humanize_value(value: float, precision: int = 2) -> str:
    """returns given value in human readable and abbreviated form
    e.g. 1234678 -> 1.23m
    """
    value = float(value)
    for exponent, identifier in [(12, "t"), (9, "b"), (6, "m"), (3, "k")]:
        if value >= pow(10, exponent):
            return f"{value / pow(10, exponent):,.{precision}f}{identifier}"

    return f"{value:,.{precision}f}"


###################
# django


def app_labels() -> set:
    """returns set of all current app labels"""
    return {x for x in apps.app_configs.keys()}


def get_absolute_url(url_name: str) -> str:
    """Returns absolute URL for the given URL name."""
    return urljoin(get_site_base_url(), reverse(url_name))


class messages_plus:
    """Pendant to Django messages adding level icons and HTML support

    Careful: Use with safe strings only
    """

    _glyph_map = {
        DEBUG: "eye-open",
        INFO: "info-sign",
        SUCCESS: "ok-sign",
        WARNING: "exclamation-sign",
        ERROR: "alert",
    }

    @classmethod
    def _add_messages_icon(cls, level: int, message: str) -> str:
        """Adds an level based icon to standard Django messages"""
        if level not in cls._glyph_map:
            raise ValueError("glyph for level not defined")
        else:
            glyph = cls._glyph_map[level]

        return format_html(
            '<span class="glyphicon glyphicon-{}" '
            'aria-hidden="true"></span>&nbsp;&nbsp;{}',
            glyph,
            message,
        )

    @classmethod
    def debug(
        cls,
        request: object,
        message: str,
        extra_tags: str = "",
        fail_silently: bool = False,
    ):
        messages.debug(
            request, cls._add_messages_icon(DEBUG, message), extra_tags, fail_silently
        )

    @classmethod
    def info(
        cls,
        request: object,
        message: str,
        extra_tags: str = "",
        fail_silently: bool = False,
    ):
        messages.info(
            request, cls._add_messages_icon(INFO, message), extra_tags, fail_silently
        )

    @classmethod
    def success(
        cls,
        request: object,
        message: str,
        extra_tags: str = "",
        fail_silently: bool = False,
    ):
        messages.success(
            request, cls._add_messages_icon(SUCCESS, message), extra_tags, fail_silently
        )

    @classmethod
    def warning(
        cls,
        request: object,
        message: str,
        extra_tags: str = "",
        fail_silently: bool = False,
    ):
        messages.warning(
            request, cls._add_messages_icon(WARNING, message), extra_tags, fail_silently
        )

    @classmethod
    def error(
        cls,
        request: object,
        message: str,
        extra_tags: str = "",
        fail_silently: bool = False,
    ):
        messages.error(
            request, cls._add_messages_icon(ERROR, message), extra_tags, fail_silently
        )


def clean_setting(
    name: str,
    default_value: object,
    min_value: int = None,
    max_value: int = None,
    required_type: type = None,
    choices: list = None,
) -> Any:
    """cleans the input for a custom setting

    Will use default_value if setting is not defined.
    Will use minimum or maximum value if respective boundary is exceeded.

    Args:
    - `default_value`: value to use if setting is not defined
    - `min_value`: minimum allowed value (0 assumed for int)
    - `max_value`: maximum value value
    - `required_type`: Mandatory if `default_value` is `None`,
    otherwise derived from default_value

    Returns:
    - cleaned value for setting
    """
    if default_value is None and not required_type:
        raise ValueError("You must specify a required_type for None defaults")

    if not required_type:
        required_type = type(default_value)

    if min_value is None and issubclass(required_type, int):
        min_value = 0

    if issubclass(required_type, int) and default_value is not None:
        if min_value is not None and default_value < min_value:
            raise ValueError("default_value can not be below min_value")
        if max_value is not None and default_value > max_value:
            raise ValueError("default_value can not be above max_value")

    if not hasattr(settings, name):
        cleaned_value = default_value
    else:
        dirty_value = getattr(settings, name)
        if dirty_value is None or (
            isinstance(dirty_value, required_type)
            and (min_value is None or dirty_value >= min_value)
            and (max_value is None or dirty_value <= max_value)
            and (choices is None or dirty_value in choices)
        ):
            cleaned_value = dirty_value
        elif (
            isinstance(dirty_value, required_type)
            and min_value is not None
            and dirty_value < min_value
        ):
            logger.warn(
                "You setting for {} it not valid. Please correct it. "
                "Using minimum value for now: {}".format(name, min_value)
            )
            cleaned_value = min_value
        elif (
            isinstance(dirty_value, required_type)
            and max_value is not None
            and dirty_value > max_value
        ):
            logger.warn(
                "You setting for {} it not valid. Please correct it. "
                "Using maximum value for now: {}".format(name, max_value)
            )
            cleaned_value = max_value
        else:
            logger.warn(
                "You setting for {} it not valid. Please correct it. "
                "Using default for now: {}".format(name, default_value)
            )
            cleaned_value = default_value
    return cleaned_value


###################
# serializers


class JSONDateTimeDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs) -> None:
        json.JSONDecoder.__init__(
            self, object_hook=self.dict_to_object, *args, **kwargs
        )

    def dict_to_object(self, dct: dict) -> object:
        if "__type__" not in dct:
            return dct

        type_str = dct.pop("__type__")
        zone, _ = dct.pop("tz")
        dct["tzinfo"] = timezone(zone)
        try:
            dateobj = datetime(**dct)
            return dateobj
        except (ValueError, TypeError):
            dct["__type__"] = type_str
            return dct


class JSONDateTimeEncoder(json.JSONEncoder):
    """Instead of letting the default encoder convert datetime to string,
    convert datetime objects into a dict, which can be decoded by the
    JSONDateTimeDecoder
    """

    def default(self, o: Any) -> Any:
        if isinstance(o, datetime):
            return {
                "__type__": "datetime",
                "year": o.year,
                "month": o.month,
                "day": o.day,
                "hour": o.hour,
                "minute": o.minute,
                "second": o.second,
                "microsecond": o.microsecond,
                "tz": (o.tzinfo.tzname(o), o.utcoffset().total_seconds()),
            }
        else:
            return json.JSONEncoder.default(self, o)


###################
# tests


def generate_invalid_pk(MyModel: models.Model) -> int:
    """return an invalid PK for the given Django model"""
    pk_max = MyModel.objects.aggregate(models.Max("pk"))["pk__max"]
    return pk_max + 1 if pk_max else 1


class SocketAccessError(Exception):
    pass


class NoSocketsTestCase(TestCase):
    """Variation of TestCase class that prevents any use of sockets"""

    @classmethod
    def setUpClass(cls):
        cls.socket_original = socket.socket
        socket.socket = cls.guard
        return super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        socket.socket = cls.socket_original
        return super().tearDownClass()

    @staticmethod
    def guard(*args, **kwargs):
        raise SocketAccessError("Attempted to access network")


def set_test_logger(logger_name: str, name: str) -> object:
    """set logger for current test module

    Args:
    - logger: current logger object
    - name: name of current module, e.g. __file__

    Returns:
    - amended logger
    """

    # reconfigure logger so we get logging from tested module
    f_format = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(module)s:%(funcName)s - %(message)s"
    )
    f_handler = logging.FileHandler("{}.log".format(os.path.splitext(name)[0]), "w+")
    f_handler.setFormatter(f_format)
    my_logger = logging.getLogger(logger_name)
    my_logger.level = logging.DEBUG
    my_logger.addHandler(f_handler)
    my_logger.propagate = False
    return my_logger


###################
# cache


class ObjectCacheMixin:
    """Adds a simple object cache to a Django manager"""

    def get_cached(
        self,
        pk,
        timeout: Union[int, float] = None,
        select_related: str = None,
    ) -> models.Model:
        """Will return the requested object either from DB or from cache

        Args:
        - pk: Primary key for object to fetch
        - timeout: Timeout in seconds for cache
        - select_related: select_related query to be applied (if any)
        Exceptions:
        - raised Model.DoesNotExist if object can not be found
        """
        func = functools.partial(
            self._fetch_object_for_cache, pk=pk, select_related=select_related
        )
        return cache.get_or_set(
            self._create_object_cache_key(pk, select_related), func, timeout
        )

    def _create_object_cache_key(self, pk, select_related: str = None) -> str:
        suffix = (
            hashlib.md5(select_related.encode("utf-8")).hexdigest()
            if select_related
            else ""
        )
        return "{}_{}_{}{}".format(
            self.model._meta.app_label,
            self.model._meta.model_name,
            pk,
            f"_{suffix}" if suffix else "",
        )

    def _fetch_object_for_cache(self, pk, select_related: str = None):
        qs = self.select_related(select_related) if select_related else self
        return qs.get(pk=pk)


def cached_queryset(
    queryset: models.QuerySet, key: str, timeout: Union[int, float]
) -> models.QuerySet:
    return cache.get_or_set(key, lambda: queryset, timeout)


###################
# allianceauth


def get_site_base_url() -> str:
    """return base URL for this site"""
    try:
        match = re.match(r"(.+)\/sso\/callback", settings.ESI_SSO_CALLBACK_URL)
        if match:
            return match.group(1)
    except AttributeError:
        pass

    return ""


###################
# esi


def get_swagger_spec_path() -> str:
    """returns the path to the current swagger spec file"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "swagger.json")


###################
# helpers


def chunks(lst, size):
    """Yield successive sized chunks from lst."""
    for i in range(0, len(lst), size):
        yield lst[i : i + size]
