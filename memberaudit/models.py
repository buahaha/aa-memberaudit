import datetime as dt
from collections import namedtuple
import json
import os
from typing import List, Optional

from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models, transaction
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from esi.models import Token
from esi.errors import TokenError

from eveuniverse.core.esitools import is_esi_online
from eveuniverse.models import (
    EveAncestry,
    EveBloodline,
    EveEntity,
    EveFaction,
    EveRace,
    EveSolarSystem,
    EveType,
)

from allianceauth.eveonline.evelinks import dotlan
from allianceauth.authentication.models import CharacterOwnership
from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .app_settings import (
    MEMBERAUDIT_MAX_MAILS,
    MEMBERAUDIT_DEVELOPER_MODE,
    MEMBERAUDIT_BULK_METHODS_BATCH_SIZE,
    MEMBERAUDIT_UPDATE_STALE_RING_1,
    MEMBERAUDIT_UPDATE_STALE_RING_2,
    MEMBERAUDIT_UPDATE_STALE_RING_3,
)
from .decorators import fetch_token_for_character
from .helpers import (
    get_or_create_esi_or_none,
    get_or_none,
    get_or_create_or_none,
    eve_xml_to_html,
)
from .managers import (
    CharacterAssetManager,
    CharacterContractItemManager,
    CharacterMailLabelManager,
    CharacterManager,
    LocationManager,
)
from .providers import esi
from .utils import LoggerAddTag, chunks

CharacterDoctrineResult = namedtuple(
    "CharacterDoctrineResult", ["doctrine", "ship", "insufficient_skills"]
)

logger = LoggerAddTag(get_extension_logger(__name__), __title__)

CURRENCY_MAX_DIGITS = 17
CURRENCY_MAX_DECIMALS = 2
NAMES_MAX_LENGTH = 100


class General(models.Model):
    """Meta model for app permissions"""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (
            (
                "basic_access",
                "Can access this app and register and view own characters",
            ),
            ("finder_access", "Can access character finder feature"),
            ("reports_access", "Can access reports feature"),
            ("view_shared_characters", "Can view shared characters"),
            ("view_same_corporation", "Can view corporation characters"),
            ("view_same_alliance", "Can view alliance characters"),
            ("view_everything", "Can view all characters"),
        )


