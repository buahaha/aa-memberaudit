import datetime as dt
from typing import Optional

from django.utils.timezone import now

from ..app_settings import MEMBERAUDIT_DATA_RETENTION_LIMIT
from ..utils import datetime_round_hour


def data_retention_cutoff() -> Optional[dt.datetime]:
    """returns cutoff datetime for data retention of None if unlimited"""
    if MEMBERAUDIT_DATA_RETENTION_LIMIT is None:
        return None
    else:
        return datetime_round_hour(
            now() - dt.timedelta(days=MEMBERAUDIT_DATA_RETENTION_LIMIT)
        )
