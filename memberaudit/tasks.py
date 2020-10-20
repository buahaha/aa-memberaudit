from celery import shared_task, chain

from bravado.exception import HTTPUnauthorized, HTTPForbidden
from esi.models import Token
from eveuniverse.models import EveEntity

from django.core.cache import cache

from allianceauth.services.hooks import get_extension_logger
from allianceauth.services.tasks import QueueOnce

from . import __title__
from .app_settings import MEMBERAUDIT_TASKS_TIME_LIMIT
from .models import (
    Character,
    CharacterContract,
    CharacterMail,
    CharacterUpdateStatus,
    Location,
    is_esi_online,
)

from .utils import LoggerAddTag


logger = LoggerAddTag(get_extension_logger(__name__), __title__)

DEFAULT_TASK_PRIORITY = 6
ESI_ERROR_LIMIT = 50
ESI_TIMEOUT_ONCE_ERROR_LIMIT_REACHED = 60
LOCATION_ESI_ERRORS_CACHE_KEY = "MEMBERAUDIT_LOCATION_ESI_ERRORS"


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_all_characters() -> None:
    """Start the update of all registered characters"""
    if not is_esi_online():
        logger.info(
            "ESI is currently offline. Can not start character update. Aborting"
        )
        return

    for character in Character.objects.all():
        update_character.apply_async(
            kwargs={"character_pk": character.pk}, priority=DEFAULT_TASK_PRIORITY
        )


# Main character update tasks


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character(character_pk: int) -> None:
    """Start respective update tasks for all sections of a character"""
    character = Character.objects.get(pk=character_pk)
    logger.info("%s: Starting character update", character)
    sections = {x[0] for x in Character.UPDATE_SECTION_CHOICES}.difference(
        {
            Character.UPDATE_SECTION_MAILS,
            Character.UPDATE_SECTION_CONTACTS,
            Character.UPDATE_SECTION_CONTRACTS,
        }
    )
    for section in sections:
        update_character_section.apply_async(
            kwargs={
                "character_pk": character.pk,
                "section": section,
            },
            priority=DEFAULT_TASK_PRIORITY,
        )

    update_character_mails.apply_async(
        kwargs={"character_pk": character.pk},
        priority=DEFAULT_TASK_PRIORITY,
    )
    update_character_contacts.apply_async(
        kwargs={"character_pk": character.pk},
        priority=DEFAULT_TASK_PRIORITY,
    )
    update_character_contracts.apply_async(
        kwargs={"character_pk": character.pk},
        priority=DEFAULT_TASK_PRIORITY,
    )


# Update sections


@shared_task(base=QueueOnce, time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character_section(character_pk: int, section: str) -> None:
    """Task that updates the section of a character"""
    character = Character.objects.get(pk=character_pk)
    character.update_status_set.filter(section=section).delete()
    logger.info("%s: Updating %s", character, Character.section_display_name(section))
    _character_update_with_error_logging(
        character, section, getattr(character, Character.section_method_name(section))
    )
    _log_character_update_success(character, section)


def _character_update_with_error_logging(
    character: Character, section: str, method: object, *args, **kwargs
):
    """Allows catching and logging of any exceptions occuring
    during an character update
    """
    try:
        method(*args, **kwargs)
    except Exception as ex:
        error_message = f"{type(ex).__name__}: {str(ex)}"
        logger.error(
            "%s: %s: Error ocurred: %s",
            character,
            Character.section_display_name(section),
            error_message,
            exc_info=True,
        )
        CharacterUpdateStatus.objects.update_or_create(
            character=character,
            section=section,
            defaults={
                "is_success": False,
                "error_message": error_message,
            },
        )
        raise ex


def _log_character_update_success(character: Character, section: str):
    """Logs character update success for a section"""
    logger.info(
        "%s: %s update completed", character, Character.section_display_name(section)
    )
    CharacterUpdateStatus.objects.update_or_create(
        character=character, section=section, defaults={"is_success": True}
    )


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_unresolved_eve_entities(
    character_pk: int, section: str, last_in_chain: bool = False
) -> None:
    """Bulk resolved all unresolved EveEntity objects in database and logs errors to respective section

    Optionally logs success for given update section
    """
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character, section, EveEntity.objects.bulk_update_new_esi
    )
    if last_in_chain:
        _log_character_update_success(character, section)