class Location(models.Model):
    """An Eve Online location: Station or Upwell Structure or Solar System"""

    _SOLAR_SYSTEM_ID_START = 30_000_000
    _SOLAR_SYSTEM_ID_END = 33_000_000
    _STATION_ID_START = 60_000_000
    _STATION_ID_END = 64_000_000
    _STRUCTURE_ID_START = 1_000_000_000_000

    id = models.BigIntegerField(
        primary_key=True,
        validators=[MinValueValidator(0)],
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
    )
    eve_type = models.ForeignKey(
        EveType,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
    )
    owner = models.ForeignKey(
        EveEntity,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        help_text="corporation this station or structure belongs to",
    )
    updated_at = models.DateTimeField(auto_now=True)

    objects = LocationManager()

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

    UPDATE_SECTION_ASSETS = "assets"
    UPDATE_SECTION_CHARACTER_DETAILS = "character_details"
    UPDATE_SECTION_CONTACTS = "contacts"
    UPDATE_SECTION_CONTRACTS = "contracts"
    UPDATE_SECTION_CORPORATION_HISTORY = "corporation_history"
    UPDATE_SECTION_DOCTRINES = "doctrines"
    UPDATE_SECTION_IMPLANTS = "implants"
    UPDATE_SECTION_JUMP_CLONES = "jump_clones"
    UPDATE_SECTION_LOCATION = "location"
    UPDATE_SECTION_LOYALTY = "loyalty"
    UPDATE_SECTION_MAILS = "mails"
    UPDATE_SECTION_ONLINE_STATUS = "online_status"
    UPDATE_SECTION_SKILLS = "skills"
    UPDATE_SECTION_SKILL_QUEUE = "skill_queue"
    UPDATE_SECTION_WALLET_BALLANCE = "wallet_balance"
    UPDATE_SECTION_WALLET_JOURNAL = "wallet_journal"
    UPDATE_SECTION_CHOICES = (
        (UPDATE_SECTION_ASSETS, _("assets")),
        (UPDATE_SECTION_CHARACTER_DETAILS, _("character details")),
        (UPDATE_SECTION_CONTACTS, _("contacts")),
        (UPDATE_SECTION_CONTRACTS, _("contracts")),
        (UPDATE_SECTION_CORPORATION_HISTORY, _("corporation history")),
        (UPDATE_SECTION_DOCTRINES, _("doctrines")),
        (UPDATE_SECTION_IMPLANTS, _("implants")),
        (UPDATE_SECTION_JUMP_CLONES, _("jump clones")),
        (UPDATE_SECTION_LOCATION, _("location")),
        (UPDATE_SECTION_LOYALTY, _("loyalty")),
        (UPDATE_SECTION_MAILS, _("mails")),
        (UPDATE_SECTION_ONLINE_STATUS, _("online status")),
        (UPDATE_SECTION_SKILLS, _("skills")),
        (UPDATE_SECTION_SKILL_QUEUE, _("skill queue")),
        (UPDATE_SECTION_WALLET_BALLANCE, _("wallet balance")),
        (UPDATE_SECTION_WALLET_JOURNAL, _("wallet journal")),
    )

    UPDATE_SECTION_RINGS_MAP = {
        UPDATE_SECTION_ASSETS: 3,
        UPDATE_SECTION_CHARACTER_DETAILS: 2,
        UPDATE_SECTION_CONTACTS: 2,
        UPDATE_SECTION_CONTRACTS: 2,
        UPDATE_SECTION_CORPORATION_HISTORY: 2,
        UPDATE_SECTION_DOCTRINES: 2,
        UPDATE_SECTION_IMPLANTS: 2,
        UPDATE_SECTION_JUMP_CLONES: 2,
        UPDATE_SECTION_LOCATION: 1,
        UPDATE_SECTION_LOYALTY: 2,
        UPDATE_SECTION_MAILS: 2,
        UPDATE_SECTION_ONLINE_STATUS: 1,
        UPDATE_SECTION_SKILLS: 2,
        UPDATE_SECTION_SKILL_QUEUE: 1,
        UPDATE_SECTION_WALLET_BALLANCE: 2,
        UPDATE_SECTION_WALLET_JOURNAL: 2,
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

    objects = CharacterManager()

    def __str__(self) -> str:
        return f"{self.character_ownership.character.character_name} (PK:{self.pk})"

    def __repr__(self) -> str:
        return (
            f"Character(pk={self.pk}, "
            f"character_ownership='{self.character_ownership}')"
        )

    @property
    def has_mails(self):
        return (
            self.mails.count() > 0
            or self.update_status_set.filter(
                section=Character.UPDATE_SECTION_MAILS
            ).exists()
        )

    @property
    def has_wallet_journal(self):
        return (
            self.wallet_journal.count() > 0
            or self.update_status_set.filter(
                section=Character.UPDATE_SECTION_WALLET_JOURNAL
            ).exists()
        )

    def user_has_access(self, user: User) -> bool:
        """Returns True if given user has permission to view this character"""
        if self.character_ownership.user == user:
            return True
        elif user.has_perm("memberaudit.view_everything"):
            return True
        elif (
            user.has_perm("memberaudit.view_same_alliance")
            and user.profile.main_character.alliance_id
            and user.profile.main_character.alliance_id
            == self.character_ownership.character.alliance_id
        ):
            return True
        elif (
            user.has_perm("memberaudit.view_same_corporation")
            and user.profile.main_character.corporation_id
            == self.character_ownership.character.corporation_id
        ):
            return True
        elif user.has_perm("memberaudit.view_shared_characters") and self.is_shared:
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
        elif ok_count == len(Character.UPDATE_SECTION_CHOICES):
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

        return dt.timedelta(minutes=minutes)

    def update_section_last_update(self, section: str) -> dt.datetime:
        """Datetime of last successful update or None"""
        try:
            return self.update_status_set.get(
                section=section, is_success=True
            ).updated_at
        except (CharacterUpdateStatus.DoesNotExist, ObjectDoesNotExist, AttributeError):
            return None

    def is_update_section_stale(self, section: str) -> bool:
        """returns True if the give update section is stale, else False"""
        last_updated = self.update_section_last_update(section)
        if not last_updated:
            return True

        deadline = now() - self.update_section_time_until_stale(section)
        return last_updated < deadline

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

    @fetch_token_for_character(
        ["esi-assets.read_assets.v1", "esi-universe.read_structures.v1"]
    )
    def assets_build_list_from_esi(self, token: Token) -> dict:
        """fetches assets from ESI and preloads related objects from ESI

        returns the asset_list
        """
        logger.info("%s: Fetching assets from ESI", self)
        asset_list = esi.client.Assets.get_characters_character_id_assets(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        asset_list_2 = {int(x["item_id"]): x for x in asset_list}

        logger.info("%s: Fetching asset names from ESI", self)
        names = list()
        for asset_ids_chunk in chunks(list(asset_list_2.keys()), 999):
            names += esi.client.Assets.post_characters_character_id_assets_names(
                character_id=self.character_ownership.character.character_id,
                token=token.valid_access_token(),
                item_ids=asset_ids_chunk,
            ).results()

        asset_names = {x["item_id"]: x["name"] for x in names if x["name"] != "None"}
        for item_id in asset_list_2.keys():
            asset_list_2[item_id]["name"] = asset_names.get(item_id, "")

        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(asset_list_2, "asset_list")

        self._preload_all_eve_types(asset_list_2)
        incoming_location_ids = {
            x["location_id"]
            for x in asset_list_2.values()
            if "location_id" in x and x["location_id"] not in asset_list_2
        }
        self._preload_all_locations(token=token, incoming_ids=incoming_location_ids)

        return asset_list_2

    def _preload_all_eve_types(self, asset_list: dict) -> None:
        required_ids = {x["type_id"] for x in asset_list.values() if "type_id" in x}
        existing_ids = set(EveType.objects.values_list("id", flat=True))
        missing_ids = required_ids.difference(existing_ids)
        if missing_ids:
            logger.info("%s: Loading %s missing types from ESI", self, len(missing_ids))
            for type_id in missing_ids:
                EveType.objects.update_or_create_esi(id=type_id)

    def update_character_details(self):
        """syncs the character details for the given character"""
        logger.info("%s: Fetching character details from ESI", self)
        details = esi.client.Character.get_characters_character_id(
            character_id=self.character_ownership.character.character_id,
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(details, "character_details")

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
        CharacterDetails.objects.update_or_create(
            character=self,
            defaults={
                "alliance": get_or_create_or_none("alliance_id", details, EveEntity),
                "birthday": details.get("birthday"),
                "eve_ancestry": get_or_create_esi_or_none(
                    "ancestry_id", details, EveAncestry
                ),
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

    def update_corporation_history(self):
        """syncs the character's corporation history"""
        logger.info("%s: Fetching corporation history from ESI", self)
        history = esi.client.Character.get_characters_character_id_corporationhistory(
            character_id=self.character_ownership.character.character_id,
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(history, "corporation_history")

        entries = [
            CharacterCorporationHistory(
                character=self,
                record_id=row.get("record_id"),
                corporation=get_or_create_or_none("corporation_id", row, EveEntity),
                is_deleted=row.get("is_deleted"),
                start_date=row.get("start_date"),
            )
            for row in history
        ]
        with transaction.atomic():
            self.corporation_history.all().delete()
            if entries:
                logger.info(
                    "%s: Creating %s entries for corporation history",
                    self,
                    len(entries),
                )
                CharacterCorporationHistory.objects.bulk_create(entries)
                EveEntity.objects.bulk_update_new_esi()
            else:
                logger.info("%s: Corporation history is empty", self)

    @fetch_token_for_character("esi-characters.read_contacts.v1")
    def update_contact_labels(self, token: Token):
        logger.info("%s: Fetching contact labels from ESI", self)
        labels = esi.client.Contacts.get_characters_character_id_contacts_labels(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(labels, "contact_labels")

        # TODO: replace with bulk methods to optimize
        with transaction.atomic():
            if labels:
                incoming_ids = {x["label_id"] for x in labels}
            else:
                incoming_ids = set()

            existing_ids = set(self.contact_labels.values_list("label_id", flat=True))
            obsolete_ids = existing_ids.difference(incoming_ids)
            if obsolete_ids:
                logger.info("%s: Removing %s obsolete skills", self, len(obsolete_ids))
                self.contact_labels.filter(label_id__in=obsolete_ids).delete()

            if incoming_ids:
                logger.info("%s: Storing %s contact labels", self, len(incoming_ids))
                for label in labels:
                    CharacterContactLabel.objects.update_or_create(
                        character=self,
                        label_id=label.get("label_id"),
                        defaults={
                            "name": label.get("label_name"),
                        },
                    )
            else:
                logger.info("%s: No contact labels", self)

    @fetch_token_for_character("esi-characters.read_contacts.v1")
    def update_contacts(self, token):
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

        with transaction.atomic():
            incoming_ids = set(contacts_list.keys())
            existing_ids = set(self.contacts.values_list("eve_entity_id", flat=True))
            obsolete_ids = existing_ids.difference(incoming_ids)
            if obsolete_ids:
                logger.info(
                    "%s: Removing %s obsolete contacts", self, len(obsolete_ids)
                )
                self.contacts.filter(eve_entity_id__in=obsolete_ids).delete()

            create_ids = incoming_ids.difference(existing_ids)
            if create_ids:
                self._create_new_contacts(
                    contacts_list=contacts_list, contact_ids=create_ids
                )

            update_ids = incoming_ids.difference(create_ids)
            if update_ids:
                self._update_existing_contacts(
                    contacts_list=contacts_list, contact_ids=update_ids
                )

            if not obsolete_ids and not create_ids and not update_ids:
                logger.info("%s: Contacts have not changed", self)

    def _create_new_contacts(self, contacts_list: dict, contact_ids: list):
        logger.info("%s: Storing %s new contacts", self, len(contact_ids))
        new_contacts_list = {
            contact_id: obj
            for contact_id, obj in contacts_list.items()
            if contact_id in contact_ids
        }
        new_contacts = [
            CharacterContact(
                character=self,
                eve_entity=get_or_create_or_none("contact_id", contact_data, EveEntity),
                is_blocked=contact_data.get("is_blocked"),
                is_watched=contact_data.get("is_watched"),
                standing=contact_data.get("standing"),
            )
            for contact_data in new_contacts_list.values()
        ]
        CharacterContact.objects.bulk_create(
            new_contacts, batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
        )
        self._update_contact_contact_labels(
            contacts_list=contacts_list, contact_ids=contact_ids, is_new=True
        )

    def _update_contact_contact_labels(
        self, contacts_list: dict, contact_ids: list, is_new=False
    ):
        for contact_id, contact_data in contacts_list.items():
            if contact_id in contact_ids and contact_data.get("label_ids"):
                character_contact = self.contacts.get(eve_entity_id=contact_id)
                if not is_new:
                    character_contact.labels.clear()

                labels = list()
                for label_id in contact_data.get("label_ids"):
                    try:
                        label = self.contact_labels.get(label_id=label_id)
                    except CharacterContactLabel.DoesNotExist:
                        # sometimes label IDs on contacts
                        # do not refer to actual labels
                        logger.info(
                            "%s: Unknown contact label with id %s",
                            self,
                            label_id,
                        )
                    else:
                        labels.append(label)

                    character_contact.labels.add(*labels)

    def _update_existing_contacts(self, contacts_list: dict, contact_ids: list):
        logger.info("%s: Updating %s contacts", self, len(contact_ids))
        update_contact_pks = list(
            self.contacts.filter(eve_entity_id__in=contact_ids).values_list(
                "pk", flat=True
            )
        )
        contacts = self.contacts.in_bulk(update_contact_pks)
        for contact in contacts.values():
            contact_data = contacts_list.get(contact.eve_entity_id)
            if contact_data:
                contact.is_blocked = contact_data.get("is_blocked")
                contact.is_watched = contact_data.get("is_watched")
                contact.standing = contact_data.get("standing")

        CharacterContact.objects.bulk_update(
            contacts.values(),
            fields=["is_blocked", "is_watched", "standing"],
            batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE,
        )
        self._update_contact_contact_labels(
            contacts_list=contacts_list, contact_ids=contact_ids
        )

    @fetch_token_for_character("esi-contracts.read_character_contracts.v1")
    def update_contract_headers(self, token: Token):
        """update the character's contract headers"""

        contracts_list = self._fetch_contracts_from_esi(token)
        if not contracts_list:
            logger.info("%s: No contracts received from ESI", self)

        existing_ids = set(self.contracts.values_list("contract_id", flat=True))
        incoming_location_ids = {
            obj["start_location_id"]
            for contract_id, obj in contracts_list.items()
            if contract_id not in existing_ids
        }
        incoming_location_ids |= {x["end_location_id"] for x in contracts_list.values()}
        self._preload_all_locations(token=token, incoming_ids=incoming_location_ids)
        with transaction.atomic():
            incoming_ids = set(contracts_list.keys())
            existing_ids = set(self.contracts.values_list("contract_id", flat=True))

            create_ids = incoming_ids.difference(existing_ids)
            if create_ids:
                self._create_new_contracts(
                    contracts_list=contracts_list, contract_ids=create_ids, token=token
                )

            update_ids = incoming_ids.difference(create_ids)
            if update_ids:
                self._update_existing_contracts(
                    contracts_list=contracts_list, contract_ids=update_ids
                )

    def _fetch_contracts_from_esi(self, token) -> dict:
        logger.info("%s: Fetching contracts from ESI", self)
        contracts_data = esi.client.Contracts.get_characters_character_id_contracts(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(contracts_data, "contracts")

        contracts_list = {
            obj["contract_id"]: obj for obj in contracts_data if "contract_id" in obj
        }
        return contracts_list

    def _create_new_contracts(
        self, contracts_list: dict, contract_ids: set, token: Token
    ) -> None:
        logger.info("%s: Storing %s new contracts", self, len(contract_ids))
        new_contracts = list()
        for contract_id in contract_ids:
            contract_data = contracts_list.get(contract_id)
            if contract_data:
                new_contracts.append(
                    CharacterContract(
                        character=self,
                        contract_id=contract_data.get("contract_id"),
                        acceptor=get_or_create_or_none(
                            "acceptor_id", contract_data, EveEntity
                        ),
                        acceptor_corporation=get_or_create_or_none(
                            "acceptor_corporation_id", contract_data, EveEntity
                        ),
                        assignee=get_or_create_or_none(
                            "assignee_id", contract_data, EveEntity
                        ),
                        availability=CharacterContract.ESI_AVAILABILITY_MAP[
                            contract_data.get("availability")
                        ],
                        buyout=contract_data.get("buyout"),
                        collateral=contract_data.get("collateral"),
                        contract_type=CharacterContract.ESI_TYPE_MAP.get(
                            contract_data.get("type"),
                            CharacterContract.TYPE_UNKNOWN,
                        ),
                        date_accepted=contract_data.get("date_accepted"),
                        date_completed=contract_data.get("date_completed"),
                        date_expired=contract_data.get("date_expired"),
                        date_issued=contract_data.get("date_issued"),
                        days_to_complete=contract_data.get("days_to_complete"),
                        end_location=get_or_none(
                            "end_location_id", contract_data, Location
                        ),
                        for_corporation=contract_data.get("for_corporation"),
                        issuer_corporation=get_or_create_or_none(
                            "issuer_corporation_id", contract_data, EveEntity
                        ),
                        issuer=get_or_create_or_none(
                            "issuer_id", contract_data, EveEntity
                        ),
                        price=contract_data.get("price"),
                        reward=contract_data.get("reward"),
                        start_location=get_or_none(
                            "start_location_id", contract_data, Location
                        ),
                        status=CharacterContract.ESI_STATUS_MAP[
                            contract_data.get("status")
                        ],
                        title=contract_data.get("title", ""),
                        volume=contract_data.get("volume"),
                    )
                )

        CharacterContract.objects.bulk_create(
            new_contracts, batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
        )

    def _update_existing_contracts(
        self, contracts_list: dict, contract_ids: set
    ) -> None:
        logger.info("%s: Updating %s contracts", self, len(contract_ids))
        update_contract_pks = list(
            self.contracts.filter(contract_id__in=contract_ids).values_list(
                "pk", flat=True
            )
        )
        contracts = self.contracts.in_bulk(update_contract_pks)
        for contract in contracts.values():
            contract_data = contracts_list.get(contract.contract_id)
            if contract_data:
                contract.acceptor = get_or_create_or_none(
                    "acceptor_id", contract_data, EveEntity
                )
                contract.acceptor_corporation = get_or_create_or_none(
                    "acceptor_corporation_id", contract_data, EveEntity
                )
                contract.date_accepted = contract_data.get("date_accepted")
                contract.date_completed = contract_data.get("date_completed")
                contract.status = CharacterContract.ESI_STATUS_MAP[
                    contract_data.get("status")
                ]

        CharacterContract.objects.bulk_update(
            contracts.values(),
            fields=[
                "acceptor",
                "acceptor_corporation",
                "date_accepted",
                "date_completed",
                "status",
            ],
            batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE,
        )

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
        logger.info(
            "%s, %s: Storing %s contract items",
            self,
            contract.contract_id,
            len(items_data),
        )
        items = [
            CharacterContractItem(
                contract=contract,
                record_id=item.get("record_id"),
                is_included=item.get("is_included"),
                is_singleton=item.get("is_singleton"),
                quantity=item.get("quantity"),
                raw_quantity=item.get("raw_quantity"),
                eve_type=get_or_create_esi_or_none("type_id", item, EveType),
            )
            for item in items_data
            if "record_id" in item
        ]
        with transaction.atomic():
            contract.items.all().delete()
            CharacterContractItem.objects.bulk_create(
                items, batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
            )

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
        with transaction.atomic():
            incoming_ids = set(bids_list.keys())
            existing_ids = set(contract.bids.values_list("bid_id", flat=True))
            create_ids = incoming_ids.difference(existing_ids)
            if not create_ids:
                logger.info(
                    "%s, %s: No new contract bids to add", self, contract.contract_id
                )
                return

            logger.info(
                "%s, %s: Storing %s new contract bids",
                self,
                contract.contract_id,
                len(create_ids),
            )
            bids = [
                CharacterContractBid(
                    contract=contract,
                    bid_id=bid.get("bid_id"),
                    amount=bid.get("amount"),
                    bidder=get_or_create_esi_or_none("bidder_id", bid, EveEntity),
                    date_bid=bid.get("date_bid"),
                )
                for bid_id, bid in bids_list.items()
                if bid_id in create_ids
            ]
            CharacterContractBid.objects.bulk_create(
                bids, batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
            )

    def update_doctrines(self):
        """Checks if character can fly doctrine ships
        and updates results in database
        """
        character_skills = {
            obj["eve_type_id"]: obj["active_skill_level"]
            for obj in self.skills.values("eve_type_id", "active_skill_level")
        }
        with transaction.atomic():
            self.doctrine_ships.all().delete()

            # create empty new objects
            doctrine_ships_qs = DoctrineShip.objects.prefetch_related(
                "skills", "skills__eve_type"
            ).all()
            doctrine_ships_count = doctrine_ships_qs.count()
            if doctrine_ships_count == 0:
                logger.info("%s: No doctrine ships defined", self)
                return

            logger.info("%s: Checking %s doctrine ships", self, doctrine_ships_count)
            doctrine_ships = [
                CharacterDoctrineShipCheck(character=self, ship=ship)
                for ship in doctrine_ships_qs
            ]
            CharacterDoctrineShipCheck.objects.bulk_create(
                doctrine_ships, batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
            )

            # add insufficient skills to objects if any
            obj_pks = list(self.doctrine_ships.values_list("pk", flat=True))
            doctrine_ships = self.doctrine_ships.in_bulk(obj_pks)
            doctrine_ships_by_ship_id = {
                obj.ship_id: obj for obj in doctrine_ships.values()
            }
            for ship in doctrine_ships_qs:
                skills = list()
                for skill in ship.skills.all():
                    eve_type_id = skill.eve_type_id
                    if (
                        eve_type_id not in character_skills
                        or character_skills[eve_type_id] < skill.level
                    ):
                        skills.append(skill)

                if skills:
                    doctrine_ships_by_ship_id[ship.id].insufficient_skills.add(*skills)

    @fetch_token_for_character("esi-clones.read_implants.v1")
    def update_implants(self, token):
        """update the character's implants"""
        logger.info("%s: Fetching implants from ESI", self)
        implants_data = esi.client.Clones.get_characters_character_id_implants(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(implants_data, "implants")

        with transaction.atomic():
            self.implants.all().delete()
            if implants_data:
                implants = list()
                for eve_type_id in implants_data:
                    eve_type, _ = EveType.objects.get_or_create_esi(id=eve_type_id)
                    implants.append(CharacterImplant(character=self, eve_type=eve_type))

                logger.info("%s: Storing %s implants", self, len(implants))
                CharacterImplant.objects.bulk_create(
                    implants, batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
                )

            else:
                logger.info("%s: No implants", self)

    def update_location(self):
        """update the location for the given character"""
        eve_solar_system, location = self.fetch_location()
        if eve_solar_system:
            CharacterLocation.objects.update_or_create(
                character=self, eve_solar_system=eve_solar_system, location=location
            )

    @fetch_token_for_character("esi-characters.read_loyalty.v1")
    def update_loyalty(self, token):
        """syncs the character's loyalty entries"""
        logger.info("%s: Fetching loyalty entries from ESI", self)
        loyalty_entries = esi.client.Loyalty.get_characters_character_id_loyalty_points(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(loyalty_entries, "loyalty")

        with transaction.atomic():
            self.loyalty_entries.all().delete()
            new_entries = [
                CharacterLoyaltyEntry(
                    character=self,
                    corporation=get_or_create_or_none(
                        "corporation_id", entry, EveEntity
                    ),
                    loyalty_points=entry.get("loyalty_points"),
                )
                for entry in loyalty_entries
                if "corporation_id" in entry and "loyalty_points" in entry
            ]
            CharacterLoyaltyEntry.objects.bulk_create(
                new_entries, MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
            )
            EveEntity.objects.bulk_update_new_esi()

    @fetch_token_for_character(
        ["esi-clones.read_clones.v1", "esi-universe.read_structures.v1"]
    )
    def update_jump_clones(self, token: Token):
        """updates the character's jump clones"""
        logger.info("%s: Fetching jump clones from ESI", self)
        jump_clones_info = esi.client.Clones.get_characters_character_id_clones(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(jump_clones_info, "jump_clones")

        # fetch locations ahead of transaction
        if jump_clones_info.get("jump_clones"):
            incoming_location_ids = {
                record["location_id"]
                for record in jump_clones_info["jump_clones"]
                if "location_id" in record
            }
            self._preload_all_locations(token, incoming_location_ids)

        with transaction.atomic():
            self.jump_clones.all().delete()
            if not jump_clones_info.get("jump_clones"):
                logger.info("%s: No jump clones", self)
                return

            jump_clones_list = jump_clones_info.get("jump_clones")
            logger.info("%s: Storing %s jump clones", self, len(jump_clones_list))
            jump_clones = [
                CharacterJumpClone(
                    character=self,
                    jump_clone_id=record.get("jump_clone_id"),
                    location=get_or_none("location_id", record, Location),
                    name=record.get("name") if record.get("name") else "",
                )
                for record in jump_clones_list
            ]
            CharacterJumpClone.objects.bulk_create(
                jump_clones,
                batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE,
            )
            implants = list()
            for jump_clone_info in jump_clones_list:
                if jump_clone_info.get("implants"):
                    for implant in jump_clone_info["implants"]:
                        eve_type, _ = EveType.objects.get_or_create_esi(id=implant)
                        jump_clone = self.jump_clones.get(
                            jump_clone_id=jump_clone_info.get("jump_clone_id")
                        )
                        implants.append(
                            CharacterJumpCloneImplant(
                                jump_clone=jump_clone, eve_type=eve_type
                            )
                        )

            CharacterJumpCloneImplant.objects.bulk_create(
                implants,
                batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE,
            )

    @fetch_token_for_character("esi-mail.read_mail.v1")
    def update_mailing_lists(self, token: Token):
        """update the mailing lists for the given character"""
        logger.info("%s: Fetching mailing lists from ESI", self)
        mailing_lists = esi.client.Mail.get_characters_character_id_mail_lists(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(mailing_lists, "mailing_lists")

        # TODO: Replace delete + create with create + update
        if not mailing_lists:
            logger.info("%s: No mailing lists", self)
            return

        logger.info("%s: Storing %s mailing lists", self, len(mailing_lists))
        with transaction.atomic():
            self.mailing_lists.all().delete()
            new_lists = [
                CharacterMailingList(
                    character=self,
                    list_id=mailing_list.get("mailing_list_id"),
                    name=mailing_list.get("name"),
                )
                for mailing_list in mailing_lists
            ]
            CharacterMailingList.objects.bulk_create(
                new_lists, batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
            )

    @fetch_token_for_character("esi-mail.read_mail.v1")
    def update_mail_labels(self, token: Token):
        """update the mail lables for the given character"""
        mail_labels_list = self._fetch_mail_labels_from_esi(token)
        if not mail_labels_list:
            logger.info("%s: No mail labels", self)
            return

        logger.info("%s: Storing %s mail labels", self, len(mail_labels_list))
        with transaction.atomic():
            incoming_ids = set(mail_labels_list.keys())
            existing_ids = set(self.mail_labels.values_list("label_id", flat=True))
            obsolete_ids = existing_ids.difference(incoming_ids)
            if obsolete_ids:
                self.mail_labels.filter(label_id__in=obsolete_ids).delete()

            create_ids = incoming_ids.difference(existing_ids)
            if create_ids:
                self._create_new_mail_labels(
                    mail_labels_list=mail_labels_list, label_ids=create_ids
                )

            update_ids = incoming_ids.difference(create_ids)
            if update_ids:
                self._update_existing_mail_labels(
                    mail_labels_list=mail_labels_list, label_ids=update_ids
                )

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

    def _create_new_mail_labels(self, mail_labels_list: dict, label_ids: set):
        new_labels = [
            CharacterMailLabel(
                character=self,
                label_id=label.get("label_id"),
                color=label.get("color"),
                name=label.get("name"),
                unread_count=label.get("unread_count"),
            )
            for label_id, label in mail_labels_list.items()
            if label_id in label_ids
        ]
        CharacterMailLabel.objects.bulk_create(
            new_labels, batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
        )

    def _update_existing_mail_labels(self, mail_labels_list: dict, label_ids: set):
        logger.info("%s: Updating %s mail labels", self, len(label_ids))
        update_pks = list(
            self.mail_labels.filter(label_id__in=label_ids).values_list("pk", flat=True)
        )
        labels = CharacterMailLabel.objects.in_bulk(update_pks)
        for label in labels.values():
            record = mail_labels_list.get(label.label_id)
            if record:
                label.name = record.get("name")
                label.color = record.get("color")
                label.unread_count = record.get("unread_count")

        CharacterMailLabel.objects.bulk_update(
            labels.values(),
            fields=["name", "color", "unread_count"],
            batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE,
        )

    @fetch_token_for_character("esi-mail.read_mail.v1")
    def update_mail_headers(self, token: Token):
        mail_headers = self._fetch_mail_headers(token)
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(mail_headers, "mail_headers")

        with transaction.atomic():
            incoming_ids = set(mail_headers.keys())
            existing_ids = set(self.mails.values_list("mail_id", flat=True))

            create_ids = incoming_ids.difference(existing_ids)
            if create_ids:
                self._create_mail_headers(mail_headers, create_ids)

            update_ids = incoming_ids.difference(create_ids)
            if update_ids:
                self._update_mail_headers(mail_headers, update_ids)

            if not create_ids and not update_ids:
                logger.info("%s: No mails", self)

    def _fetch_mail_headers(self, token) -> list:
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

        mail_headers_all_2 = {x["mail_id"]: x for x in mail_headers_all}
        logger.info(
            "%s: Received %s mail headers from ESI", self, len(mail_headers_all_2)
        )
        return mail_headers_all_2

    def _create_mail_headers(self, mail_headers: dict, create_ids) -> None:
        logger.info("%s: Create %s new mail headers", self, len(create_ids))
        mailing_list_ids = set(self.mailing_lists.values_list("list_id", flat=True))
        new_mail_headers_list = {
            mail_info["mail_id"]: mail_info
            for mail_id, mail_info in mail_headers.items()
            if mail_id in create_ids
        }

        # create headers
        new_headers = list()
        for mail_id, header in new_mail_headers_list.items():
            from_id = header.get("from")
            if from_id in mailing_list_ids:
                from_mailing_list = self.mailing_lists.get(list_id=from_id)
                from_entity = None
            else:
                from_entity = get_or_create_or_none("from", header, EveEntity)
                from_mailing_list = None

            new_headers.append(
                CharacterMail(
                    character=self,
                    mail_id=mail_id,
                    from_entity=from_entity,
                    from_mailing_list=from_mailing_list,
                    is_read=bool(header.get("is_read")),
                    subject=header.get("subject", ""),
                    timestamp=header.get("timestamp"),
                )
            )

        CharacterMail.objects.bulk_create(
            new_headers, batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
        )

        # add recipients and labels
        new_recipients = list()
        labels = self.mail_labels.get_all_labels()
        for mail_id, header in new_mail_headers_list.items():
            mail_obj = self.mails.get(mail_id=mail_id)
            for recipient in header.get("recipients"):
                if recipient.get("recipient_type") != "mailing_list":
                    new_recipients.append(
                        CharacterMailRecipient(
                            mail=mail_obj,
                            eve_entity=get_or_create_or_none(
                                "recipient_id", recipient, EveEntity
                            ),
                        )
                    )
                else:
                    recipient_id = recipient.get("recipient_id")
                    if recipient_id and recipient_id in mailing_list_ids:
                        new_recipients.append(
                            CharacterMailRecipient(
                                mail=mail_obj,
                                mailing_list=self.mailing_lists.get(
                                    list_id=recipient_id
                                ),
                            )
                        )
                    else:
                        logger.warning(
                            f"{self}: Unknown mailing list with "
                            f"id {recipient_id} for mail id {mail_obj.mail_id}",
                        )

            self._update_labels_of_mail(mail_obj, header.get("labels"), labels)

        if new_recipients:
            CharacterMailRecipient.objects.bulk_create(
                new_recipients, batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
            )

    def _update_labels_of_mail(
        self,
        mail: "CharacterMail",
        label_ids: List[int],
        labels: List["CharacterMailLabel"],
    ) -> None:
        """Updates the labels of a mail object from a dict"""
        mail.labels.clear()
        if label_ids:
            labels_to_add = list()
            for label_id in label_ids:
                try:
                    labels_to_add.append(labels[label_id])
                except KeyError:
                    logger.info(
                        "%s: Unknown mail label with ID %s for mail %s",
                        self,
                        label_id,
                        mail,
                    )

            mail.labels.add(*labels_to_add)

    def _update_mail_headers(self, mail_headers: dict, update_ids) -> None:
        logger.info("%s: Updating %s mail headers", self, len(update_ids))
        mail_pks = CharacterMail.objects.filter(mail_id__in=update_ids).values_list(
            "pk", flat=True
        )
        labels = self.mail_labels.get_all_labels()
        mails = CharacterMail.objects.in_bulk(mail_pks)
        for mail in mails.values():
            mail_header = mail_headers.get(mail.mail_id)
            if mail_header:
                mail.is_read = bool(mail_header.get("is_read"))
                self._update_labels_of_mail(mail, mail_header.get("labels"), labels)

        CharacterMail.objects.bulk_update(mails.values(), ["is_read"])

    @fetch_token_for_character("esi-mail.read_mail.v1")
    def update_mail_body(self, token: Token, mail: "CharacterMail") -> None:
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
    def update_skill_queue(self, token):
        """update the character's skill queue"""
        logger.info("%s: Fetching skill queue from ESI", self)
        skillqueue = esi.client.Skills.get_characters_character_id_skillqueue(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()
        if MEMBERAUDIT_DEVELOPER_MODE:
            self._store_list_to_disk(skillqueue, "skill_queue")

        # TODO: Replace delete + create with create + update
        with transaction.atomic():
            self.skillqueue.all().delete()
            if skillqueue:
                entries = [
                    CharacterSkillqueueEntry(
                        character=self,
                        eve_type=get_or_create_esi_or_none("skill_id", entry, EveType),
                        finish_date=entry.get("finish_date"),
                        finished_level=entry.get("finished_level"),
                        level_end_sp=entry.get("level_end_sp"),
                        level_start_sp=entry.get("level_start_sp"),
                        queue_position=entry.get("queue_position"),
                        start_date=entry.get("start_date"),
                        training_start_sp=entry.get("training_start_sp"),
                    )
                    for entry in skillqueue
                ]
            else:
                entries = list()

            if entries:
                logger.info("%s: Writing skill queue of size %s", self, len(entries))
                CharacterSkillqueueEntry.objects.bulk_create(
                    entries, batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
                )
            else:
                logger.info("%s: Skill queue is empty", self)

    @fetch_token_for_character("esi-skills.read_skills.v1")
    def update_skills(self, token):
        self._update_skills(token)
        self.update_doctrines()

    def _update_skills(self, token):
        """update the character's skill"""
        skills_list = self._fetch_skills_from_esi(token)
        with transaction.atomic():
            incoming_ids = set(skills_list.keys())
            existing_ids = set(self.skills.values_list("eve_type_id", flat=True))
            obsolete_ids = existing_ids.difference(incoming_ids)
            if obsolete_ids:
                logger.info("%s: Removing %s obsolete skills", self, len(obsolete_ids))
                self.skills.filter(eve_type_id__in=obsolete_ids).delete()

            create_ids = None
            update_ids = None
            if skills_list:
                create_ids = incoming_ids.difference(existing_ids)
                if create_ids:
                    self._create_new_skills(
                        skills_list=skills_list, create_ids=create_ids
                    )

                update_ids = incoming_ids.difference(create_ids)
                if update_ids:
                    self._update_existing_skills(
                        skills_list=skills_list, update_ids=update_ids
                    )

            if not obsolete_ids and not create_ids and not update_ids:
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

    def _create_new_skills(self, skills_list: dict, create_ids: list):
        logger.info("%s: Storing %s new skills", self, len(create_ids))
        skills = [
            CharacterSkill(
                character=self,
                eve_type=get_or_create_esi_or_none("skill_id", skill_info, EveType),
                active_skill_level=skill_info.get("active_skill_level"),
                skillpoints_in_skill=skill_info.get("skillpoints_in_skill"),
                trained_skill_level=skill_info.get("trained_skill_level"),
            )
            for skill_id, skill_info in skills_list.items()
            if skill_id in create_ids
        ]
        CharacterSkill.objects.bulk_create(
            skills, batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
        )

    def _update_existing_skills(self, skills_list: dict, update_ids: list):
        logger.info("%s: Updating %s skills", self, len(update_ids))
        update_pks = list(
            self.skills.filter(eve_type_id__in=update_ids).values_list("pk", flat=True)
        )
        skills = CharacterSkill.objects.in_bulk(update_pks)
        for skill in skills.values():
            skill_info = skills_list.get(skill.eve_type_id)
            if skill_info:
                skill.active_skill_level = skill_info.get("active_skill_level")
                skill.skillpoints_in_skill = skill_info.get("skillpoints_in_skill")
                skill.trained_skill_level = skill_info.get("trained_skill_level")

        CharacterSkill.objects.bulk_update(
            skills.values(),
            fields=[
                "active_skill_level",
                "skillpoints_in_skill",
                "trained_skill_level",
            ],
            batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE,
        )

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

        entries_list = {x["id"]: x for x in journal if "id" in x}

        with transaction.atomic():
            incoming_ids = set(entries_list.keys())
            existing_ids = set(self.wallet_journal.values_list("entry_id", flat=True))
            create_ids = incoming_ids.difference(existing_ids)
            if not create_ids:
                logger.info("%s: No new wallet journal entries", self)
                return

            logger.info(
                "%s: Adding %s new wallet journal entries", self, len(create_ids)
            )
            entries = [
                CharacterWalletJournalEntry(
                    character=self,
                    entry_id=entry_id,
                    amount=row.get("amount"),
                    balance=row.get("balance"),
                    context_id=row.get("context_id"),
                    context_id_type=(
                        CharacterWalletJournalEntry.match_context_type_id(
                            row.get("context_id_type")
                        )
                    ),
                    date=row.get("date"),
                    description=row.get("description"),
                    first_party=get_or_create_or_none("first_party_id", row, EveEntity),
                    ref_type=row.get("ref_type"),
                    second_party=get_or_create_or_none(
                        "second_party_id", row, EveEntity
                    ),
                    tax=row.get("tax"),
                    tax_receiver=row.get("tax_receiver"),
                )
                for entry_id, row in entries_list.items()
                if entry_id in create_ids
            ]
            CharacterWalletJournalEntry.objects.bulk_create(
                entries, batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
            )
            EveEntity.objects.bulk_update_new_esi()

    @fetch_token_for_character(
        ["esi-location.read_location.v1", "esi-universe.read_structures.v1"]
    )
    def fetch_location(self, token) -> Optional[dict]:
        logger.info("%s: Fetching location from ESI", self)
        if not is_esi_online():
            return None, None

        location_info = esi.client.Location.get_characters_character_id_location(
            character_id=self.character_ownership.character.character_id,
            token=token.valid_access_token(),
        ).results()

        solar_system, _ = EveSolarSystem.objects.get_or_create_esi(
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

        return solar_system, location

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
            "esi-characters.read_blueprints.v1",
            "esi-characters.read_contacts.v1",
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
            "esi-industry.read_character_jobs.v1",
            "esi-industry.read_character_mining.v1",
            "esi-location.read_location.v1",
            "esi-location.read_online.v1",
            "esi-location.read_ship_type.v1",
            "esi-mail.read_mail.v1",
            "esi-markets.read_character_orders.v1",
            "esi-markets.structure_markets.v1",
            "esi-planets.manage_planets.v1",
            "esi-search.search_structures.v1",
            "esi-skills.read_skillqueue.v1",
            "esi-skills.read_skills.v1",
            "esi-universe.read_structures.v1",
            "esi-wallet.read_character_wallet.v1",
        ]

    @classmethod
    def section_method_name(cls, section: str) -> str:
        if section not in {obj[0] for obj in cls.UPDATE_SECTION_CHOICES}:
            raise ValueError(f"Unknown section: {section}")

        return f"update_{section}"

    @classmethod
    def section_display_name(cls, section: str) -> str:
        for short_name, long_name in cls.UPDATE_SECTION_CHOICES:
            if short_name == section:
                return long_name

        raise ValueError(f"Unknown section: {section}")


class CharacterAsset(models.Model):
    """An Eve Online asset belonging to a Character"""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="assets"
    )
    item_id = models.BigIntegerField(validators=[MinValueValidator(0)])

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

    eve_type = models.ForeignKey(EveType, on_delete=models.CASCADE)
    is_blueprint_copy = models.BooleanField(default=None, null=True, db_index=True)
    is_singleton = models.BooleanField()
    location_flag = models.CharField(max_length=NAMES_MAX_LENGTH)
    name = models.CharField(max_length=NAMES_MAX_LENGTH, default="")
    quantity = models.PositiveIntegerField()

    objects = CharacterAssetManager()

    class Meta:
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
    def group_display(self) -> str:
        """group of this asset to be displayed to user"""
        return self.eve_type.name if self.name else self.eve_type.eve_group.name


"""
class CharacterAssetPosition(models.Model):
   # Location of an asset

    asset = models.OneToOneField(
        CharacterAsset,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="position",
    )
    x = models.FloatField()
    y = models.FloatField()
    z = models.FloatField()
"""


class CharacterContactLabel(models.Model):
    """An Eve Online contact label belonging to a Character"""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="contact_labels"
    )
    label_id = models.BigIntegerField(validators=[MinValueValidator(0)])
    name = models.CharField(max_length=NAMES_MAX_LENGTH)

    class Meta:
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
    eve_entity = models.ForeignKey(EveEntity, on_delete=models.CASCADE)

    is_blocked = models.BooleanField(default=None, null=True)
    is_watched = models.BooleanField(default=None, null=True)
    standing = models.FloatField()
    labels = models.ManyToManyField(CharacterContactLabel, related_name="contacts")

    class Meta:
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
        related_name="acceptor_character_contracts",
        help_text="Who will accept the contract if character",
    )
    acceptor_corporation = models.ForeignKey(
        EveEntity,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        related_name="acceptor_corporation_contracts",
        help_text="corporation of acceptor",
    )
    assignee = models.ForeignKey(
        EveEntity,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        related_name="assignee_character_contracts",
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
        EveEntity,
        on_delete=models.CASCADE,
        related_name="issuer_corporation_contracts",
    )
    issuer = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, related_name="issuer_character_contracts"
    )
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

    class Meta:
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
    bidder = models.ForeignKey(EveEntity, on_delete=models.CASCADE)
    date_bid = models.DateTimeField()

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
    eve_type = models.ForeignKey(EveType, on_delete=models.CASCADE)

    objects = CharacterContractItemManager()

    def __str__(self) -> str:
        return f"{self.contract}-{self.record_id}"

    @property
    def is_bpo(self) -> bool:
        return self.raw_quantity == -2


class CharacterCorporationHistory(models.Model):
    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="corporation_history"
    )
    record_id = models.PositiveIntegerField(db_index=True)

    corporation = models.ForeignKey(EveEntity, on_delete=models.CASCADE)
    is_deleted = models.BooleanField(null=True, default=None, db_index=True)
    start_date = models.DateTimeField(db_index=True)

    class Meta:
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
        related_name="owner_alliances",
    )
    birthday = models.DateTimeField()
    corporation = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, related_name="owner_corporations"
    )
    description = models.TextField()
    eve_ancestry = models.ForeignKey(
        EveAncestry, on_delete=models.SET_DEFAULT, default=None, null=True
    )
    eve_bloodline = models.ForeignKey(EveBloodline, on_delete=models.CASCADE)
    eve_faction = models.ForeignKey(
        EveFaction, on_delete=models.SET_DEFAULT, default=None, null=True
    )
    eve_race = models.ForeignKey(EveRace, on_delete=models.CASCADE)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    name = models.CharField(max_length=NAMES_MAX_LENGTH)
    security_status = models.FloatField(default=None, null=True)
    title = models.TextField()

    def __str__(self) -> str:
        return str(self.character)

    @property
    def description_plain(self) -> str:
        """returns the description without tags"""
        return eve_xml_to_html(self.description)


class CharacterDoctrineShipCheck(models.Model):
    """Whether this character can fly this doctrine ship"""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="doctrine_ships"
    )
    ship = models.ForeignKey("DoctrineShip", on_delete=models.CASCADE)

    insufficient_skills = models.ManyToManyField("DoctrineShipSkill")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["character", "ship"],
                name="functional_pk_characterdoctrineshipcheck",
            )
        ]

    def __str__(self) -> str:
        return f"{self.character}-{self.ship}"

    @property
    def can_fly(self) -> bool:
        return self.insufficient_skills.count() == 0


class CharacterImplant(models.Model):
    """Implant of a character"""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="implants"
    )
    eve_type = models.ForeignKey(EveType, on_delete=models.CASCADE)

    class Meta:
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

    eve_solar_system = models.ForeignKey(EveSolarSystem, on_delete=models.CASCADE)
    location = models.ForeignKey(
        Location, on_delete=models.SET_DEFAULT, default=None, null=True
    )

    def __str__(self) -> str:
        return str(f"{self.character}-{self.eve_solar_system}")


class CharacterLoyaltyEntry(models.Model):
    """Loyalty entry for a character"""

    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name="loyalty_entries",
    )
    corporation = models.ForeignKey(EveEntity, on_delete=models.CASCADE)

    loyalty_points = models.PositiveIntegerField()

    class Meta:
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

    class Meta:
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
    eve_type = models.ForeignKey(EveType, on_delete=models.CASCADE)

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

    from_entity = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, null=True, default=None
    )
    from_mailing_list = models.ForeignKey(
        "CharacterMailingList",
        on_delete=models.CASCADE,
        null=True,
        default=None,
        blank=True,
    )
    is_read = models.BooleanField(null=True, default=None, db_index=True)
    subject = models.CharField(max_length=255, default="")
    body = models.TextField()
    timestamp = models.DateTimeField(null=True, default=None)
    labels = models.ManyToManyField("CharacterMailLabel", related_name="mails")

    class Meta:
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


