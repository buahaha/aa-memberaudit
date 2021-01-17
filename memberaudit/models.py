import datetime as dt
import hashlib
import json
import os
from typing import Any, Optional

from bravado.exception import HTTPInternalServerError

from django.contrib.auth.models import User, Permission
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils.functional import cached_property
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from esi.models import Token
from esi.errors import TokenError

from eveuniverse.models import (
    EveAncestry,
    EveBloodline,
    EveEntity,
    EveFaction,
    EveRace,
    EveSolarSystem,
    EveType,
)

from allianceauth.eveonline.evelinks import dotlan, evewho
from allianceauth.authentication.models import CharacterOwnership
from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .app_settings import (
    MEMBERAUDIT_MAX_MAILS,
    MEMBERAUDIT_DEVELOPER_MODE,
    MEMBERAUDIT_UPDATE_STALE_RING_1,
    MEMBERAUDIT_UPDATE_STALE_RING_2,
    MEMBERAUDIT_UPDATE_STALE_RING_3,
    MEMBERAUDIT_UPDATE_STALE_OFFSET,
    MEMBERAUDIT_DATA_RETENTION_LIMIT,
)
from .core.xml_converter import eve_xml_to_html
from .decorators import fetch_token_for_character
from .helpers import (
    get_or_create_esi_or_none,
    get_or_create_or_none,
    users_with_permission,
)
from .managers import (
    CharacterAssetManager,
    CharacterContactLabelManager,
    CharacterContactManager,
    CharacterContractManager,
    CharacterContractBidManager,
    CharacterContractItemManager,
    CharacterCorporationHistoryManager,
    CharacterImplantManager,
    CharacterLoyaltyEntryManager,
    CharacterJumpCloneManager,
    CharacterMailLabelManager,
    CharacterMailManager,
    CharacterManager,
    CharacterSkillManager,
    CharacterSkillqueueEntryManager,
    CharacterSkillSetCheckManager,
    CharacterUpdateStatusManager,
    CharacterWalletJournalEntryManager,
    EveShipTypeManger,
    EveSkillTypeManger,
    LocationManager,
    MailEntityManager,
    SkillSetManager,
)
from .providers import esi
from .utils import LoggerAddTag, chunks, datetime_round_hour

logger = LoggerAddTag(get_extension_logger(__name__), __title__)

CURRENCY_MAX_DIGITS = 17
CURRENCY_MAX_DECIMALS = 2
NAMES_MAX_LENGTH = 100


def data_retention_cutoff() -> Optional[dt.datetime]:
    """returns cutoff datetime for data retention of None if unlimited"""
    if MEMBERAUDIT_DATA_RETENTION_LIMIT is None:
        return None
    else:
        return datetime_round_hour(
            now() - dt.timedelta(days=MEMBERAUDIT_DATA_RETENTION_LIMIT)
        )


def accessible_users(user: User) -> models.QuerySet:
    """users that the given user can access"""
    if user.has_perm("memberaudit.view_everything"):
        users_qs = General.users_with_basic_access()
    else:
        users_qs = User.objects.none()
        if (
            user.has_perm("memberaudit.view_same_alliance")
            and user.profile.main_character.alliance_id
        ):
            users_qs = (
                General.users_with_basic_access()
                .select_related("profile__main_character")
                .filter(
                    profile__main_character__alliance_id=user.profile.main_character.alliance_id
                )
            )
        elif user.has_perm("memberaudit.view_same_corporation"):
            users_qs = (
                General.users_with_basic_access()
                .select_related("profile__main_character")
                .filter(
                    profile__main_character__corporation_id=user.profile.main_character.corporation_id
                )
            )

    return users_qs


class EveShipType(EveType):
    """Subset of EveType for all ship types"""

    class Meta:
        proxy = True

    objects = EveShipTypeManger()


class EveSkillType(EveType):
    """Subset of EveType for all skill types"""

    class Meta:
        proxy = True

    objects = EveSkillTypeManger()


class General(models.Model):
    """Meta model for app permissions"""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (
            (
                "basic_access",
                "Can access this app, register, and view own characters",
            ),
            ("share_characters", "Can share his/her characters"),
            ("finder_access", "Can access character finder feature"),
            ("reports_access", "Can access reports feature"),
            ("characters_access", "Can view characters owned by others"),
            ("view_shared_characters", "Can view shared characters"),
            ("view_same_corporation", "Can view corporation characters"),
            ("view_same_alliance", "Can view alliance characters"),
            ("view_everything", "Can view all characters"),
        )

    @classmethod
    def basic_permission(cls):
        """return basic permission needed to use this app"""
        return Permission.objects.select_related("content_type").get(
            content_type__app_label=cls._meta.app_label, codename="basic_access"
        )

    @classmethod
    def users_with_basic_access(cls) -> models.QuerySet:
        return users_with_permission(cls.basic_permission())


class Location(models.Model):
    """An Eve Online location: Station or Upwell Structure or Solar System"""

    _SOLAR_SYSTEM_ID_START = 30_000_000
    _SOLAR_SYSTEM_ID_END = 33_000_000
    _STATION_ID_START = 60_000_000
    _STATION_ID_END = 64_000_000
    _STRUCTURE_ID_START = 1_000_000_000_000

    id = models.PositiveBigIntegerField(
        primary_key=True,
        help_text=(
            "Eve Online location ID, "
            "either item ID for stations or structure ID for structures"
        ),
    )
    name = models.CharField(
        max_length=NAMES_MAX_LENGTH,
        help_text="In-game name of this station or structure",
    )
    eve_solar_system = models.ForeignKey(
        EveSolarSystem,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        related_name="+",
    )
    eve_type = models.ForeignKey(
        EveType,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        related_name="+",
    )
    owner = models.ForeignKey(
        EveEntity,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        related_name="+",
        help_text="corporation this station or structure belongs to",
    )
    updated_at = models.DateTimeField(auto_now=True)

    objects = LocationManager()

    class Meta:
        default_permissions = ()

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return "{}(id={}, name='{}')".format(
            self.__class__.__name__, self.id, self.name
        )

    @property
    def name_plus(self) -> str:
        """return the actual name or 'Unknown location' for empty locations"""
        if self.is_empty:
            return f"Unknown location #{self.id}"

        return self.name

    @property
    def is_empty(self) -> bool:
        return not self.eve_solar_system and not self.eve_type

    @property
    def solar_system_url(self) -> str:
        """returns dotlan URL for this solar system"""
        try:
            return dotlan.solar_system_url(self.eve_solar_system.name)
        except AttributeError:
            return ""

    @property
    def is_solar_system(self) -> bool:
        return self.is_solar_system_id(self.id)

    @property
    def is_station(self) -> bool:
        return self.is_station_id(self.id)

    @property
    def is_structure(self) -> bool:
        return self.is_structure_id(self.id)

    @classmethod
    def is_solar_system_id(cls, location_id: int) -> bool:
        return cls._SOLAR_SYSTEM_ID_START <= location_id <= cls._SOLAR_SYSTEM_ID_END

    @classmethod
    def is_station_id(cls, location_id: int) -> bool:
        return cls._STATION_ID_START <= location_id <= cls._STATION_ID_END

    @classmethod
    def is_structure_id(cls, location_id: int) -> bool:
        return location_id >= cls._STRUCTURE_ID_START


