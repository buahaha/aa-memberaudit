from django.db import models

from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .utils import LoggerAddTag


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class MailingListManager(models.Manager):
    pass


class MailManager(models.Manager):
    pass
