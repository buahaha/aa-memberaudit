from celery import shared_task

from bravado.exception import HTTPUnauthorized, HTTPForbidden
from esi.models import Token

from django.core.cache import cache

from allianceauth.services.hooks import get_extension_logger
from allianceauth.services.tasks import QueueOnce

from . import __title__
from .models import Character, CharacterUpdateStatus, Location

from .utils import LoggerAddTag


logger = LoggerAddTag(get_extension_logger(__name__), __title__)

DEFAULT_TASK_PRIORITY = 6
HIGHER_TASK_PRIORITY = 5
ESI_ERROR_LIMIT = 50
ESI_TIMEOUT_ONCE_ERROR_LIMIT_REACHED = 60
LOCATION_ESI_ERRORS_CACHE_KEY = "MEMBERAUDIT_LOCATION_ESI_ERRORS"


def _load_character(character_pk: int) -> Character:
    try:
        return Character.objects.get(pk=character_pk)
    except Character.DoesNotExist:
        raise Character.DoesNotExist(
            "Requested character with pk {} not registered".format(character_pk)
        )


@shared_task
def update_character_section(character_pk: int, section: str) -> None:
    character = _load_character(character_pk)
    try:
        getattr(character, Character.section_method_name(section))()
        CharacterUpdateStatus.objects.create(
            character=character, section=section, is_success=True
        )
    except Exception as ex:
        error_message = f"{repr(ex)}"
        logger.error(
            "%s: %s: Error ocurred: %s",
            character,
            section,
            error_message,
            exc_info=True,
        )
        CharacterUpdateStatus.objects.create(
            character=character,
            section=section,
            is_success=False,
            error_message=error_message,
        )
        raise ex


@shared_task
def update_character(character_pk: int, has_priority=False) -> None:
    """update all data for a character from ESI"""

    character = _load_character(character_pk)
    logger.info("%s: Starting character update", character)
    character.update_status_set.all().delete()
    task_priority = HIGHER_TASK_PRIORITY if has_priority else DEFAULT_TASK_PRIORITY
    for section, _ in Character.UPDATE_SECTION_CHOICES:
        update_character_section.apply_async(
            kwargs={
                "character_pk": character.pk,
                "section": section,
            },
            priority=task_priority,
        )


@shared_task
def update_all_characters() -> None:
    for character in Character.objects.all():
        update_character.apply_async(
            kwargs={"character_pk": character.pk}, priority=DEFAULT_TASK_PRIORITY
        )


@shared_task(bind=True, base=QueueOnce, once={"keys": ["id"]}, max_retries=None)
def update_location_esi(self, id: int, token_pk: int):
    """Updates a location object from ESI
    and defers itself if the ESI error limit for locations as been exceeded
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
            Location.objects.update_or_create_esi(id, token)
        except (HTTPUnauthorized, HTTPForbidden):
            try:
                cache.incr(LOCATION_ESI_ERRORS_CACHE_KEY)
            except ValueError:
                cache.add(key=LOCATION_ESI_ERRORS_CACHE_KEY, value=1)
    else:
        logger.info("Location #%s: Error limit reached. Defering task", id)
        raise self.retry(countdown=ESI_TIMEOUT_ONCE_ERROR_LIMIT_REACHED)