class Character(models.Model):
    """A character synced by this app

    This is the head model for all characters
    """

    class UpdateSection(models.TextChoices):
        ASSETS = "assets", _("assets")
        CHARACTER_DETAILS = "character_details", ("character details")
        CONTACTS = "contacts", _("contacts")
        CONTRACTS = "contracts", _("contracts")
        CORPORATION_HISTORY = "corporation_history", _("corporation history")
        IMPLANTS = "implants", _("implants")
        JUMP_CLONES = "jump_clones", _("jump clones")
        LOCATION = "location", _("location")
        LOYALTY = "loyalty", _("loyalty")
        MAILS = "mails", _("mails")
        ONLINE_STATUS = "online_status", _("online status")
        SKILLS = "skills", _("skills")
        SKILL_QUEUE = "skill_queue", _("skill queue")
        SKILL_SETS = "skill_sets", _("skill sets")
        WALLET_BALLANCE = "wallet_balance", _("wallet balance")
        WALLET_JOURNAL = "wallet_journal", _("wallet journal")

        @classmethod
        def method_name(cls, section: str) -> str:
            """returns name of update method corresponding with the given section

            Raises:
            - ValueError if secton is invalid
            """
            if section not in cls.values:
                raise ValueError(f"Unknown section: {section}")

            return f"update_{section}"

        @classmethod
        def display_name(cls, section: str) -> str:
            """returns display name of given section

            Raises:
            - ValueError if secton is invalid
            """
            for short_name, long_name in cls.choices:
                if short_name == section:
                    return long_name

            raise ValueError(f"Unknown section: {section}")

    UPDATE_SECTION_RINGS_MAP = {
        UpdateSection.ASSETS: 3,
        UpdateSection.CHARACTER_DETAILS: 2,
        UpdateSection.CONTACTS: 2,
        UpdateSection.CONTRACTS: 2,
        UpdateSection.CORPORATION_HISTORY: 2,
        UpdateSection.SKILL_SETS: 2,
        UpdateSection.IMPLANTS: 2,
        UpdateSection.JUMP_CLONES: 2,
        UpdateSection.LOCATION: 1,
        UpdateSection.LOYALTY: 2,
        UpdateSection.MAILS: 2,
        UpdateSection.ONLINE_STATUS: 1,
        UpdateSection.SKILLS: 2,
        UpdateSection.SKILL_QUEUE: 1,
        UpdateSection.WALLET_BALLANCE: 2,
        UpdateSection.WALLET_JOURNAL: 2,
    }

    character_ownership = models.OneToOneField(
        CharacterOwnership,
        related_name="memberaudit_character",
        on_delete=models.CASCADE,
        primary_key=True,
        help_text="ownership of this character on Auth",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    is_shared = models.BooleanField(
        default=False,
        help_text="Shared characters can be viewed by recruiters",
    )
    mailing_lists = models.ManyToManyField("MailEntity", related_name="characters")

    objects = CharacterManager()

    class Meta:
        default_permissions = ()

    def __str__(self) -> str:
        return f"{self.character_ownership.character.character_name} (PK:{self.pk})"

    def __repr__(self) -> str:
        return (
            f"Character(pk={self.pk}, "
            f"character_ownership='{self.character_ownership}')"
        )

    @cached_property
    def is_main(self) -> bool:
        """returns True if this character is a main character, else False"""
        try:
            return (
                self.character_ownership.user.profile.main_character.character_id
                == self.character_ownership.character.character_id
            )
        except AttributeError:
            return False

    def user_is_owner(self, user: User) -> bool:
        """Return True if the given user is owner of this character"""
        return self.character_ownership.user == user

    def user_has_access(self, user: User) -> bool:
        """Returns True if given user has permission to access this character
        in the character viewer
        """
        if self.character_ownership.user == user:
            return True
        elif user.has_perm("memberaudit.view_shared_characters") and self.is_shared:
            return True
        elif user.has_perm("memberaudit.characters_access"):
            if user.has_perm("memberaudit.view_everything"):
                return True
            elif (
                user.has_perm("memberaudit.view_same_alliance")
                and user.profile.main_character.alliance_id
                and user.profile.main_character.alliance_id
                == self.character_ownership.user.profile.main_character.alliance_id
            ):
                return True
            elif (
                user.has_perm("memberaudit.view_same_corporation")
                and user.profile.main_character.corporation_id
                == self.character_ownership.user.profile.main_character.corporation_id
            ):
                return True

        return False

    def is_update_status_ok(self) -> bool:
        """returns status of last update

        Returns:
        - True: If update was complete and without errors
        - False if there where any errors
        - None: if last update is incomplete
        """
        errors_count = self.update_status_set.filter(is_success=False).count()
        ok_count = self.update_status_set.filter(is_success=True).count()
        if errors_count > 0:
            return False
        elif ok_count == len(Character.UpdateSection.choices):
            return True
        else:
            return None

    @classmethod
    def update_section_time_until_stale(cls, section: str) -> dt.timedelta:
        """time until given update section is considered stale"""
        ring = cls.UPDATE_SECTION_RINGS_MAP[section]
        if ring == 1:
            minutes = MEMBERAUDIT_UPDATE_STALE_RING_1
        elif ring == 2:
            minutes = MEMBERAUDIT_UPDATE_STALE_RING_2
        else:
            minutes = MEMBERAUDIT_UPDATE_STALE_RING_3

        # setting reduced by offset to ensure all sections are stale when
        # periodic task starts
        return dt.timedelta(minutes=minutes - MEMBERAUDIT_UPDATE_STALE_OFFSET)

    @classmethod
    def sections_in_ring(cls, ring: int) -> set:
        """returns set of sections for given ring"""
        return {
            section
            for section, ring_num in cls.UPDATE_SECTION_RINGS_MAP.items()
            if ring_num == ring
        }

    def is_update_section_stale(self, section: str) -> bool:
        """returns True if the give update section is stale, else False"""
        try:
            update_status = self.update_status_set.get(
                section=section,
                is_success=True,
                started_at__isnull=False,
                finished_at__isnull=False,
            )
        except (CharacterUpdateStatus.DoesNotExist, ObjectDoesNotExist, AttributeError):
            return True

        deadline = now() - self.update_section_time_until_stale(section)
        return update_status.started_at < deadline

    def has_section_changed(
        self, section: str, content: str, hash_num: int = 1
    ) -> bool:
        """returns False if the content hash for this section has not changed, else True"""
        try:
            section = self.update_status_set.get(section=section)
        except CharacterUpdateStatus.DoesNotExist:
            return True
        else:
            return section.has_changed(content=content, hash_num=hash_num)

    def update_section_content_hash(
        self, section: str, content: str, hash_num: int = 1
    ) -> bool:
        try:
            section = self.update_status_set.get(section=section)
        except CharacterUpdateStatus.DoesNotExist:
            section, _ = CharacterUpdateStatus.objects.get_or_create(
                character=self, section=section
            )

        section.update_content_hash(content=content, hash_num=hash_num)

    def reset_update_section(
        self, section: str, root_task_id: str = None, parent_task_id: str = None
    ) -> "CharacterUpdateStatus":
        """resets status of given update section and returns it"""
        try:
            section = self.update_status_set.get(section=section)
        except CharacterUpdateStatus.DoesNotExist:
            section, _ = CharacterUpdateStatus.objects.get_or_create(
                character=self, section=section
            )

        section.reset(root_task_id, parent_task_id)
        return section

    def is_section_updating(self, section: str) -> bool:
        """returns True if section is currently updating, or does not exist, else False"""
        try:
            section = self.update_status_set.get(section=section)
        except CharacterUpdateStatus.DoesNotExist:
            return True

        return section.is_updating

    def _preload_all_locations(self, token: Token, incoming_ids: set) -> list:
        """loads location objects specified by given set

        returns list of existing location IDs after preload
        """
        existing_ids = set(Location.objects.values_list("id", flat=True))
        missing_ids = incoming_ids.difference(existing_ids)
        if missing_ids:
            logger.info(
                "%s: Loading %s missing locations from ESI", self, len(missing_ids)
            )
            for location_id in missing_ids:
                try:
                    Location.objects.get_or_create_esi_async(
                        id=location_id, token=token
                    )
                except ValueError:
                    pass
                else:
                    existing_ids.add(location_id)

        return existing_ids

    def fetch_token(self, scopes=None) -> Token:
        """returns valid token for character

        Args:
        - scopes: Optionally provide the required scopes.
        Otherwise will use all scopes defined for this character.

        Exceptions:
        - TokenError: If no valid token can be found
        """
        token = (
            Token.objects.prefetch_related("scopes")
            .filter(
                user=self.character_ownership.user,
                character_id=self.character_ownership.character.character_id,
            )
            .require_scopes(scopes if scopes else self.get_esi_scopes())
            .require_valid()
            .first()
        )
        if not token:
            raise TokenError("Could not find a matching token")

        return token

    @fetch_token_for_character("esi-assets.read_assets.v1")
    def assets_build_list_from_esi(
        self, token: Token, force_update=False
    ) -> Optional[list]:
        """fetches assets from ESI and preloads related objects from ESI

        returns the asset_list or None if no update is required
        """
        logger.info("%s: Fetching assets from ESI", self)
        asset_list = esi.client.Assets.get_characters_character_id_assets(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        assets_flat = {int(x["item_id"]): x for x in asset_list}

        logger.info("%s: Fetching asset names from ESI", self)
        names = list()
        for asset_ids_chunk in chunks(list(assets_flat.keys()), 999):
            names += esi.client.Assets.post_characters_character_id_assets_names(
                character_id=self.character_ownership.character.character_id,
                token=token.valid_access_token(),
                item_ids=asset_ids_chunk,
            ).results()

        asset_names = {
            int(x["item_id"]): x["name"] for x in names if x["name"] != "None"
        }
        for item_id in assets_flat.keys():
            assets_flat[item_id]["name"] = asset_names.get(item_id, "")

        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(assets_flat, "asset_list")

        new_asset_list = list(assets_flat.values())
        if force_update or self.has_section_changed(
            section=Character.UpdateSection.ASSETS, content=new_asset_list
        ):
            self.update_section_content_hash(
                section=Character.UpdateSection.ASSETS, content=new_asset_list
            )
            return new_asset_list
        else:
            logger.info("%s: Assets did not change", self)
            return None

    @fetch_token_for_character("esi-universe.read_structures.v1")
    def assets_preload_objects(self, token: Token, asset_list: list) -> None:
        """preloads objects needed to build the asset tree"""
        logger.info("%s: Preloading objects for asset tree", self)
        required_ids = {x["type_id"] for x in asset_list if "type_id" in x}
        existing_ids = set(EveType.objects.values_list("id", flat=True))
        missing_ids = required_ids.difference(existing_ids)
        if missing_ids:
            logger.info("%s: Loading %s missing types from ESI", self, len(missing_ids))
            EveType.objects.bulk_get_or_create_esi(ids=missing_ids)

        assets_flat = {int(x["item_id"]): x for x in asset_list}
        incoming_location_ids = {
            x["location_id"]
            for x in assets_flat.values()
            if "location_id" in x and x["location_id"] not in assets_flat
        }
        self._preload_all_locations(token=token, incoming_ids=incoming_location_ids)

    def update_character_details(self, force_update: bool = False):
        """syncs the character details for the given character"""
        logger.info("%s: Fetching character details from ESI", self)
        details = esi.client.Character.get_characters_character_id(
            character_id=self.character_ownership.character.character_id,
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(details, "character_details")

        if force_update or self.has_section_changed(
            section=self.UpdateSection.CHARACTER_DETAILS, content=details
        ):
            description = (
                details.get("description", "") if details.get("description") else ""
            )
            if description:
                eve_xml_to_html(description)  # resolve names early

            gender = (
                CharacterDetails.GENDER_MALE
                if details.get("gender") == "male"
                else CharacterDetails.GENDER_FEMALE
            )

            # Workaround because of ESI issue #1264
            # TODO: Remove once issue is fixed
            try:
                eve_ancestry = get_or_create_esi_or_none(
                    "ancestry_id", details, EveAncestry
                )
            except HTTPInternalServerError:
                eve_ancestry = None

            CharacterDetails.objects.update_or_create(
                character=self,
                defaults={
                    "alliance": get_or_create_or_none(
                        "alliance_id", details, EveEntity
                    ),
                    "birthday": details.get("birthday"),
                    "eve_ancestry": eve_ancestry,
                    "eve_bloodline": get_or_create_esi_or_none(
                        "bloodline_id", details, EveBloodline
                    ),
                    "eve_faction": get_or_create_esi_or_none(
                        "faction_id", details, EveFaction
                    ),
                    "eve_race": get_or_create_esi_or_none("race_id", details, EveRace),
                    "corporation": get_or_create_or_none(
                        "corporation_id", details, EveEntity
                    ),
                    "description": description,
                    "gender": gender,
                    "name": details.get("name", ""),
                    "security_status": details.get("security_status"),
                    "title": details.get("title", "") if details.get("title") else "",
                },
            )
            EveEntity.objects.bulk_update_new_esi()
            self.update_section_content_hash(
                section=self.UpdateSection.CHARACTER_DETAILS, content=details
            )

        else:
            logger.info("%s: Character details have not changed", self)

    @fetch_token_for_character("esi-characters.read_contacts.v1")
    def update_contact_labels(self, token: Token, force_update: bool = False):
        logger.info("%s: Fetching contact labels from ESI", self)
        labels = esi.client.Contacts.get_characters_character_id_contacts_labels(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(labels, "contact_labels")
        if force_update or self.has_section_changed(
            section=self.UpdateSection.CONTACTS, content=labels, hash_num=2
        ):
            self.contact_labels.update_for_character(self, labels)
            self.update_section_content_hash(
                section=self.UpdateSection.CONTACTS, content=labels, hash_num=2
            )
        else:
            logger.info("%s: Contact labels have not changed", self)

    @fetch_token_for_character("esi-characters.read_contacts.v1")
    def update_contacts(self, token: Token, force_update: bool = False):
        logger.info("%s: Fetching contacts from ESI", self)
        contacts_data = esi.client.Contacts.get_characters_character_id_contacts(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(contacts_data, "contacts")

        if contacts_data:
            contacts_list = {int(x["contact_id"]): x for x in contacts_data}
        else:
            contacts_list = dict()

        if force_update or self.has_section_changed(
            section=self.UpdateSection.CONTACTS, content=contacts_list
        ):
            self.contacts.update_for_character(self, contacts_list)
            self.update_section_content_hash(
                section=self.UpdateSection.CONTACTS, content=contacts_list
            )

        else:
            logger.info("%s: Contacts have not changed", self)

    @fetch_token_for_character("esi-contracts.read_character_contracts.v1")
    def update_contract_headers(self, token: Token, force_update: bool = False):
        """update the character's contract headers"""

        contracts_list = self._fetch_contracts_from_esi(token)
        if not contracts_list:
            logger.info("%s: No contracts received from ESI", self)

        cutoff_datetime = data_retention_cutoff()
        if cutoff_datetime:
            self.contracts.filter(date_expired__lt=cutoff_datetime).delete()

        if force_update or self.has_section_changed(
            section=self.UpdateSection.CONTRACTS, content=contracts_list
        ):
            existing_ids = set(self.contracts.values_list("contract_id", flat=True))
            incoming_location_ids = {
                obj["start_location_id"]
                for contract_id, obj in contracts_list.items()
                if contract_id not in existing_ids
            }
            incoming_location_ids |= {
                obj["end_location_id"] for obj in contracts_list.values()
            }
            self._preload_all_locations(token=token, incoming_ids=incoming_location_ids)
            self.contracts.update_for_character(self, contracts_list)
            self.update_section_content_hash(
                section=self.UpdateSection.CONTRACTS, content=contracts_list
            )

        else:
            logger.info("%s: Contracts have not changed", self)

    def _fetch_contracts_from_esi(self, token) -> dict:
        logger.info("%s: Fetching contracts from ESI", self)
        contracts_data = esi.client.Contracts.get_characters_character_id_contracts(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(contracts_data, "contracts")

        cutoff_datetime = data_retention_cutoff()
        contracts_list = {
            obj.get("contract_id"): obj
            for obj in contracts_data
            if cutoff_datetime is None or obj.get("date_expired") > cutoff_datetime
        }
        return contracts_list

    @fetch_token_for_character("esi-contracts.read_character_contracts.v1")
    def update_contract_items(self, token: Token, contract: "CharacterContract"):
        """update the character's contract details"""
        if contract.contract_type not in [
            CharacterContract.TYPE_ITEM_EXCHANGE,
            CharacterContract.TYPE_AUCTION,
        ]:
            logger.warning(
                "%s, %s: Can not update items. Wrong contract type.",
                self,
                contract.contract_id,
            )
            return

        logger.info(
            "%s, %s: Fetching contract items from ESI", self, contract.contract_id
        )
        my_esi = esi.client.Contracts
        items_data = my_esi.get_characters_character_id_contracts_contract_id_items(
            character_id=self.character_ownership.character.character_id,
            contract_id=contract.contract_id,
            token=token.valid_access_token(),
        ).results()
        contract.items.update_for_contract(contract, items_data)

    @fetch_token_for_character("esi-contracts.read_character_contracts.v1")
    def update_contract_bids(self, token: Token, contract: "CharacterContract"):
        """update the character's contract details"""
        if contract.contract_type != CharacterContract.TYPE_AUCTION:
            logger.warning(
                "%s, %s: Can not update bids. Wrong contract type.",
                self,
                contract.contract_id,
            )
            return

        logger.info(
            "%s, %s: Fetching contract bids from ESI", self, contract.contract_id
        )
        bids_data = (
            esi.client.Contracts.get_characters_character_id_contracts_contract_id_bids(
                character_id=self.character_ownership.character.character_id,
                contract_id=contract.contract_id,
                token=token.valid_access_token(),
            ).results()
        )
        bids_list = {int(x["bid_id"]): x for x in bids_data if "bid_id" in x}
        contract.bids.update_for_contract(contract, bids_list)
        EveEntity.objects.bulk_update_new_esi()

    def update_corporation_history(self, force_update: bool = False):
        """syncs the character's corporation history"""
        logger.info("%s: Fetching corporation history from ESI", self)
        history = esi.client.Character.get_characters_character_id_corporationhistory(
            character_id=self.character_ownership.character.character_id,
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(history, "corporation_history")
        if force_update or self.has_section_changed(
            section=self.UpdateSection.CORPORATION_HISTORY, content=history
        ):
            self.corporation_history.update_for_character(self, history)
            self.update_section_content_hash(
                section=self.UpdateSection.CORPORATION_HISTORY, content=history
            )
        else:
            logger.info("%s: Corporation history has not changed", self)

    @fetch_token_for_character("esi-clones.read_implants.v1")
    def update_implants(self, token: Token, force_update: bool = False):
        """update the character's implants"""
        logger.info("%s: Fetching implants from ESI", self)
        implants_data = esi.client.Clones.get_characters_character_id_implants(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(implants_data, "implants")
        if force_update or self.has_section_changed(
            section=self.UpdateSection.IMPLANTS, content=implants_data
        ):
            if implants_data:
                EveType.objects.bulk_get_or_create_esi(ids=implants_data)
            self.implants.update_for_character(self, implants_data)
            self.update_section_content_hash(
                section=self.UpdateSection.IMPLANTS, content=implants_data
            )
        else:
            logger.info("%s: Implants have not changed", self)

    @fetch_token_for_character(
        ["esi-location.read_location.v1", "esi-universe.read_structures.v1"]
    )
    def update_location(self, token: Token):
        """update the location for the given character"""
        logger.info("%s: Fetching location from ESI", self)
        location_info = esi.client.Location.get_characters_character_id_location(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        eve_solar_system, _ = EveSolarSystem.objects.get_or_create_esi(
            id=location_info.get("solar_system_id")
        )
        if location_info.get("station_id"):
            location, _ = Location.objects.get_or_create_esi_async(
                id=location_info.get("station_id"), token=token
            )
        elif location_info.get("structure_id"):
            location, _ = Location.objects.get_or_create_esi_async(
                id=location_info.get("structure_id"), token=token
            )
        else:
            location = None

        if eve_solar_system:
            CharacterLocation.objects.update_or_create(
                character=self,
                defaults={
                    "eve_solar_system": eve_solar_system,
                    "location": location,
                },
            )

    @fetch_token_for_character("esi-characters.read_loyalty.v1")
    def update_loyalty(self, token: Token, force_update: bool = False):
        """syncs the character's loyalty entries"""
        logger.info("%s: Fetching loyalty entries from ESI", self)
        loyalty_entries = esi.client.Loyalty.get_characters_character_id_loyalty_points(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(loyalty_entries, "loyalty")

        if force_update or self.has_section_changed(
            section=self.UpdateSection.LOYALTY, content=loyalty_entries
        ):
            self.loyalty_entries.update_for_character(self, loyalty_entries)
            self.update_section_content_hash(
                section=self.UpdateSection.LOYALTY, content=loyalty_entries
            )
            EveEntity.objects.bulk_update_new_esi()

        else:
            logger.info("%s: Loyalty entries have not changed", self)

    @fetch_token_for_character(
        ["esi-clones.read_clones.v1", "esi-universe.read_structures.v1"]
    )
    def update_jump_clones(self, token: Token, force_update: bool = False):
        """updates the character's jump clones"""
        logger.info("%s: Fetching jump clones from ESI", self)
        jump_clones_info = esi.client.Clones.get_characters_character_id_clones(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(jump_clones_info, "jump_clones")

        if force_update or self.has_section_changed(
            section=self.UpdateSection.JUMP_CLONES, content=jump_clones_info
        ):
            jump_clones_list = jump_clones_info.get("jump_clones")
            # fetch related objects ahead of transaction
            if jump_clones_list:
                incoming_location_ids = {
                    record["location_id"]
                    for record in jump_clones_info["jump_clones"]
                    if "location_id" in record
                }
                self._preload_all_locations(token, incoming_location_ids)

                for jump_clone_info in jump_clones_list:
                    if jump_clone_info.get("implants"):
                        EveType.objects.bulk_get_or_create_esi(
                            ids=jump_clone_info.get("implants", [])
                        )

            self.jump_clones.update_for_character(self, jump_clones_list)
            self.update_section_content_hash(
                section=self.UpdateSection.JUMP_CLONES, content=jump_clones_info
            )

        else:
            logger.info("%s: Jump clones have not changed", self)

    @fetch_token_for_character("esi-mail.read_mail.v1")
    def update_mailing_lists(self, token: Token, force_update: bool = False):
        """update mailing lists with input from given character

        Note: Obsolete mailing lists must not be removed,
        since they might still be referenced by older mails
        """
        logger.info("%s: Fetching mailing lists from ESI", self)
        mailing_lists_raw = esi.client.Mail.get_characters_character_id_mail_lists(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if mailing_lists_raw:
            mailing_lists = {
                obj["mailing_list_id"]: obj
                for obj in mailing_lists_raw
                if "mailing_list_id" in obj
            }
        else:
            mailing_lists = dict()

        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(mailing_lists, "mailing_lists")

        # TODO: replace with bulk methods to optimize

        incoming_ids = set(mailing_lists.keys())
        # existing_ids = set(self.mailing_lists.values_list("list_id", flat=True))
        if not incoming_ids:
            logger.info("%s: No new mailing lists", self)
            return

        if force_update or self.has_section_changed(
            section=self.UpdateSection.MAILS, content=mailing_lists, hash_num=2
        ):
            new_mailing_lists = self.mailing_lists.update_for_character(
                character=self, mailing_lists=mailing_lists
            )
            self.mailing_lists.set(new_mailing_lists, clear=True)
            self.update_section_content_hash(
                section=self.UpdateSection.MAILS, content=mailing_lists, hash_num=2
            )

        else:
            logger.info("%s: Mailng lists have not changed", self)

    @fetch_token_for_character("esi-mail.read_mail.v1")
    def update_mail_labels(self, token: Token, force_update: bool = False):
        """update the mail lables for the given character"""
        mail_labels_list = self._fetch_mail_labels_from_esi(token)
        if not mail_labels_list:
            logger.info("%s: No mail labels", self)
            return

        if force_update or self.has_section_changed(
            section=self.UpdateSection.MAILS, content=mail_labels_list, hash_num=3
        ):
            self.mail_labels.update_for_character(self, mail_labels_list)
            self.update_section_content_hash(
                section=self.UpdateSection.MAILS, content=mail_labels_list, hash_num=3
            )

        else:
            logger.info("%s: Mail labels have not changed", self)

    def _fetch_mail_labels_from_esi(self, token) -> dict:
        logger.info("%s: Fetching mail labels from ESI", self)
        mail_labels_info = esi.client.Mail.get_characters_character_id_mail_labels(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(mail_labels_info, "mail_labels")

        if mail_labels_info.get("total_unread_count"):
            CharacterMailUnreadCount.objects.update_or_create(
                character=self,
                defaults={"total": mail_labels_info.get("total_unread_count")},
            )

        mail_labels = mail_labels_info.get("labels")
        if mail_labels:
            return {obj["label_id"]: obj for obj in mail_labels if "label_id" in obj}
        else:
            return dict()

    @fetch_token_for_character("esi-mail.read_mail.v1")
    def update_mail_headers(self, token: Token, force_update: bool = False):
        mail_headers = self._fetch_mail_headers(token)
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(mail_headers, "mail_headers")
        self.mails.update_for_character(
            character=self,
            cutoff_datetime=data_retention_cutoff(),
            mail_headers=mail_headers,
            force_update=force_update,
        )

    def _fetch_mail_headers(self, token) -> dict:
        last_mail_id = None
        mail_headers_all = list()
        page = 1
        while True:
            logger.info("%s: Fetching mail headers from ESI - page %s", self, page)
            mail_headers = esi.client.Mail.get_characters_character_id_mail(
                character_id=self.character_ownership.character.character_id,
                last_mail_id=last_mail_id,
                token=token.valid_access_token(),
            ).results()
            if MEMBERAUDIT_DEVELOPER_MODE:
                self._store_list_to_disk(mail_headers, "mail_headers")

            mail_headers_all += mail_headers
            if len(mail_headers) < 50 or len(mail_headers_all) >= MEMBERAUDIT_MAX_MAILS:
                break
            else:
                last_mail_id = min([x["mail_id"] for x in mail_headers])
                page += 1

        cutoff_datetime = data_retention_cutoff()
        mail_headers_all_2 = {
            obj["mail_id"]: obj
            for obj in mail_headers_all
            if cutoff_datetime is None
            or not obj.get("timestamp")
            or obj.get("timestamp") > cutoff_datetime
        }
        logger.info(
            "%s: Received %s mail headers from ESI", self, len(mail_headers_all_2)
        )
        return mail_headers_all_2

    @staticmethod
    def _headers_list_subset(mail_headers, subset_ids) -> dict:
        return {
            mail_info["mail_id"]: mail_info
            for mail_id, mail_info in mail_headers.items()
            if mail_id in subset_ids
        }

    @fetch_token_for_character("esi-mail.read_mail.v1")
    def update_mail_body(self, token: Token, mail: models.Model) -> None:
        logger.debug("%s: Fetching body from ESI for mail ID %s", self, mail.mail_id)
        mail_body = esi.client.Mail.get_characters_character_id_mail_mail_id(
            character_id=self.character_ownership.character.character_id,
            mail_id=mail.mail_id,
            token=token.valid_access_token(),
        ).result()
        mail.body = mail_body.get("body", "")
        mail.save()
        eve_xml_to_html(mail.body)  # resolve names early
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(mail_body, "mail_body")

    @fetch_token_for_character("esi-location.read_online.v1")
    def update_online_status(self, token):
        """Update the character's online status"""
        logger.info("%s: Fetching online status from ESI", self)
        online_info = esi.client.Location.get_characters_character_id_online(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        CharacterOnlineStatus.objects.update_or_create(
            character=self,
            defaults={
                "last_login": online_info.get("last_login"),
                "last_logout": online_info.get("last_logout"),
                "logins": online_info.get("logins"),
            },
        )

    @fetch_token_for_character("esi-skills.read_skillqueue.v1")
    def update_skill_queue(self, token: Token, force_update: bool = False):
        """update the character's skill queue"""
        logger.info("%s: Fetching skill queue from ESI", self)
        skillqueue = esi.client.Skills.get_characters_character_id_skillqueue(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(skillqueue, "skill_queue")

        if force_update or self.has_section_changed(
            section=self.UpdateSection.SKILL_QUEUE, content=skillqueue
        ):
            self.skillqueue.update_for_character(self, skillqueue)
            self.update_section_content_hash(
                section=self.UpdateSection.SKILL_QUEUE, content=skillqueue
            )

        else:
            logger.info("%s: Skill queue has not changed", self)

    def update_skill_sets(self):
        """Checks if character has the skills needed for skill sets
        and updates results in database
        """
        self.skill_set_checks.update_for_character(self)

    @fetch_token_for_character("esi-skills.read_skills.v1")
    def update_skills(self, token, force_update: bool = False):
        """update the character's skill"""
        skills_list = self._fetch_skills_from_esi(token)
        if force_update or self.has_section_changed(
            section=self.UpdateSection.SKILLS, content=skills_list
        ):
            self._preload_types(skills_list)
            self.skills.update_for_character(self, skills_list)
            self.update_section_content_hash(
                section=self.UpdateSection.SKILLS, content=skills_list
            )

        else:
            logger.info("%s: Skills have not changed", self)

    def _fetch_skills_from_esi(self, token: Token) -> dict:
        logger.info("%s: Fetching skills from ESI", self)
        skills_info = esi.client.Skills.get_characters_character_id_skills(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(skills_info, "skills")

        CharacterSkillpoints.objects.update_or_create(
            character=self,
            defaults={
                "total": skills_info.get("total_sp"),
                "unallocated": skills_info.get("unallocated_sp"),
            },
        )
        if skills_info.get("skills"):
            skills_list = {
                obj["skill_id"]: obj
                for obj in skills_info.get("skills")
                if "skill_id" in obj
            }
        else:
            skills_list = dict()

        return skills_list

    def _preload_types(self, skills_list: dict):
        if skills_list:
            incoming_ids = set(skills_list.keys())
            existing_ids = set(self.skills.values_list("eve_type_id", flat=True))
            new_ids = incoming_ids.difference(existing_ids)
            EveType.objects.bulk_get_or_create_esi(ids=new_ids)

    @fetch_token_for_character("esi-wallet.read_character_wallet.v1")
    def update_wallet_balance(self, token):
        """syncs the character's wallet balance"""
        logger.info("%s: Fetching wallet balance from ESI", self)
        balance = esi.client.Wallet.get_characters_character_id_wallet(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(balance, "balance")

        CharacterWalletBalance.objects.update_or_create(
            character=self, defaults={"total": balance}
        )

    @fetch_token_for_character("esi-wallet.read_character_wallet.v1")
    def update_wallet_journal(self, token):
        """syncs the character's wallet journal

        Note: Does not update unknown EvEntities.
        """
        logger.info("%s: Fetching wallet journal from ESI", self)
        journal = esi.client.Wallet.get_characters_character_id_wallet_journal(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(journal, "wallet_journal")

        self.wallet_journal.update_for_character(self, data_retention_cutoff(), journal)

    def _store_list_to_disk(self, lst: list, name: str):
        """stores the given list as JSON file to disk. For debugging

        Will store under memberaudit_logs/{DATE}/{CHARACTER_PK}_{NAME}.json
        """
        today_str = now().strftime("%Y%m%d")
        now_str = now().strftime("%Y%m%d%H%M")
        path = f"memberaudit_log/{today_str}"
        if not os.path.isdir(path):
            os.makedirs(path)

        fullpath = os.path.join(path, f"character_{self.pk}_{name}_{now_str}.json")
        try:
            with open(fullpath, "w", encoding="utf-8") as f:
                json.dump(lst, f, cls=DjangoJSONEncoder, sort_keys=True, indent=4)

        except OSError:
            pass

    @classmethod
    def get_esi_scopes(cls) -> list:
        return [
            "esi-assets.read_assets.v1",
            "esi-bookmarks.read_character_bookmarks.v1",
            "esi-calendar.read_calendar_events.v1",
            "esi-characters.read_agents_research.v1",
            "esi-characters.read_blueprints.v1",
            "esi-characters.read_contacts.v1",
            "esi-characters.read_fatigue.v1",
            "esi-characters.read_fw_stats.v1",
            "esi-characters.read_loyalty.v1",
            "esi-characters.read_medals.v1",
            "esi-characters.read_notifications.v1",
            "esi-characters.read_opportunities.v1",
            "esi-characters.read_standings.v1",
            "esi-characters.read_titles.v1",
            "esi-clones.read_clones.v1",
            "esi-clones.read_implants.v1",
            "esi-contracts.read_character_contracts.v1",
            "esi-corporations.read_corporation_membership.v1",
            "esi-industry.read_character_jobs.v1",
            "esi-industry.read_character_mining.v1",
            "esi-killmails.read_killmails.v1",
            "esi-location.read_location.v1",
            "esi-location.read_online.v1",
            "esi-location.read_ship_type.v1",
            "esi-mail.organize_mail.v1",
            "esi-mail.read_mail.v1",
            "esi-markets.read_character_orders.v1",
            "esi-markets.structure_markets.v1",
            "esi-planets.manage_planets.v1",
            "esi-planets.read_customs_offices.v1",
            "esi-search.search_structures.v1",
            "esi-skills.read_skillqueue.v1",
            "esi-skills.read_skills.v1",
            "esi-universe.read_structures.v1",
            "esi-wallet.read_character_wallet.v1",
        ]


class CharacterAsset(models.Model):
    """An Eve Online asset belonging to a Character"""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="assets"
    )
    item_id = models.PositiveBigIntegerField()

    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, default=None, null=True
    )
    parent = models.ForeignKey(
        "CharacterAsset",
        on_delete=models.CASCADE,
        default=None,
        null=True,
        related_name="children",
    )

    eve_type = models.ForeignKey(EveType, on_delete=models.CASCADE, related_name="+")
    is_blueprint_copy = models.BooleanField(default=None, null=True, db_index=True)
    is_singleton = models.BooleanField()
    location_flag = models.CharField(max_length=NAMES_MAX_LENGTH)
    name = models.CharField(max_length=NAMES_MAX_LENGTH, default="")
    quantity = models.PositiveIntegerField()

    objects = CharacterAssetManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "item_id"],
                name="functional_pk_characterasset",
            )
        ]

    def __str__(self) -> str:
        return f"{self.character}-{self.item_id}-{self.name_display}"

    @property
    def name_display(self) -> str:
        """name of this asset to be displayed to user"""
        name = self.name if self.name else self.eve_type.name
        if self.is_blueprint_copy:
            name += " [BPC]"
        return name

    @property
    def icon_url(self) -> str:
        variant = self.eve_type.IconVariant.BPC if self.is_blueprint_copy else None
        return self.eve_type.icon_url(variant=variant)

    @property
    def group_display(self) -> str:
        """group of this asset to be displayed to user"""
        return self.eve_type.name if self.name else self.eve_type.eve_group.name


class CharacterContactLabel(models.Model):
    """An Eve Online contact label belonging to a Character"""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="contact_labels"
    )
    label_id = models.PositiveBigIntegerField()
    name = models.CharField(max_length=NAMES_MAX_LENGTH)

    objects = CharacterContactLabelManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "label_id"],
                name="functional_pk_characterlabel",
            )
        ]

    def __str__(self) -> str:
        return f"{self.character}-{self.name}"


class CharacterContact(models.Model):
    """An Eve Online contact belonging to a Character"""

    STANDING_EXCELLENT = _("excellent standing")
    STANDING_GOOD = _("good standing")
    STANDING_NEUTRAL = _("neutral standing")
    STANDING_BAD = _("bad standing")
    STANDING_TERRIBLE = _("terrible standing")

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="contacts"
    )
    eve_entity = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, related_name="+"
    )

    is_blocked = models.BooleanField(default=None, null=True)
    is_watched = models.BooleanField(default=None, null=True)
    standing = models.FloatField()
    labels = models.ManyToManyField(CharacterContactLabel, related_name="contacts")

    objects = CharacterContactManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "eve_entity"],
                name="functional_pk_charactercontact",
            )
        ]

    def __str__(self) -> str:
        return f"{self.character}-{self.eve_entity.name}"

    @property
    def standing_level(self) -> int:
        if self.standing > 5:
            return self.STANDING_EXCELLENT

        if 5 >= self.standing > 0:
            return self.STANDING_GOOD

        if self.standing == 0:
            return self.STANDING_NEUTRAL

        if 0 > self.standing >= -5:
            return self.STANDING_BAD

        if self.standing < -5:
            return self.STANDING_TERRIBLE


class CharacterContract(models.Model):
    """An Eve Online contract belonging to a Character"""

    AVAILABILITY_ALLIANCE = "AL"
    AVAILABILITY_CORPORATION = "CO"
    AVAILABILITY_PERSONAL = "PR"
    AVAILABILITY_PUBLIC = "PU"
    AVAILABILITY_CHOICES = (
        (AVAILABILITY_ALLIANCE, _("alliance")),
        (AVAILABILITY_CORPORATION, _("corporation")),
        (AVAILABILITY_PERSONAL, _("private")),
        (AVAILABILITY_PUBLIC, _("public")),
    )
    ESI_AVAILABILITY_MAP = {
        "alliance": AVAILABILITY_ALLIANCE,
        "corporation": AVAILABILITY_CORPORATION,
        "personal": AVAILABILITY_PERSONAL,
        "public": AVAILABILITY_PUBLIC,
    }

    STATUS_OUTSTANDING = "OS"
    STATUS_IN_PROGRESS = "IP"
    STATUS_FINISHED_ISSUER = "FI"
    STATUS_FINISHED_CONTRACTOR = "FC"
    STATUS_FINISHED = "FS"
    STATUS_CANCELED = "CA"
    STATUS_REJECTED = "RJ"
    STATUS_FAILED = "FL"
    STATUS_DELETED = "DL"
    STATUS_REVERSED = "RV"
    STATUS_CHOICES = (
        (STATUS_CANCELED, _("canceled")),
        (STATUS_DELETED, _("deleted")),
        (STATUS_FAILED, _("failed")),
        (STATUS_FINISHED, _("finished")),
        (STATUS_FINISHED_CONTRACTOR, _("finished contractor")),
        (STATUS_FINISHED_ISSUER, _("finished issuer")),
        (STATUS_IN_PROGRESS, _("in progress")),
        (STATUS_OUTSTANDING, _("outstanding")),
        (STATUS_REJECTED, _("rejected")),
        (STATUS_REVERSED, _("reversed")),
    )
    ESI_STATUS_MAP = {
        "canceled": STATUS_CANCELED,
        "deleted": STATUS_DELETED,
        "failed": STATUS_FAILED,
        "finished": STATUS_FINISHED,
        "finished_contractor": STATUS_FINISHED_CONTRACTOR,
        "finished_issuer": STATUS_FINISHED_ISSUER,
        "in_progress": STATUS_IN_PROGRESS,
        "outstanding": STATUS_OUTSTANDING,
        "rejected": STATUS_REJECTED,
        "reversed": STATUS_REVERSED,
    }

    TYPE_AUCTION = "AT"
    TYPE_COURIER = "CR"
    TYPE_ITEM_EXCHANGE = "IE"
    TYPE_LOAN = "LN"
    TYPE_UNKNOWN = "UK"
    TYPE_CHOICES = (
        (TYPE_AUCTION, _("auction")),
        (TYPE_COURIER, _("courier")),
        (TYPE_ITEM_EXCHANGE, _("item exchange")),
        (TYPE_LOAN, _("loan")),
        (TYPE_UNKNOWN, _("unknown")),
    )
    ESI_TYPE_MAP = {
        "auction": TYPE_AUCTION,
        "courier": TYPE_COURIER,
        "item_exchange": TYPE_ITEM_EXCHANGE,
        "loan": TYPE_LOAN,
        "unknown": TYPE_UNKNOWN,
    }

    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name="contracts",
    )
    contract_id = models.IntegerField()

    acceptor = models.ForeignKey(
        EveEntity,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        related_name="+",
        help_text="Who will accept the contract if character",
    )
    acceptor_corporation = models.ForeignKey(
        EveEntity,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        related_name="+",
        help_text="corporation of acceptor",
    )
    assignee = models.ForeignKey(
        EveEntity,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        related_name="+",
        help_text="To whom the contract is assigned, can be a corporation or a character",
    )
    availability = models.CharField(
        max_length=2,
        choices=AVAILABILITY_CHOICES,
        help_text="To whom the contract is available",
    )
    buyout = models.DecimalField(
        max_digits=CURRENCY_MAX_DIGITS,
        decimal_places=CURRENCY_MAX_DECIMALS,
        default=None,
        null=True,
    )
    collateral = models.DecimalField(
        max_digits=CURRENCY_MAX_DIGITS,
        decimal_places=CURRENCY_MAX_DECIMALS,
        default=None,
        null=True,
    )
    contract_type = models.CharField(max_length=2, choices=TYPE_CHOICES)
    date_accepted = models.DateTimeField(default=None, null=True)
    date_completed = models.DateTimeField(default=None, null=True)
    date_expired = models.DateTimeField()
    date_issued = models.DateTimeField()
    days_to_complete = models.IntegerField(default=None, null=True)
    end_location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="contract_end_location",
        default=None,
        null=True,
    )
    for_corporation = models.BooleanField()
    issuer_corporation = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, related_name="+"
    )
    issuer = models.ForeignKey(EveEntity, on_delete=models.CASCADE, related_name="+")
    price = models.DecimalField(
        max_digits=CURRENCY_MAX_DIGITS,
        decimal_places=CURRENCY_MAX_DECIMALS,
        default=None,
        null=True,
    )
    reward = models.DecimalField(
        max_digits=CURRENCY_MAX_DIGITS,
        decimal_places=CURRENCY_MAX_DECIMALS,
        default=None,
        null=True,
    )
    start_location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="contract_start_location",
        default=None,
        null=True,
    )
    status = models.CharField(max_length=2, choices=STATUS_CHOICES)
    title = models.CharField(max_length=NAMES_MAX_LENGTH, default="")
    volume = models.FloatField(default=None, null=True)

    objects = CharacterContractManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "contract_id"],
                name="functional_pk_charactercontract",
            )
        ]

    def __str__(self) -> str:
        return f"{self.character}-{self.contract_id}"

    @property
    def is_completed(self) -> bool:
        """whether this contract is completed or active"""
        return self.status in [
            self.STATUS_FINISHED_ISSUER,
            self.STATUS_FINISHED_CONTRACTOR,
            self.STATUS_FINISHED_ISSUER,
            self.STATUS_CANCELED,
            self.STATUS_REJECTED,
            self.STATUS_DELETED,
            self.STATUS_FINISHED,
            self.STATUS_FAILED,
        ]

    @property
    def is_in_progress(self) -> bool:
        return self.status == self.STATUS_IN_PROGRESS

    @property
    def is_failed(self) -> bool:
        return self.status == self.STATUS_FAILED

    @property
    def has_expired(self) -> bool:
        """returns true if this contract is expired"""
        return self.date_expired < now()

    @property
    def hours_issued_2_completed(self) -> float:
        if self.date_completed:
            td = self.date_completed - self.date_issued
            return td.days * 24 + (td.seconds / 3600)
        else:
            return None

    def summary(self) -> str:
        """return summary text for this contract"""
        if self.contract_type == CharacterContract.TYPE_COURIER:
            summary = (
                f"{self.start_location.eve_solar_system} >> "
                f"{self.end_location.eve_solar_system} "
                f"({self.volume:.0f} m3)"
            )
        else:
            if self.items.filter(is_included=True).count() > 1:
                summary = _("[Multiple Items]")
            else:
                first_item = self.items.first()
                summary = first_item.eve_type.name if first_item else "(no items)"

        return summary


