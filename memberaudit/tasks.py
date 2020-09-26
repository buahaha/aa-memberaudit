from celery import shared_task

from django.utils.timezone import now

from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .models import Owner

from .utils import LoggerAddTag, make_logger_prefix


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


@shared_task
def sync_owner(owner_pk, force_sync: bool = False) -> None:
    try:
        owner = Owner.objects.get(pk=owner_pk)
    except Owner.DoesNotExist:
        raise Owner.DoesNotExist(
            "Requested character with pk {} not registered".format(owner_pk)
        )
    else:
        add_prefix = make_logger_prefix(owner)
        try:
            owner.sync_character_details()
            owner.sync_corporation_history()
            owner.sync_skills()
            owner.sync_wallet_balance()
            owner.sync_wallet_journal()
            # owner.sync_mailinglists()
            # owner.sync_mails()
            owner.last_sync = now()
            owner.last_error = ""
            owner.save()
            owner.notify_user_about_last_sync()
        except Exception as ex:
            error = f"Unexpected error ocurred: {type(ex).__name__}"
            logger.exception(add_prefix(error))
            owner.last_error = error
            owner.save()
            owner.notify_user_about_last_sync()
            raise ex
