import random
from typing import Optional

from celery import shared_task, chain

from bravado.exception import (
    HTTPBadGateway,
    HTTPGatewayTimeout,
    HTTPServiceUnavailable,
)
from esi.models import Token
from eveuniverse.core.esitools import is_esi_online
from eveuniverse.models import EveEntity, EveMarketPrice

from allianceauth.services.hooks import get_extension_logger
from allianceauth.services.tasks import QueueOnce

from . import __title__
from .app_settings import (
    MEMBERAUDIT_TASKS_TIME_LIMIT,
    MEMBERAUDIT_UPDATE_STALE_RING_2,
)
from .helpers import EsiOffline, EsiErrorLimitExceeded
from .models import (
    Character,
    CharacterContract,
    CharacterMail,
    CharacterUpdateStatus,
    Location,
    MailEntity,
)
from .utils import LoggerAddTag


logger = LoggerAddTag(get_extension_logger(__name__), __title__)

DEFAULT_TASK_PRIORITY = 6

# params for all tasks
TASK_DEFAULT_KWARGS = {
    "time_limit": MEMBERAUDIT_TASKS_TIME_LIMIT,
}

# params for tasks that make ESI calls
TASK_ESI_KWARGS = {
    **TASK_DEFAULT_KWARGS,
    **{
        "bind": True,
        "autoretry_for": (
            OSError,
            HTTPBadGateway,
            HTTPGatewayTimeout,
            HTTPServiceUnavailable,
        ),
        "retry_kwargs": {"max_retries": 3},
        "retry_backoff": 30,
    },
}


@shared_task(**TASK_DEFAULT_KWARGS)
def run_regular_updates() -> None:
    """Main task to be run on a regular basis to keep everyting updated and running"""
    if not is_esi_online():
        logger.info(
            "ESI is currently offline. Can not start ESI related tasks. Aborting"
        )
        return

    update_market_prices.apply_async(priority=DEFAULT_TASK_PRIORITY)
    update_all_characters.apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(**TASK_DEFAULT_KWARGS)
def update_all_characters(force_update: bool = False) -> None:
    """Start the update of all registered characters

    Args:
    - force_update: When set to True will always update regardless of stale status
    """
    for character in Character.objects.all():
        update_character.apply_async(
            kwargs={"character_pk": character.pk, "force_update": force_update},
            priority=DEFAULT_TASK_PRIORITY,
        )


# Main character update tasks


@shared_task(**TASK_DEFAULT_KWARGS)
def update_character(character_pk: int, force_update: bool = False) -> bool:
    """Start respective update tasks for all stale sections of a character

    Args:
    - character_pk: PL of character to update
    - force_update: When set to True will always update regardless of stale status

    Returns:
    - True when update was conducted
    - False when no updated was needed
    """
    character = Character.objects.get(pk=character_pk)
    all_sections = set(Character.UpdateSection.values)
    needs_update = force_update
    for section in all_sections:
        needs_update |= character.is_update_section_stale(section)

    if not needs_update:
        logger.info("%s: No update required", character)
        return False

    logger.info(
        "%s: Starting %s character update", character, "forced" if force_update else ""
    )
    sections = all_sections.difference(
        {
            Character.UpdateSection.ASSETS,
            Character.UpdateSection.MAILS,
            Character.UpdateSection.CONTACTS,
            Character.UpdateSection.CONTRACTS,
            Character.UpdateSection.WALLET_JOURNAL,
        }
    )
    for section in sorted(sections):
        if force_update or character.is_update_section_stale(section):
            update_character_section.apply_async(
                kwargs={
                    "character_pk": character.pk,
                    "section": section,
                    "force_update": force_update,
                },
                priority=DEFAULT_TASK_PRIORITY,
            )

    if force_update or character.is_update_section_stale(Character.UpdateSection.MAILS):
        update_character_mails.apply_async(
            kwargs={"character_pk": character.pk},
            priority=DEFAULT_TASK_PRIORITY,
        )
    if force_update or character.is_update_section_stale(
        Character.UpdateSection.CONTACTS
    ):
        update_character_contacts.apply_async(
            kwargs={"character_pk": character.pk, "force_update": force_update},
            priority=DEFAULT_TASK_PRIORITY,
        )
    if force_update or character.is_update_section_stale(
        Character.UpdateSection.CONTRACTS
    ):
        update_character_contracts.apply_async(
            kwargs={"character_pk": character.pk, "force_update": force_update},
            priority=DEFAULT_TASK_PRIORITY,
        )

    if force_update or character.is_update_section_stale(
        Character.UpdateSection.WALLET_JOURNAL
    ):
        update_character_wallet_journal.apply_async(
            kwargs={"character_pk": character.pk},
            priority=DEFAULT_TASK_PRIORITY,
        )

    if force_update or character.is_update_section_stale(
        Character.UpdateSection.ASSETS
    ):
        update_character_assets.apply_async(
            kwargs={"character_pk": character.pk, "force_update": force_update},
            priority=DEFAULT_TASK_PRIORITY,
        )

    return True