class CharacterContractBid(models.Model):
    contract = models.ForeignKey(
        CharacterContract, on_delete=models.CASCADE, related_name="bids"
    )
    bid_id = models.PositiveIntegerField(db_index=True)

    amount = models.FloatField()
    bidder = models.ForeignKey(EveEntity, on_delete=models.CASCADE, related_name="+")
    date_bid = models.DateTimeField()

    objects = CharacterContractBidManager()

    class Meta:
        default_permissions = ()

    def __str__(self) -> str:
        return f"{self.contract}-{self.bid_id}"


class CharacterContractItem(models.Model):
    contract = models.ForeignKey(
        CharacterContract, on_delete=models.CASCADE, related_name="items"
    )
    record_id = models.PositiveIntegerField(db_index=True)

    is_included = models.BooleanField(db_index=True)
    is_singleton = models.BooleanField()
    quantity = models.PositiveIntegerField()
    raw_quantity = models.IntegerField(default=None, null=True)
    eve_type = models.ForeignKey(EveType, on_delete=models.CASCADE, related_name="+")

    objects = CharacterContractItemManager()

    class Meta:
        default_permissions = ()

    def __str__(self) -> str:
        return f"{self.contract}-{self.record_id}"

    @property
    def is_blueprint_original(self) -> bool:
        return self.raw_quantity == -1

    @property
    def is_blueprint_copy(self) -> bool:
        return self.raw_quantity == -2

    @property
    def is_blueprint(self) -> bool:
        return self.raw_quantity in [-1, -2]

    @property
    def name_display(self) -> str:
        """name to be displayed to user"""
        name = self.eve_type.name
        if self.is_blueprint_copy:
            name += " [BPC]"
        return name