class CharacterMailingList(models.Model):
    """Mailing list of a character"""

    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name="mailing_lists",
        help_text="character this mailling list belongs to",
    )
    list_id = models.PositiveIntegerField(db_index=True)
    name = models.CharField(max_length=254)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["character", "list_id"],
                name="functional_pk_charactermailinglist",
            )
        ]

    def __str__(self) -> str:
        return self.name


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
        constraints = [
            models.UniqueConstraint(
                fields=["character", "label_id"],
                name="functional_pk_charactermaillabel",
            )
        ]

    def __str__(self) -> str:
        return self.name


class CharacterMailRecipient(models.Model):
    """Mail recipient used in a mail"""

    mail = models.ForeignKey(
        CharacterMail, on_delete=models.CASCADE, related_name="recipients"
    )
    eve_entity = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, default=None, null=True
    )
    mailing_list = models.ForeignKey(
        CharacterMailingList,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
    )

    def __str__(self) -> str:
        return self.mailing_list.name if self.mailing_list else self.eve_entity.name


class CharacterMailUnreadCount(models.Model):
    """Wallet balance of a character"""

    character = models.OneToOneField(
        Character,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="unread_mail_count",
    )
    total = models.PositiveIntegerField()


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

    def __str__(self) -> str:
        return str(self.character)