# Update sections


@shared_task(**{**TASK_ESI_KWARGS}, **{"base": QueueOnce})
def update_character_section(
    self, character_pk: int, section: str, force_update: bool = False
) -> None:
    """Task that updates the section of a character"""
    character = Character.objects.get(pk=character_pk)
    character.reset_update_section(section=section)
    logger.info(
        "%s: Updating %s", character, Character.UpdateSection.display_name(section)
    )
    update_method = getattr(character, Character.UpdateSection.method_name(section))
    args = [self, character, section, update_method]
    if hasattr(update_method, "force_update"):
        kwargs = {"force_update": force_update}
    else:
        kwargs = {}

    _character_update_with_error_logging(*args, **kwargs)
    _log_character_update_success(character, section)


def _character_update_with_error_logging(
    self, character: Character, section: str, method: object, *args, **kwargs
):
    """Allows catching and logging of any exceptions occuring
    during an character update
    """
    try:
        return method(*args, **kwargs)
    except Exception as ex:
        error_message = f"{type(ex).__name__}: {str(ex)}"
        logger.error(
            "%s: %s: Error ocurred: %s",
            character,
            Character.UpdateSection.display_name(section),
            error_message,
            exc_info=True,
        )
        CharacterUpdateStatus.objects.update_or_create(
            character=character,
            section=section,
            defaults={
                "is_success": False,
                "last_error_message": error_message,
            },
        )
        raise ex


def _log_character_update_success(character: Character, section: str):
    """Logs character update success for a section"""
    logger.info(
        "%s: %s update completed",
        character,
        Character.UpdateSection.display_name(section),
    )
    CharacterUpdateStatus.objects.update_or_create(
        character=character,
        section=section,
        defaults={"is_success": True, "last_error_message": ""},
    )


@shared_task(**TASK_ESI_KWARGS)
def update_unresolved_eve_entities(
    self, character_pk: int, section: str, last_in_chain: bool = False
) -> None:
    """Bulk resolved all unresolved EveEntity objects in database and logs errors to respective section

    Optionally logs success for given update section
    """
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        self, character, section, EveEntity.objects.bulk_update_new_esi
    )
    if last_in_chain:
        _log_character_update_success(character, section)


# Special tasks for updating assets


@shared_task(**TASK_DEFAULT_KWARGS)
def update_character_assets(character_pk: int, force_update: bool = False) -> None:
    """Main tasks for updating the character's assets"""
    character = Character.objects.get(pk=character_pk)
    logger.info(
        "%s: Updating %s",
        character,
        Character.UpdateSection.display_name(Character.UpdateSection.ASSETS),
    )
    character.reset_update_section(section=Character.UpdateSection.ASSETS)
    chain(
        assets_build_list_from_esi.s(character.pk, force_update),
        assets_preload_objects.s(character.pk),
        assets_build_tree.s(character.pk),
    ).apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(**TASK_ESI_KWARGS)
def assets_build_list_from_esi(
    self, character_pk: int, force_update: bool = False
) -> dict:
    """Building asset list"""
    character = Character.objects.get(pk=character_pk)
    asset_list = _character_update_with_error_logging(
        self,
        character,
        Character.UpdateSection.ASSETS,
        character.assets_build_list_from_esi,
        force_update,
    )
    return asset_list


@shared_task(**TASK_ESI_KWARGS)
def assets_preload_objects(self, asset_list: dict, character_pk: int) -> Optional[dict]:
    """Task for preloading asset objects"""
    if asset_list is None:
        return None

    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        self,
        character,
        Character.UpdateSection.ASSETS,
        character.assets_preload_objects,
        asset_list,
    )
    return asset_list


@shared_task(**TASK_ESI_KWARGS)
def assets_build_tree(self, asset_list: dict, character_pk: int) -> None:
    """Building the asset tree"""
    character = Character.objects.get(pk=character_pk)
    if asset_list is not None:
        _character_update_with_error_logging(
            self,
            character,
            Character.UpdateSection.ASSETS,
            character.assets_build_tree,
            asset_list,
        )

    _log_character_update_success(character, Character.UpdateSection.ASSETS)


# Special tasks for updating mail section


@shared_task(**TASK_ESI_KWARGS)
def update_character_mails(self, character_pk: int, force_update: bool = False) -> None:
    """Main task for updating mails of a character"""
    character = Character.objects.get(pk=character_pk)
    section = Character.UpdateSection.MAILS
    logger.info(
        "%s: Updating %s", character, Character.UpdateSection.display_name(section)
    )
    character.reset_update_section(section=section)
    chain(
        update_character_mailing_lists.si(character.pk),
        update_character_mail_labels.si(character.pk),
        update_character_mail_headers.si(character.pk),
        update_character_mail_bodies.si(character.pk),
        update_unresolved_eve_entities.si(character.pk, section),
    ).apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(**TASK_ESI_KWARGS)