class CharacterCorporationHistory(models.Model):
    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="corporation_history"
    )
    record_id = models.PositiveIntegerField(db_index=True)

    corporation = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, related_name="+"
    )
    is_deleted = models.BooleanField(null=True, default=None, db_index=True)
    start_date = models.DateTimeField(db_index=True)

    objects = CharacterCorporationHistoryManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "record_id"],
                name="functional_pk_charactercorporationhistory",
            )
        ]

    def __str__(self) -> str:
        return str(f"{self.character}-{self.record_id}")


class CharacterDetails(models.Model):
    """Details for a character"""

    GENDER_MALE = "m"
    GENDER_FEMALE = "f"
    GENDER_CHOICES = (
        (GENDER_MALE, _("male")),
        (GENDER_FEMALE, _("female")),
    )
    character = models.OneToOneField(
        Character,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="details",
        help_text="character this details belongs to",
    )

    # character public info
    alliance = models.ForeignKey(
        EveEntity,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        related_name="+",
    )
    birthday = models.DateTimeField()
    corporation = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, related_name="+"
    )
    description = models.TextField()
    eve_ancestry = models.ForeignKey(
        EveAncestry,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        related_name="+",
    )
    eve_bloodline = models.ForeignKey(
        EveBloodline, on_delete=models.CASCADE, related_name="+"
    )
    eve_faction = models.ForeignKey(
        EveFaction,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        related_name="+",
    )
    eve_race = models.ForeignKey(EveRace, on_delete=models.CASCADE, related_name="+")
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    name = models.CharField(max_length=NAMES_MAX_LENGTH)
    security_status = models.FloatField(default=None, null=True)
    title = models.TextField()

    class Meta:
        default_permissions = ()

    def __str__(self) -> str:
        return str(self.character)

    @property
    def description_plain(self) -> str:
        """returns the description without tags"""
        return eve_xml_to_html(self.description)


