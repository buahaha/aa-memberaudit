from celery import shared_task

from bravado.exception import HTTPUnauthorized, HTTPForbidden
from esi.models import Token

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


@shared_task(base=QueueOnce, time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character_section(character_pk: int, section: str) -> None:
    """Task that updates the section of a character"""
    character = Character.objects.get(pk=character_pk)
    character.update_status_set.filter(section=section).delete()
    logger.info("%s: Updating %s", character, Character.section_display_name(section))
    try:
        getattr(character, Character.section_method_name(section))()
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

    else:
        logger.info(
            "%s: %s update completed",
            character,
            Character.section_display_name(section),
        )
        CharacterUpdateStatus.objects.update_or_create(
            character=character, section=section, defaults={"is_success": True}
        )


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_character(character_pk: int) -> None:
    """Start respective update tasks for all sections of a character"""
    character = Character.objects.get(pk=character_pk)
    logger.info("%s: Starting character update", character)
    for section, _ in Character.UPDATE_SECTION_CHOICES:
        update_character_section.apply_async(
            kwargs={
                "character_pk": character.pk,
                "section": section,
            },
            priority=DEFAULT_TASK_PRIORITY,
        )


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


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_mail_body_esi(character_pk: int, mail_pk: int):
    """Task for updating the body of a mail from ESI"""
    character = Character.objects.get(pk=character_pk)
    mail = CharacterMail.objects.get(pk=mail_pk)
    character.update_mail_body(mail)


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_contract_items_esi(character_pk: int, contract_pk: int):
    """Task for updating the items of a contract from ESI"""
    character = Character.objects.get(pk=character_pk)
    contract = CharacterContract.objects.get(pk=contract_pk)
    character.update_contract_items(contract)


@shared_task(time_limit=MEMBERAUDIT_TASKS_TIME_LIMIT)
def update_contract_bids_esi(character_pk: int, contract_pk: int):
    """Task for updating the bids of a contract from ESI"""
    character = Character.objects.get(pk=character_pk)
    contract = CharacterContract.objects.get(pk=contract_pk)
    character.update_contract_bids(contract)
