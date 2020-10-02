from django.contrib.auth.models import User
from django.db import models

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .utils import LoggerAddTag


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class CharacterManager(models.Manager):
    def unregistered_characters_of_user_count(self, user: User) -> int:
        return CharacterOwnership.objects.filter(
            user=user, memberaudit_character__isnull=True
        ).count()

    def user_has_access(self, user: User) -> models.QuerySet:
        if user.has_perm("memberaudit.view_everything"):
            qs = self.all()
        else:
            qs = self.select_related(
                "character_ownership__user",
            ).filter(character_ownership__user=user)
            if (
                user.has_perm("memberaudit.view_same_alliance")
                and user.profile.main_character.alliance_id
            ):
                qs = qs | self.select_related("character_ownership__character").filter(
                    character_ownership__character__alliance_id=user.profile.main_character.alliance_id
                )
            elif user.has_perm("memberaudit.view_same_corporation"):
                qs = qs | self.select_related("character_ownership__character").filter(
                    character_ownership__character__corporation_id=user.profile.main_character.corporation_id
                )

            if user.has_perm("memberaudit.view_shared_characters"):
                qs = qs | self.filter(is_shared=True)

        return qs