class CharacterImplant(models.Model):
    """Implant of a character"""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="implants"
    )
    eve_type = models.ForeignKey(EveType, on_delete=models.CASCADE, related_name="+")

    objects = CharacterImplantManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "eve_type"],
                name="functional_pk_characterimplant",
            )
        ]

    def __str__(self) -> str:
        return str(f"{self.character}-{self.eve_type}")


class CharacterLocation(models.Model):
    """Location of a character"""

    character = models.OneToOneField(
        Character, on_delete=models.CASCADE, primary_key=True, related_name="location"
    )

    eve_solar_system = models.ForeignKey(
        EveSolarSystem, on_delete=models.CASCADE, related_name="+"
    )
    location = models.ForeignKey(
        Location, on_delete=models.SET_DEFAULT, default=None, null=True
    )

    class Meta:
        default_permissions = ()

    def __str__(self) -> str:
        return str(f"{self.character}-{self.eve_solar_system}")


class CharacterLoyaltyEntry(models.Model):
    """Loyalty entry for a character"""

    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name="loyalty_entries",
    )
    corporation = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, related_name="+"
    )

    loyalty_points = models.PositiveIntegerField()

    objects = CharacterLoyaltyEntryManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "corporation"],
                name="functional_pk_characterloyaltyentry",
            )
        ]

    def __str__(self) -> str:
        return f"{self.character}-{self.corporation}"


