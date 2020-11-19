from collections import namedtuple
from typing import Optional

from bravado.exception import HTTPError
from django.core.cache import cache

from allianceauth.services.hooks import get_extension_logger
from . import __title__
from .utils import LoggerAddTag


logger = LoggerAddTag(get_extension_logger(__name__), __title__)
ESI_ERROR_LIMIT = 25

_EsiErrorStatus = namedtuple("_EsiErrorStatus", ["remain", "reset", "is_exceeded"])


def EsiErrorStatus(remain, reset) -> _EsiErrorStatus:
    """_EsiErrorStatus with added features"""
    return _EsiErrorStatus(int(remain), int(reset), int(remain) <= ESI_ERROR_LIMIT)


class EsiErrors:
    """Wrapper class for managing the global ESI error rate limit"""

    ESI_ERRORS_CACHE_KEY = "MEMBERAUDIT_ESI_ERRORS"

    def get(self) -> Optional[_EsiErrorStatus]:
        """returns the current ESI error status (if any) or None"""
        try:
            remain = cache.get(self.ESI_ERRORS_CACHE_KEY)
            reset = cache.ttl(self.ESI_ERRORS_CACHE_KEY)
        except Exception:
            logger.warning("Failed to read ESI error status from cache", exc_info=True)
            return None
        else:
            if not remain or not reset:
                return None
            else:
                return EsiErrorStatus(remain=remain, reset=reset)

    def set(self, remain: int, reset: int) -> None:
        """sets the current ESI error status"""
        try:
            cache.set(
                key=self.ESI_ERRORS_CACHE_KEY, value=int(remain), timeout=int(reset)
            )
        except Exception:
            logger.warning("Failed to write ESI error status to cache", exc_info=True)

    def set_from_bravado_exception(self, http_error: HTTPError) -> None:
        """set ESI error status with information from HTTPError exception"""
        try:
            remain = int(http_error.response.headers.get("X-Esi-Error-Limit-Remain"))
            reset = int(http_error.response.headers.get("X-Esi-Error-Limit-Reset"))
        except TypeError:
            return None
        else:
            self.set(remain=remain, reset=reset)
            return EsiErrorStatus(remain=remain, reset=reset)


esi_errors = EsiErrors()
