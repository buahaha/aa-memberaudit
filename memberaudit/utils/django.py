import logging
from typing import Any

from django.apps import apps
from django.conf import settings

from .logging import LoggerAddTag


logger = LoggerAddTag(logging.getLogger(__name__), __package__)


def app_labels() -> set:
    """returns set of all current app labels"""
    return {x for x in apps.app_configs.keys()}


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
