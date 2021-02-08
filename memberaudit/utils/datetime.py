from datetime import datetime, timedelta

from django.utils.translation import gettext_lazy as _


# Default format for output of datetime
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