# Special tasks for updating mail section


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character_mails(character_pk: int) -> None:
    """Main task for updating mails of a character"""
    character = Character.objects.get(pk=character_pk)
    section = Character.UPDATE_SECTION_MAILS
    character.update_status_set.filter(section=section).delete()
    logger.info("%s: Updating %s", character, Character.section_display_name(section))
    chain(
        update_character_mailing_lists.si(character.pk),
        update_character_mail_labels.si(character.pk),
        update_character_mail_headers.si(character.pk),
        update_character_mail_bodies.si(character.pk),
        update_unresolved_eve_entities.si(character.pk, section),
    ).apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character_mailing_lists(character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character, Character.UPDATE_SECTION_MAILS, character.update_mailing_lists
    )


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character_mail_labels(character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character, Character.UPDATE_SECTION_MAILS, character.update_mail_labels
    )


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character_mail_headers(character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character, Character.UPDATE_SECTION_MAILS, character.update_mail_headers
    )


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_mail_body_esi(character_pk: int, mail_pk: int):
    """Task for updating the body of a mail from ESI"""
    character = Character.objects.get(pk=character_pk)
    mail = CharacterMail.objects.get(pk=mail_pk)
    _character_update_with_error_logging(
        character, Character.UPDATE_SECTION_MAILS, character.update_mail_body, mail
    )


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character_mail_bodies(character_pk: int) -> None:
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
    _log_character_update_success(character, Character.UPDATE_SECTION_MAILS)


# special tasks for updating contacts


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character_contacts(character_pk: int) -> None:
    """Main task for updating contacts of a character"""
    character = Character.objects.get(pk=character_pk)
    section = Character.UPDATE_SECTION_CONTACTS
    character.update_status_set.filter(section=section).delete()
    logger.info("%s: Updating %s", character, Character.section_display_name(section))
    chain(
        update_character_contact_labels.si(character.pk),
        update_character_contacts_2.si(character.pk),
        update_unresolved_eve_entities.si(character.pk, section, last_in_chain=True),
    ).apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character_contact_labels(character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character, Character.UPDATE_SECTION_CONTACTS, character.update_contact_labels
    )


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character_contacts_2(character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character, Character.UPDATE_SECTION_CONTACTS, character.update_contacts
    )


# special tasks for updating contracts


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character_contracts(character_pk: int) -> None:
    """Main task for updating contracts of a character"""
    character = Character.objects.get(pk=character_pk)
    section = Character.UPDATE_SECTION_CONTRACTS
    character.update_status_set.filter(section=section).delete()
    logger.info("%s: Updating %s", character, Character.section_display_name(section))
    chain(
        update_character_contract_headers.si(character.pk),
        update_character_contracts_items.si(character.pk),
        update_character_contracts_bids.si(character.pk),
        update_unresolved_eve_entities.si(character.pk, section, last_in_chain=True),
    ).apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character_contract_headers(character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character, Character.UPDATE_SECTION_CONTRACTS, character.update_contract_headers
    )


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character_contracts_items(character_pk: int) -> None:
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
            update_contract_items_esi(
                character_pk=character.pk, contract_pk=contract_pk
            )

    else:
        logger.info("%s: No items to update", character)


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_contract_items_esi(character_pk: int, contract_pk: int):
    """Task for updating the items of a contract from ESI"""
    character = Character.objects.get(pk=character_pk)
    contract = CharacterContract.objects.get(pk=contract_pk)
    character.update_contract_items(contract)


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character_contracts_bids(character_pk: int) -> None:
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
            update_contract_bids_esi(character_pk=character.pk, contract_pk=contract_pk)

    else:
        logger.info("%s: No bids to update", character)


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_contract_bids_esi(character_pk: int, contract_pk: int):
    """Task for updating the bids of a contract from ESI"""
    character = Character.objects.get(pk=character_pk)
    contract = CharacterContract.objects.get(pk=contract_pk)
    character.update_contract_bids(contract)


# Tasks for Location objects


@shared_task(
    bind=True,
    base=QueueOnce,
    once={"keys": ["id"]},
    max_retries=None,
    time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT,
)
def update_structure_esi(self, id: int, token_pk: int):
    """Updates a structure object from ESI
    and retries later if the ESI error limit for structures has been reached
    """
    try:
        token = Token.objects.get(pk=token_pk)
    except Token.DoesNotExist:
        raise Token.DoesNotExist(
            f"Location #{id}: Requested token with pk {token_pk} does not exist"
        )

    errors_count = cache.get(key=LOCATION_ESI_ERRORS_CACHE_KEY)
    if not errors_count or errors_count < ESI_ERROR_LIMIT:
        try:
            Location.objects.structure_update_or_create_esi(id, token)
        except (HTTPUnauthorized, HTTPForbidden):
            try:
                cache.incr(LOCATION_ESI_ERRORS_CACHE_KEY)
            except ValueError:
                cache.add(key=LOCATION_ESI_ERRORS_CACHE_KEY, value=1)
    else:
        logger.info("Location #%s: Error limit reached. Defering task", id)
        raise self.retry(countdown=ESI_TIMEOUT_ONCE_ERROR_LIMIT_REACHED)