def update_character_mailing_lists(self, character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        self, character, Character.UpdateSection.MAILS, character.update_mailing_lists
    )


@shared_task(**TASK_ESI_KWARGS)
def update_character_mail_labels(self, character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        self, character, Character.UpdateSection.MAILS, character.update_mail_labels
    )


@shared_task(**TASK_ESI_KWARGS)
def update_character_mail_headers(
    self, character_pk: int, force_update: bool = False
) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        self,
        character,
        Character.UpdateSection.MAILS,
        character.update_mail_headers,
    )


@shared_task(**TASK_ESI_KWARGS)
def update_mail_body_esi(self, character_pk: int, mail_pk: int):
    """Task for updating the body of a mail from ESI"""
    character = Character.objects.get(pk=character_pk)
    mail = CharacterMail.objects.get(pk=mail_pk)
    _character_update_with_error_logging(
        self,
        character,
        Character.UpdateSection.MAILS,
        character.update_mail_body,
        mail,
    )


@shared_task(**TASK_ESI_KWARGS)
def update_character_mail_bodies(self, character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    mails_without_body_qs = character.mails.filter(body="")
    mails_without_body_count = mails_without_body_qs.count()

    if mails_without_body_count > 0:
        logger.info("%s: Loading %s mailbodies", character, mails_without_body_count)
        for mail in mails_without_body_qs:
            update_mail_body_esi.apply_async(
                kwargs={"character_pk": character.pk, "mail_pk": mail.pk},
                priority=DEFAULT_TASK_PRIORITY,
            )

    # the last task in the chain logs success (if any)
    _log_character_update_success(character, Character.UpdateSection.MAILS)


# special tasks for updating contacts


@shared_task(**TASK_DEFAULT_KWARGS)
def update_character_contacts(character_pk: int, force_update: bool = False) -> None:
    """Main task for updating contacts of a character"""
    character = Character.objects.get(pk=character_pk)
    section = Character.UpdateSection.CONTACTS
    character.reset_update_section(section=section)
    logger.info(
        "%s: Updating %s", character, Character.UpdateSection.display_name(section)
    )
    chain(
        update_character_contact_labels.si(character.pk),
        update_character_contacts_2.si(character.pk, force_update=force_update),
        update_unresolved_eve_entities.si(character.pk, section, last_in_chain=True),
    ).apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(**TASK_ESI_KWARGS)
def update_character_contact_labels(self, character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        self,
        character,
        Character.UpdateSection.CONTACTS,
        character.update_contact_labels,
    )


@shared_task(**TASK_ESI_KWARGS)
def update_character_contacts_2(
    self, character_pk: int, force_update: bool = False
) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        self,
        character,
        Character.UpdateSection.CONTACTS,
        character.update_contacts,
        force_update=force_update,
    )


# special tasks for updating contracts


@shared_task(**TASK_DEFAULT_KWARGS)
def update_character_contracts(character_pk: int, force_update: bool = False) -> None:
    """Main task for updating contracts of a character"""
    character = Character.objects.get(pk=character_pk)
    section = Character.UpdateSection.CONTRACTS
    character.reset_update_section(section=section)
    logger.info(
        "%s: Updating %s", character, Character.UpdateSection.display_name(section)
    )
    chain(
        update_character_contract_headers.si(character.pk, force_update=force_update),
        update_character_contracts_items.si(character.pk),
        update_character_contracts_bids.si(character.pk),
        update_unresolved_eve_entities.si(character.pk, section, last_in_chain=True),
    ).apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(**TASK_ESI_KWARGS)
def update_character_contract_headers(
    self, character_pk: int, force_update: bool = False
) -> bool:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        self,
        character,
        Character.UpdateSection.CONTRACTS,
        character.update_contract_headers,
        force_update=force_update,
    )


@shared_task(**TASK_DEFAULT_KWARGS)
def update_character_contracts_items(character_pk: int):
    """Update items for all contracts of a character"""
    character = Character.objects.get(pk=character_pk)
    contract_pks = set(
        character.contracts.filter(
            contract_type__in=[
                CharacterContract.TYPE_ITEM_EXCHANGE,
                CharacterContract.TYPE_AUCTION,
            ],
            items__isnull=True,
        ).values_list("pk", flat=True)
    )
    if len(contract_pks) > 0:
        logger.info(
            "%s: Starting updating items for %s contracts", character, len(contract_pks)
        )
        for contract_pk in contract_pks:
            update_contract_items_esi.apply_async(
                kwargs={"character_pk": character.pk, "contract_pk": contract_pk},
                priority=DEFAULT_TASK_PRIORITY,
            )

    else:
        logger.info("%s: No items to update", character)