class CharacterJumpClone(models.Model):
    """Jump clone of a character"""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="jump_clones"
    )
    jump_clone_id = models.PositiveIntegerField(db_index=True)

    location = models.ForeignKey(Location, on_delete=models.CASCADE)
    name = models.CharField(max_length=NAMES_MAX_LENGTH, default="")

    objects = CharacterJumpCloneManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "jump_clone_id"],
                name="functional_pk_characterjumpclone",
            )
        ]

    def __str__(self) -> str:
        return str(f"{self.character}-{self.jump_clone_id}")


class CharacterJumpCloneImplant(models.Model):
    """Implant of a character jump clone"""

    jump_clone = models.ForeignKey(
        CharacterJumpClone, on_delete=models.CASCADE, related_name="implants"
    )
    eve_type = models.ForeignKey(EveType, on_delete=models.CASCADE, related_name="+")

    class Meta:
        default_permissions = ()

    def __str__(self) -> str:
        return str(f"{self.jump_clone}-{self.eve_type}")


class CharacterMail(models.Model):
    """Mail of a character"""

    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name="mails",
        help_text="character this mail belongs to",
    )
    mail_id = models.PositiveIntegerField(db_index=True)

    body = models.TextField()
    is_read = models.BooleanField(null=True, default=None, db_index=True)
    labels = models.ManyToManyField("CharacterMailLabel", related_name="mails")
    recipients = models.ManyToManyField("MailEntity", related_name="recipient_mails")
    # TODO: When migrations are reset remove default for sender
    sender = models.ForeignKey(
        "MailEntity",
        on_delete=models.CASCADE,
        null=True,
        default=None,
        related_name="sender_mails",
    )
    subject = models.CharField(max_length=255, default="")
    timestamp = models.DateTimeField(null=True, default=None)

    objects = CharacterMailManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "mail_id"], name="functional_pk_charactermail"
            )
        ]

    def __str__(self) -> str:
        return f"{self.character}-{self.mail_id}"

    @property
    def body_html(self) -> str:
        """returns the body as html"""
        return eve_xml_to_html(self.body)


