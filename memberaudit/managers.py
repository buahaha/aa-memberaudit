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
    _STATION_ID_START = 60000000
    _STATION_ID_END = 69999999

    def get_or_create_esi(
        self, id: int, token: Token, add_unknown: bool = True
    ) -> Tuple[models.Model, bool]:
        """gets or creates location object with data fetched from ESI

        Empty and stale locations will always be updated.
        """
        id = int(id)
        stale_threshold = now() - dt.timedelta(hours=MEMBERAUDIT_LOCATION_STALE_HOURS)
        try:
            location = (
                self.exclude(eve_type__isnull=True, eve_solar_system__isnull=True)
                .exclude(updated_at__lt=stale_threshold)
                .get(id=id)
            )
            created = False
        except self.model.DoesNotExist:
            location, created = self.update_or_create_esi(
                id=id, token=token, add_unknown=add_unknown
            )

        return location, created

    def update_or_create_esi(
        self, id: int, token: Token, add_unknown: bool = True
    ) -> Tuple[models.Model, bool]:
        """updates or creates location object with data fetched from ESI"""
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
