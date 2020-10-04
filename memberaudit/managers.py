import datetime as dt
from typing import Tuple

from django.contrib.auth.models import User
from django.db import models
from django.utils.timezone import now

from bravado.exception import HTTPUnauthorized, HTTPForbidden
from esi.models import Token

from eveuniverse.models import EveEntity, EveSolarSystem, EveType

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .app_settings import MEMBERAUDIT_LOCATION_STALE_HOURS
from .providers import esi
from .utils import LoggerAddTag, make_logger_prefix


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class LocationManager(models.Manager):
    """Manager for Location model

    We recommend preferring the "async" variants, because they  include protection
    against exceeding the ESI error limit due to characters no longer having access
    to structures within their assets, contracts, etc.

    The async methods will first create an empty location and then try to
    update that empty location asynchronously from ESI.
    Updates might be delayed if the error limit is reached.

    The async method can also be used safely in mass updates, where the same
    unauthorized update might be requested multiple times.
    Additional requests for the same location will be ignored within a grace period.
    """

    _STATION_ID_START = 60000000
    _STATION_ID_END = 69999999
    _UPDATE_EMPTY_GRACE_MINUTES = 5

    def get_or_create_esi(
        self, id: int, token: Token, add_unknown: bool = True
    ) -> Tuple[models.Model, bool]:
        """gets or creates location object with data fetched from ESI

        Stale locations will always be updated.
        Empty locations will always be updated after grace period as passed
        """
        return self._get_or_create_esi(
            id=id, token=token, add_unknown=add_unknown, update_async=False
        )

    def get_or_create_esi_async(
        self, id: int, token: Token, add_unknown: bool = True
    ) -> Tuple[models.Model, bool]:
        """gets or creates location object with data fetched from ESI asynchronous"""
        return self._get_or_create_esi(
            id=id, token=token, add_unknown=add_unknown, update_async=True
        )

    def _get_or_create_esi(
        self, id: int, token: Token, add_unknown: bool = True, update_async: bool = True
    ) -> Tuple[models.Model, bool]:
        id = int(id)
        empty_threshold = now() - dt.timedelta(minutes=self._UPDATE_EMPTY_GRACE_MINUTES)
        stale_threshold = now() - dt.timedelta(hours=MEMBERAUDIT_LOCATION_STALE_HOURS)
        try:
            location = (
                self.exclude(
                    eve_type__isnull=True,
                    eve_solar_system__isnull=True,
                    updated_at__lt=empty_threshold,
                )
                .exclude(updated_at__lt=stale_threshold)
                .get(id=id)
            )
            created = False
        except self.model.DoesNotExist:
            if update_async:
                location, created = self.update_or_create_esi_async(
                    id=id, token=token, add_unknown=add_unknown
                )
            else:
                location, created = self.update_or_create_esi(
                    id=id, token=token, add_unknown=add_unknown
                )

        return location, created

    def update_or_create_esi_async(
        self, id: int, token: Token, add_unknown: bool = True
    ) -> Tuple[models.Model, bool]:
        """updates or creates location object with data fetched from ESI asynchronous"""
        from .tasks import update_location_esi as task_update_location_esi

        id = int(id)
        location, created = self.get_or_create(id=id)
        task_update_location_esi.delay(id=id, token_pk=token.pk)
        return location, created

    def update_or_create_esi(
        self, id: int, token: Token, add_unknown: bool = True
    ) -> Tuple[models.Model, bool]:
        """updates or creates location object with data fetched from ESI synchronous

        The preferred method to use is: `update_or_create_esi_async()`,
        since it protects against exceeding the ESI error limit and which can happen
        a lot due to users not having authorization to access a structure.
        """
        id = int(id)
        add_prefix = make_logger_prefix(id)
        if self._STATION_ID_START <= id <= self._STATION_ID_END:
            logger.info(add_prefix("Fetching station from ESI"))
            station = esi.client.Universe.get_universe_stations_station_id(
                station_id=id
            ).results()
            if station.get("system_id"):
                eve_solar_system, _ = EveSolarSystem.objects.get_or_create_esi(
                    id=station.get("system_id")
                )
            else:
                eve_solar_system = None

            if station.get("type_id"):
                eve_type, _ = EveType.objects.get_or_create_esi(
                    id=station.get("type_id")
                )
            else:
                eve_type = None

            if station.get("owner"):
                owner, _ = EveEntity.objects.get_or_create_esi(id=station.get("owner"))
            else:
                owner = None

            location, created = self.update_or_create(
                id=id,
                defaults={
                    "name": station.get("name", ""),
                    "eve_solar_system": eve_solar_system,
                    "eve_type": eve_type,
                    "owner": owner,
                },
            )

        else:
            try:
                structure = esi.client.Universe.get_universe_structures_structure_id(
                    structure_id=id, token=token.valid_access_token()
                ).results()
            except (HTTPUnauthorized, HTTPForbidden) as ex:
                logger.warn(add_prefix("No access to this structure"), exc_info=True)
                if add_unknown:
                    location, created = self.get_or_create(id=id)
                else:
                    raise ex

            else:
                if structure.get("solar_system_id"):
                    eve_solar_system, _ = EveSolarSystem.objects.get_or_create_esi(
                        id=structure.get("solar_system_id")
                    )
                else:
                    eve_solar_system = None

                if structure.get("type_id"):
                    eve_type, _ = EveType.objects.get_or_create_esi(
                        id=structure.get("type_id")
                    )
                else:
                    eve_type = None

                if structure.get("owner_id"):
                    owner, _ = EveEntity.objects.get_or_create_esi(
                        id=structure.get("owner_id")
                    )
                else:
                    owner = None

                location, created = self.update_or_create(
                    id=id,
                    defaults={
                        "name": structure.get("name", ""),
                        "eve_solar_system": eve_solar_system,
                        "eve_type": eve_type,
                        "owner": owner,
                    },
                )

        return location, created


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