class CharacterSkill(models.Model):
    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="skills"
    )
    eve_type = models.ForeignKey(EveType, on_delete=models.CASCADE)

    active_skill_level = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    skillpoints_in_skill = models.BigIntegerField(validators=[MinValueValidator(0)])
    trained_skill_level = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )

    class Meta:
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
    total = models.BigIntegerField(validators=[MinValueValidator(0)])
    unallocated = models.PositiveIntegerField(default=None, null=True)


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
    eve_type = models.ForeignKey(EveType, on_delete=models.CASCADE)
    start_date = models.DateTimeField(default=None, null=True)
    training_start_sp = models.PositiveIntegerField(default=None, null=True)

    class Meta:
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


class CharacterUpdateStatus(models.Model):
    """Update status for a character"""

    character = models.ForeignKey(
        Character, on_delete=models.CASCADE, related_name="update_status_set"
    )

    section = models.CharField(
        max_length=64, choices=Character.UPDATE_SECTION_CHOICES, db_index=True
    )
    is_success = models.BooleanField(db_index=True)
    error_message = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["character", "section"],
                name="functional_pk_charactersyncstatus",
            )
        ]

    def __str__(self) -> str:
        return f"{self.character}-{self.section}"


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
    entry_id = models.BigIntegerField(validators=[MinValueValidator(0)])
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
    context_id = models.BigIntegerField(default=None, null=True)
    context_id_type = models.CharField(max_length=3, choices=CONTEXT_ID_CHOICES)
    date = models.DateTimeField()
    description = models.TextField()
    first_party = models.ForeignKey(
        EveEntity,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        related_name="wallet_journal_entry_first_party_set",
    )
    reason = models.TextField()
    ref_type = models.CharField(max_length=64)
    second_party = models.ForeignKey(
        EveEntity,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        related_name="wallet_journal_entry_second_party_set",
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
        related_name="wallet_journal_entry_tax_receiver_set",
    )

    class Meta:
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


