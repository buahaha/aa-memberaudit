from django.db import models

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .utils import LoggerAddTag


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class OwnerManager(models.Manager):
    def unregistered_characters_of_user_count(self, user) -> int:
        return CharacterOwnership.objects.filter(
            user=user, memberaudit_owner__isnull=True
        ).count()