@shared_task(**TASK_ESI_KWARGS)
def update_contract_items_esi(self, character_pk: int, contract_pk: int):
    """Task for updating the items of a contract from ESI"""
    character = Character.objects.get(pk=character_pk)
    contract = CharacterContract.objects.get(pk=contract_pk)
    character.update_contract_items(contract)


@shared_task(**TASK_DEFAULT_KWARGS)
def update_character_contracts_bids(character_pk: int):
    """Update bids for all contracts of a character"""
    character = Character.objects.get(pk=character_pk)
    contract_pks = set(
        character.contracts.filter(
            contract_type__in=[CharacterContract.TYPE_AUCTION],
            status=CharacterContract.STATUS_OUTSTANDING,
        ).values_list("pk", flat=True)
    )
    if len(contract_pks) > 0:
        logger.info(
            "%s: Starting updating bids for %s contracts", character, len(contract_pks)
        )
        for contract_pk in contract_pks:
            update_contract_bids_esi.apply_async(
                kwargs={"character_pk": character.pk, "contract_pk": contract_pk},
                priority=DEFAULT_TASK_PRIORITY,
            )

    else:
        logger.info("%s: No bids to update", character)


@shared_task(**TASK_ESI_KWARGS)
def update_contract_bids_esi(self, character_pk: int, contract_pk: int):
    """Task for updating the bids of a contract from ESI"""
    character = Character.objects.get(pk=character_pk)
    contract = CharacterContract.objects.get(pk=contract_pk)
    character.update_contract_bids(contract)


# special tasks for updating wallet


@shared_task(**TASK_DEFAULT_KWARGS)
def update_character_wallet_journal(character_pk: int) -> None:
    """Main task for updating wallet journal of a character"""
    character = Character.objects.get(pk=character_pk)
    section = Character.UpdateSection.WALLET_JOURNAL
    character.reset_update_section(section=section)
    logger.info(
        "%s: Updating %s", character, Character.UpdateSection.display_name(section)
    )
    chain(
        update_character_wallet_journal_entries.si(character.pk),
        update_unresolved_eve_entities.si(character.pk, section, last_in_chain=True),
    ).apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(**TASK_ESI_KWARGS)
def update_character_wallet_journal_entries(self, character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        self,
        character,
        Character.UpdateSection.WALLET_JOURNAL,
        character.update_wallet_journal,
    )


# Tasks for other objects


@shared_task(**TASK_ESI_KWARGS)
def update_market_prices(self):
    """Update market prices from ESI"""
    EveMarketPrice.objects.update_from_esi(
        minutes_until_stale=MEMBERAUDIT_UPDATE_STALE_RING_2
    )


@shared_task(
    **{**TASK_ESI_KWARGS},
    **{
        "base": QueueOnce,
        "once": {"keys": ["id"], "graceful": True},
        "max_retries": None,
    },
)
def update_structure_esi(self, id: int, token_pk: int):
    """Updates a structure object from ESI
    and retries later if the ESI error limit has already been reached
    """
    try:
        token = Token.objects.get(pk=token_pk)
    except Token.DoesNotExist:
        raise Token.DoesNotExist(
            f"Location #{id}: Requested token with pk {token_pk} does not exist"
        )

    try:
        Location.objects.structure_update_or_create_esi(id, token)
    except EsiOffline:
        logger.warning(
            "Location #%s: ESI appears to be offline. Trying again in 30 minutes.", id
        )
        raise self.retry(countdown=30 * 60 + int(random.uniform(1, 20)))
    except EsiErrorLimitExceeded as ex:
        logger.warning(
            "Location #%s: ESI error limit threshold reached. "
            "Trying again in %s seconds",
            id,
            ex.retry_in,
        )
        raise self.retry(countdown=ex.retry_in)


@shared_task(
    **{**TASK_ESI_KWARGS},
    **{
        "base": QueueOnce,
        "once": {"keys": ["id"], "graceful": True},
        "max_retries": None,
    },
)
def update_mail_entity_esi(self, id: int, category: str = None):
    """Updates a mail entity object from ESI
    and retries later if the ESI error limit has already been reached
    """
    try:
        MailEntity.objects.update_or_create_esi(id=id, category=category)
    except EsiOffline:
        logger.warning(
            "MailEntity #%s: ESI appears to be offline. Trying again in 30 minutes.", id
        )
        raise self.retry(countdown=30 * 60 + int(random.uniform(1, 20)))
    except EsiErrorLimitExceeded as ex:
        logger.warning(
            "MailEntity #%s: ESI error limit threshold reached. "
            "Trying again in %s seconds",
            id,
            ex.retry_in,
        )
        raise self.retry(countdown=ex.retry_in)