class CharacterMailLabel(models.Model):
    """Mail labels of a character"""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="mail_labels"
    )
    label_id = models.PositiveIntegerField(db_index=True)

    name = models.CharField(max_length=40, db_index=True)
    color = models.CharField(max_length=16, default="")
    unread_count = models.PositiveIntegerField(default=None, null=True)

    objects = CharacterMailLabelManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "label_id"],
                name="functional_pk_charactermaillabel",
            )
        ]

    def __str__(self) -> str:
        return self.name


class CharacterMailUnreadCount(models.Model):
    """Wallet balance of a character"""

    character = models.OneToOneField(
        Character,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="unread_mail_count",
    )
    total = models.PositiveIntegerField()

    class Meta:
        default_permissions = ()


class CharacterOnlineStatus(models.Model):
    """Online Status of a character"""

    character = models.OneToOneField(
        Character,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="online_status",
    )

    last_login = models.DateTimeField(default=None, null=True)
    last_logout = models.DateTimeField(default=None, null=True)
    logins = models.PositiveIntegerField(default=None, null=True)

    class Meta:
        default_permissions = ()

    def __str__(self) -> str:
        return str(self.character)


class CharacterSkill(models.Model):
    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="skills"
    )
    eve_type = models.ForeignKey(EveType, on_delete=models.CASCADE, related_name="+")

    active_skill_level = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    skillpoints_in_skill = models.PositiveBigIntegerField()
    trained_skill_level = models.PositiveBigIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )

    objects = CharacterSkillManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "eve_type"], name="functional_pk_characterskill"
            )
        ]

    def __str__(self) -> str:
        return f"{self.character}-{self.eve_type.name}"


class CharacterSkillpoints(models.Model):
    """Skillpoints of a character"""

    character = models.OneToOneField(
        Character,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="skillpoints",
    )
    total = models.PositiveBigIntegerField()
    unallocated = models.PositiveIntegerField(default=None, null=True)

    class Meta:
        default_permissions = ()


class CharacterSkillqueueEntry(models.Model):
    """Entry in the skillqueue of a character"""

    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name="skillqueue",
    )
    queue_position = models.PositiveIntegerField(db_index=True)

    finish_date = models.DateTimeField(default=None, null=True)
    finished_level = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    level_end_sp = models.PositiveIntegerField(default=None, null=True)
    level_start_sp = models.PositiveIntegerField(default=None, null=True)
    eve_type = models.ForeignKey(EveType, on_delete=models.CASCADE, related_name="+")
    start_date = models.DateTimeField(default=None, null=True)
    training_start_sp = models.PositiveIntegerField(default=None, null=True)

    objects = CharacterSkillqueueEntryManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "queue_position"],
                name="functional_pk_characterskillqueueentry",
            )
        ]

    def __str__(self) -> str:
        return f"{self.character}-{self.queue_position}"

    @property
    def is_active(self) -> bool:
        """Returns true when this skill is currently being trained"""
        return self.finish_date and self.queue_position == 0


class CharacterSkillSetCheck(models.Model):
    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="skill_set_checks"
    )
    skill_set = models.ForeignKey("SkillSet", on_delete=models.CASCADE)

    failed_required_skills = models.ManyToManyField(
        "SkillSetSkill", related_name="failed_required_skill_set_checks"
    )
    failed_recommended_skills = models.ManyToManyField(
        "SkillSetSkill", related_name="failed_recommended_skill_set_checks"
    )

    objects = CharacterSkillSetCheckManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "skill_set"],
                name="functional_pk_characterskillsetcheck",
            )
        ]

    def __str__(self) -> str:
        return f"{self.character}-{self.skill_set}"

    @property
    def can_fly(self) -> bool:
        return self.failed_required_skills.count() == 0


class CharacterUpdateStatus(models.Model):
    """Update status for a character"""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="update_status_set"
    )

    section = models.CharField(
        max_length=64, choices=Character.UpdateSection.choices, db_index=True
    )
    is_success = models.BooleanField(
        null=True,
        default=None,
        db_index=True,
    )
    content_hash_1 = models.CharField(max_length=32, default="")
    content_hash_2 = models.CharField(max_length=32, default="")
    content_hash_3 = models.CharField(max_length=32, default="")
    last_error_message = models.TextField()
    root_task_id = models.CharField(
        max_length=36,
        default="",
        db_index=True,
        help_text="ID of update_all_characters task that started this update",
    )
    parent_task_id = models.CharField(
        max_length=36,
        default="",
        db_index=True,
        help_text="ID of character_update task that started this update",
    )
    started_at = models.DateTimeField(null=True, default=None, db_index=True)
    finished_at = models.DateTimeField(null=True, default=None, db_index=True)

    objects = CharacterUpdateStatusManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "section"],
                name="functional_pk_charactersyncstatus",
            )
        ]

    def __str__(self) -> str:
        return f"{self.character}-{self.section}"

    @property
    def is_updating(self) -> bool:
        if not self.started_at and not self.finished_at:
            return False
        else:
            return self.started_at is not None and self.finished_at is None

    def has_changed(self, content: Any, hash_num: int = 1) -> bool:
        """returns True if given content is not the same as previous one, else False"""
        new_hash = self._calculate_hash(content)
        if hash_num == 2:
            content_hash = self.content_hash_2
        elif hash_num == 3:
            content_hash = self.content_hash_3
        else:
            content_hash = self.content_hash_1

        return new_hash != content_hash

    def update_content_hash(self, content: Any, hash_num: int = 1):
        new_hash = self._calculate_hash(content)
        if hash_num == 2:
            self.content_hash_2 = new_hash
        elif hash_num == 3:
            self.content_hash_3 = new_hash
        else:
            self.content_hash_1 = new_hash

        self.save()

    @staticmethod
    def _calculate_hash(content: Any) -> str:
        return hashlib.md5(
            json.dumps(content, cls=DjangoJSONEncoder).encode("utf-8")
        ).hexdigest()

    def reset(self, root_task_id: str = None, parent_task_id: str = None) -> None:
        """resets this update status"""
        self.is_success = None
        self.last_error_message = ""
        self.started_at = now()
        self.finished_at = None
        self.root_task_id = root_task_id if root_task_id else ""
        self.parent_task_id = parent_task_id if root_task_id else ""
        self.save()