class Doctrine(models.Model):
    """A doctrine"""

    name = models.CharField(max_length=NAMES_MAX_LENGTH, unique=True)
    description = models.TextField(blank=True)
    ships = models.ManyToManyField(
        "DoctrineShip", related_name="doctrines", verbose_name="doctrine ships"
    )
    is_active = models.BooleanField(
        default=True, db_index=True, help_text="Whether this doctrine is in active use"
    )

    def __str__(self) -> str:
        return str(self.name)


class DoctrineShip(models.Model):
    """A ship for doctrines"""

    name = models.CharField(max_length=NAMES_MAX_LENGTH, unique=True)
    ship_type = models.ForeignKey(
        EveType, on_delete=models.SET_DEFAULT, default=None, null=True, blank=True
    )
    is_visible = models.BooleanField(
        default=True,
        db_index=True,
        help_text=(
            "Non visible doctrine ships are not shown to users "
            "on their character sheet and used for reporting only."
        ),
    )

    def __str__(self) -> str:
        return str(self.name)


class DoctrineShipSkill(models.Model):
    """A required skill for a doctrine"""

    ship = models.ForeignKey(
        DoctrineShip, on_delete=models.CASCADE, related_name="skills"
    )
    eve_type = models.ForeignKey(
        EveType, on_delete=models.CASCADE, verbose_name="skill"
    )

    level = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Minimum required skill level",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ship", "eve_type"],
                name="functional_pk_doctrineskill",
            )
        ]

    def __str__(self) -> str:
        return f"{self.ship}-{self.eve_type}"
