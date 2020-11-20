import datetime as dt
from email.utils import parsedate_to_datetime
import json
from math import ceil
from typing import Optional, Tuple

from django.core.cache import cache
from django.utils.dateparse import parse_datetime
from django.utils.timezone import now

from allianceauth.services.hooks import get_extension_logger
from . import __title__
from .utils import LoggerAddTag


logger = LoggerAddTag(get_extension_logger(__name__), __title__)
ESI_ERROR_LIMIT = 25


class EsiErrorStatus:
    """DTO for ESI error status - immutable"""

    def __init__(self, remain: int, until: dt.datetime) -> None:
        if not isinstance(until, dt.datetime):
            raise TypeError("until must be of type datetime.datetime")

        self._remain = int(remain)
        self._until = until

    def __str__(self) -> str:
        return (
            f"ESI error status: remain = {self.remain}, "
            f"until = '{self.until.isoformat()}'"
        )

    @property
    def remain(self) -> int:
        return self._remain

    @property
    def until(self) -> dt.datetime:
        return self._until

    @property
    def reset(self) -> int:
        return ceil((self.until - now()).total_seconds())

    @property
    def is_exceeded(self) -> bool:
        return self.remain <= ESI_ERROR_LIMIT

    @property
    def is_valid(self) -> bool:
        return self.reset > 0

    def asjson(self) -> str:
        data = {
            "remain": self.remain,
            "until": self.until.isoformat(),
        }
        return json.dumps(data)

    @classmethod
    def from_json(cls, data_json: str) -> "EsiErrorStatus":
        if not data_json:
            raise ValueError("data_json string can not be empty")

        data = json.loads(data_json)
        return cls(remain=data.get("remain"), until=parse_datetime(data.get("until")))

    @classmethod
    def from_headers(cls, headers: dict) -> "EsiErrorStatus":
        try:
            remain = int(headers.get("X-Esi-Error-Limit-Remain"))
            reset = int(headers.get("X-Esi-Error-Limit-Reset"))
        except TypeError as ex:
            logger.warning("Failed to parse HTTP headers: %s", headers, exc_info=True)
            raise ex

        else:
            request_date = (
                parsedate_to_datetime(headers.get("Date"))
                if headers.get("Date")
                else now()
            )
            until = request_date + dt.timedelta(seconds=reset)
            return cls(remain=remain, until=until)


class EsiErrorManager:
    """Manager for global ESI error rate limit

    This class is designed to be used by concurrent threads.
    """

    ESI_ERRORS_CACHE_KEY = "MEMBERAUDIT_ESI_ERRORS"
    UNTIL_MAX_DEVIATION_SECS = 5

    def get(self) -> Optional[EsiErrorStatus]:
        """returns the current ESI error status (if any) or None"""
        try:
            data_json = cache.get(self.ESI_ERRORS_CACHE_KEY)
        except Exception:
            logger.warning("Failed to read ESI error status from cache", exc_info=True)
            return None
        else:
            if not data_json:
                return None

            return EsiErrorStatus.from_json(data_json)

    def _set_status(self, esi_error_status) -> bool:
        """sets the current ESI error status"""
        try:
            cache.set(
                key=self.ESI_ERRORS_CACHE_KEY,
                value=esi_error_status.asjson(),
                timeout=esi_error_status.reset,
            )
        except Exception:
            logger.warning("Failed to write ESI error status to cache", exc_info=True)
            return False
        else:
            return True

    def update(self, headers: dict) -> Tuple[Optional[EsiErrorStatus], bool]:
        """update ESI error status from HTTP headers

        Returns:
            esi_error_status, is_updated
        """
        try:
            new_status = EsiErrorStatus.from_headers(headers)
        except TypeError:
            return None, False
        else:
            current_status = self.get()
            if current_status:
                is_current_window = (
                    abs((current_status.until - new_status.until).total_seconds())
                    < self.UNTIL_MAX_DEVIATION_SECS
                )
                if is_current_window:
                    if new_status.remain >= current_status.remain:
                        return current_status, False

                elif new_status.until < current_status.until:
                    return current_status, False

            if self._set_status(new_status):
                return new_status, True
            else:
                return None, False


esi_errors = EsiErrorManager()
