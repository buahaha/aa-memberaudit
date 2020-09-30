from celery import shared_task

from django.contrib.auth.models import User
from django.utils.timezone import now

from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .models import Character

from .utils import LoggerAddTag, make_logger_prefix


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


@shared_task
def update_character(character_pk: int, user_pk: int = None) -> None:
    """update all data for a character from ESI"""
    try:
        character = Character.objects.get(pk=character_pk)
    except Character.DoesNotExist:
        raise Character.DoesNotExist(
            "Requested character with pk {} not registered".format(character_pk)
        )
    add_prefix = make_logger_prefix(character)
    logger.info(add_prefix("Starting character update"))
    try:
        user = User.objects.get(pk=user_pk)
    except User.DoesNotExist:
        user = None
    try:
        character.last_sync = now()
        character.last_error = ""
        character.save()
        character.update_character_details()
        character.update_corporation_history()
        character.update_skills()
        character.update_wallet_balance()
        character.update_wallet_journal()
        character.update_mailinglists()
        character.update_mails()
        if user:
            character.notify_user_about_last_sync(user)

    except Exception as ex:
        error = f"Unexpected error ocurred: {type(ex).__name__}"
        logger.error(add_prefix(error), exc_info=True)
        character.last_error = error
        character.save()
        if user:
            character.notify_user_about_last_sync(user)
        raise ex

    logger.info(add_prefix("Character update completed"))


@shared_task
def update_all_characters() -> None:
    for character in Character.objects.all():
        update_character.delay(character_pk=character.pk)