class CharacterWalletBalance(models.Model):
    """Wallet balance of a character"""

    character = models.OneToOneField(
        Character,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="wallet_balance",
    )
    total = models.DecimalField(
        max_digits=CURRENCY_MAX_DIGITS, decimal_places=CURRENCY_MAX_DECIMALS
    )

    class Meta:
        default_permissions = ()


class CharacterWalletJournalEntry(models.Model):
    CONTEXT_ID_TYPE_UNDEFINED = "NON"
    CONTEXT_ID_TYPE_STRUCTURE_ID = "STR"
    CONTEXT_ID_TYPE_STATION_ID = "STA"
    CONTEXT_ID_TYPE_MARKET_TRANSACTION_ID = "MTR"
    CONTEXT_ID_TYPE_CHARACTER_ID = "CHR"
    CONTEXT_ID_TYPE_CORPORATION_ID = "COR"
    CONTEXT_ID_TYPE_ALLIANCE_ID = "ALL"
    CONTEXT_ID_TYPE_EVE_SYSTEM = "EVE"
    CONTEXT_ID_TYPE_INDUSTRY_JOB_ID = "INJ"
    CONTEXT_ID_TYPE_CONTRACT_ID = "CNT"
    CONTEXT_ID_TYPE_PLANET_ID = "PLN"
    CONTEXT_ID_TYPE_SYSTEM_ID = "SYS"
    CONTEXT_ID_TYPE_TYPE_ID = "TYP"
    CONTEXT_ID_CHOICES = (
        (CONTEXT_ID_TYPE_UNDEFINED, _("undefined")),
        (CONTEXT_ID_TYPE_STATION_ID, _("station ID")),
        (CONTEXT_ID_TYPE_MARKET_TRANSACTION_ID, _("market transaction ID")),
        (CONTEXT_ID_TYPE_CHARACTER_ID, _("character ID")),
        (CONTEXT_ID_TYPE_CORPORATION_ID, _("corporation ID")),
        (CONTEXT_ID_TYPE_ALLIANCE_ID, _("alliance ID")),
        (CONTEXT_ID_TYPE_EVE_SYSTEM, _("eve system")),
        (CONTEXT_ID_TYPE_INDUSTRY_JOB_ID, _("industry job ID")),
        (CONTEXT_ID_TYPE_CONTRACT_ID, _("contract ID")),
        (CONTEXT_ID_TYPE_PLANET_ID, _("planet ID")),
        (CONTEXT_ID_TYPE_SYSTEM_ID, _("system ID")),
        (CONTEXT_ID_TYPE_TYPE_ID, _("type ID")),
    )
    CONTEXT_ID_MAPS = {
        "undefined": CONTEXT_ID_TYPE_UNDEFINED,
        "station_id": CONTEXT_ID_TYPE_STATION_ID,
        "market_transaction_id": CONTEXT_ID_TYPE_MARKET_TRANSACTION_ID,
        "character_id": CONTEXT_ID_TYPE_CHARACTER_ID,
        "corporation_id": CONTEXT_ID_TYPE_CORPORATION_ID,
        "alliance_id": CONTEXT_ID_TYPE_ALLIANCE_ID,
        "eve_system": CONTEXT_ID_TYPE_EVE_SYSTEM,
        "industry_job_id": CONTEXT_ID_TYPE_INDUSTRY_JOB_ID,
        "contract_id": CONTEXT_ID_TYPE_CONTRACT_ID,
        "planet_id": CONTEXT_ID_TYPE_PLANET_ID,
        "system_id": CONTEXT_ID_TYPE_SYSTEM_ID,
        "type_id": CONTEXT_ID_TYPE_TYPE_ID,
    }

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="wallet_journal"
    )
    entry_id = models.PositiveBigIntegerField()
    amount = models.DecimalField(
        max_digits=CURRENCY_MAX_DIGITS,
        decimal_places=CURRENCY_MAX_DECIMALS,
        default=None,
        null=True,
        blank=True,
    )
    balance = models.DecimalField(
        max_digits=CURRENCY_MAX_DIGITS,
        decimal_places=CURRENCY_MAX_DECIMALS,
        default=None,
        null=True,
        blank=True,
    )
    context_id = models.PositiveBigIntegerField(default=None, null=True)
    context_id_type = models.CharField(max_length=3, choices=CONTEXT_ID_CHOICES)
    date = models.DateTimeField()
    description = models.TextField()
    first_party = models.ForeignKey(
        EveEntity,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        related_name="+",
    )
    reason = models.TextField()
    ref_type = models.CharField(max_length=64)
    second_party = models.ForeignKey(
        EveEntity,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        related_name="+",
    )
    tax = models.DecimalField(
        max_digits=CURRENCY_MAX_DIGITS,
        decimal_places=CURRENCY_MAX_DECIMALS,
        default=None,
        null=True,
        blank=True,
    )
    tax_receiver = models.ForeignKey(
        EveEntity,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        related_name="+",
    )

    objects = CharacterWalletJournalEntryManager()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["character", "entry_id"],
                name="functional_pk_characterwalletjournalentry",
            )
        ]

    def __str__(self) -> str:
        return str(self.character) + " " + str(self.entry_id)

    @classmethod
    def match_context_type_id(cls, query: str) -> str:
        result = cls.CONTEXT_ID_MAPS.get(query)
        if result:
            return result

        return cls.CONTEXT_ID_TYPE_UNDEFINED


class SkillSetGroup(models.Model):
    """A group of SkillSets, e.g. for defining a doctrine"""

    name = models.CharField(max_length=NAMES_MAX_LENGTH, unique=True)
    description = models.TextField(blank=True)
    skill_sets = models.ManyToManyField("SkillSet", related_name="groups")
    is_doctrine = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "This enables a skill set group to show up correctly in doctrine reports"
        ),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this skill set group is in active use",
    )

    def __str__(self) -> str:
        return str(self.name)

    @property
    def name_plus(self) -> str:
        return "{}{}".format(_("Doctrine: ") if self.is_doctrine else "", self.name)


class SkillSet(models.Model):
    """A set of required and recommended skills needed to perform
    a particular task like flying a doctrine ships
    """

    name = models.CharField(max_length=NAMES_MAX_LENGTH, unique=True)
    description = models.TextField(blank=True)
    ship_type = models.ForeignKey(
        EveShipType,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        related_name="+",
        help_text=(
            "Ship type is used for visual presentation only. "
            "All skill requirements must be explicitly defined."
        ),
    )
    is_visible = models.BooleanField(
        default=True,
        db_index=True,
        help_text=(
            "Non visible skill sets are not shown to users "
            "on their character sheet and used for audit purposes only."
        ),
    )

    objects = SkillSetManager()

    def __str__(self) -> str:
        return str(self.name)


class SkillSetSkill(models.Model):
    # A specific skill within a skill set

    skill_set = models.ForeignKey(
        SkillSet, on_delete=models.CASCADE, related_name="skills"
    )
    eve_type = models.ForeignKey(
        EveSkillType, on_delete=models.CASCADE, verbose_name="skill", related_name="+"
    )

    required_level = models.PositiveIntegerField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    recommended_level = models.PositiveIntegerField(
        default=None,
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["skill_set", "eve_type"],
                name="functional_pk_skillsetskill",
            )
        ]

    def __str__(self) -> str:
        return f"{self.skill_set}-{self.eve_type}"


class MailEntity(models.Model):
    """A sender or recipient in a mail"""

    class Category(models.TextChoices):
        ALLIANCE = "AL", _("Alliance")
        CHARACTER = "CH", _("Character")
        CORPORATION = "CO", _("Corporation")
        MAILING_LIST = "ML", _("Mailing List")
        UNKNOWN = "UN", _("Unknown")

        @classmethod
        def eve_entity_compatible(cls) -> set:
            return {cls.ALLIANCE, cls.CHARACTER, cls.CORPORATION}

    id = models.PositiveIntegerField(primary_key=True)
    category = models.CharField(
        max_length=2, choices=Category.choices, db_index=True
    )  # mandatory
    name = models.CharField(max_length=255, db_index=True)  # optional

    objects = MailEntityManager()

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(id={self.id}, category={self.category}, "
            f"name='{self.name}')"
        )

    @property
    def name_plus(self) -> str:
        """returns the name if defined or a generatic name based on category and ID"""
        return self.name if self.name else f"{self.get_category_display()} #{self.id}"

    @property
    def eve_entity_categories(self) -> set:
        """categories which also exist for EveEntity"""
        return {
            self.Category.ALLIANCE,
            self.Category.CHARACTER,
            self.Category.CORPORATION,
        }

    def save(self, *args, **kwargs):
        if not self.category:
            raise ValidationError("You must specify a category")

        super().save(*args, **kwargs)

    def external_url(self) -> str:
        """returns URL for to show details of this entity on external website"""
        if self.category == self.Category.ALLIANCE and self.name:
            return dotlan.alliance_url(self.name)

        elif self.category == self.Category.CHARACTER:
            return evewho.character_url(self.id)

        elif self.category == self.Category.CORPORATION and self.name:
            return dotlan.corporation_url(self.name)

        else:
            return ""
