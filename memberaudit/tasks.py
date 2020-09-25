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
            owner.sync_mailinglists()
            owner.sync_mails()
            owner.last_sync = now()
            owner.last_error = None
            owner.save()
        except Exception as ex:
            error = f"Unexpected error ocurred: {type(ex).__name__}"
            logger.exception(add_prefix(error))
            owner.last_error = error
            owner.save()
            raise ex
