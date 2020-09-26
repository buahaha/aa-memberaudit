import json
from typing import Optional

from django.core.serializers.json import DjangoJSONEncoder
from django.conf import settings
from django.db import models, transaction
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from esi.models import Token
from esi.errors import TokenExpiredError, TokenInvalidError

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.services.hooks import get_extension_logger

from eveuniverse.models import (
    EveAncestry,
    EveBloodline,
    EveEntity,
    EveFaction,
    EveRace,
    EveSolarSystem,
    EveStation,
)
from eveuniverse.providers import esi

from . import __title__
from .app_settings import MEMBERAUDIT_MAX_MAILS
from .managers import OwnerManager
from .utils import LoggerAddTag, make_logger_prefix


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class Memberaudit(models.Model):
    """Meta model for app permissions"""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (("basic_access", "Can access this app"),)


class Owner(models.Model):
    """Character who owns mails or wallet or ... """

    character = models.OneToOneField(
        CharacterOwnership,
        related_name="memberaudit_owner",
        on_delete=models.CASCADE,
        help_text="character registered to member audit",
    )
    last_sync = models.DateTimeField(
        null=True,
        default=None,
        blank=True,
    )
    last_error = models.TextField(
        null=True,
        default=None,
        blank=True,
    )

    objects = OwnerManager()

    def __str__(self):
        return str(self.character)

    def token(self) -> Optional[Token]:
        add_prefix = make_logger_prefix(self)
        token = None

        # abort if character does not have sufficient permissions
        if not self.character.user.has_perm("memberaudit.basic_access"):
            error = "Character does not have sufficient permission to sync"

        else:
            try:
                # get token
                token = (
                    Token.objects.filter(
                        user=self.character.user,
                        character_id=self.character.character.character_id,
                    )
                    .require_scopes(self.get_esi_scopes())
                    .require_valid()
                    .first()
                )
                error = None

            except TokenInvalidError:
                error = "Invalid token"

            except TokenExpiredError:
                error = "Token expired"

            else:
                if not token:
                    error = "Missing token"

        if error:
            logger.error(add_prefix(error))
            self.last_error = error
            self.save()

        if token:
            logger.debug(add_prefix("Using token: {}".format(token)))

        return token

    def sync_character_details(self):
        """syncs the character details for the given owner"""
        # add_prefix = make_logger_prefix(self)
        token = self.token()
        if not token:
            return

        details = esi.client.Character.get_characters_character_id(
            character_id=self.character.character.character_id,
        ).results()
        if details.get("alliance_id"):
            alliance, _ = EveEntity.objects.get_or_create_esi(
                id=details.get("alliance_id")
            )
        else:
            alliance = None

        if details.get("ancestry_id"):
            eve_ancestry, _ = EveAncestry.objects.get_or_create_esi(
                id=details.get("ancestry_id")
            )
        else:
            eve_ancestry = None

        eve_bloodline, _ = EveBloodline.objects.get_or_create_esi(
            id=details.get("bloodline_id")
        )
        corporation, _ = EveEntity.objects.get_or_create_esi(
            id=details.get("corporation_id")
        )
        description = details.get("description") if details.get("description") else ""
        if details.get("faction_id"):
            faction, _ = EveFaction.objects.get_or_create_esi(
                id=details.get("faction_id")
            )
        else:
            faction = None

        if details.get("gender") == "male":
            gender = CharacterDetail.GENDER_MALE
        else:
            gender = CharacterDetail.GENDER_FEMALE

        race, _ = EveRace.objects.get_or_create_esi(id=details.get("race_id"))
        title = details.get("title") if details.get("title") else ""
        CharacterDetail.objects.update_or_create(
            owner=self,
            defaults={
                "alliance": alliance,
                "eve_ancestry": eve_ancestry,
                "birthday": details.get("birthday"),
                "eve_bloodline": eve_bloodline,
                "corporation": corporation,
                "description": description,
                "faction": faction,
                "gender": gender,
                "race": race,
                "security_status": details.get("security_status"),
                "title": title,
            },
        )

    def sync_mailinglists(self):
        """syncs the mailing list for the given owner"""
        add_prefix = make_logger_prefix(self)
        token = self.token()
        if not token:
            return

        mailing_lists = esi.client.Mail.get_characters_character_id_mail_lists(
            character_id=self.character.character.character_id,
            token=token.valid_access_token(),
        ).results()

        logger.info(
            add_prefix("Received {} mailing lists from ESI".format(len(mailing_lists)))
        )

        created_count = 0
        for mailing_list in mailing_lists:
            _, created = MailingList.objects.update_or_create(
                owner=self,
                list_id=mailing_list["mailing_list_id"],
                defaults={"name": mailing_list["name"]},
            )
            if created:
                created_count += 1

        if created_count > 0:
            logger.info(
                add_prefix("Added/Updated {} mailing lists".format(created_count))
            )

    def sync_mails(self):
        add_prefix = make_logger_prefix(self)
        token = self.token()
        if not token:
            return

        # fetch mail headers
        last_mail_id = None
        mail_headers_all = list()
        page = 1

        while True:
            logger.info(
                add_prefix("Fetching mail headers from ESI - page {}".format(page))
            )
            mail_headers = esi.client.Mail.get_characters_character_id_mail(
                character_id=self.character.character.character_id,
                last_mail_id=last_mail_id,
                token=token.valid_access_token(),
            ).results()

            mail_headers_all += mail_headers

            if len(mail_headers) < 50 or len(mail_headers_all) >= MEMBERAUDIT_MAX_MAILS:
                break
            else:
                last_mail_id = min([x["mail_id"] for x in mail_headers])
                page += 1

        logger.info(
            add_prefix(
                "Received {} mail headers from ESI".format(len(mail_headers_all))
            )
        )

        if settings.DEBUG:
            # store to disk (for debugging)
            with open(
                "mail_headers_raw_{}.json".format(
                    self.character.character.character_id
                ),
                "w",
                encoding="utf-8",
            ) as f:
                json.dump(
                    mail_headers_all, f, cls=DjangoJSONEncoder, sort_keys=True, indent=4
                )

        # update IDs from ESI
        ids = set()
        mailing_list_ids = [
            x["list_id"]
            for x in MailingList.objects.filter(owner=self)
            .select_related()
            .values("list_id")
        ]
        for header in mail_headers_all:
            if header["from"] not in mailing_list_ids:
                ids.add(header["from"])
            for recipient in header["recipients"]:
                if recipient["recipient_type"] != "mailing_list":
                    ids.add(recipient["recipient_id"])

        EveEntity.objects.bulk_create_esi(ids)

        logger.info(
            add_prefix(
                "Updating {} mail headers and loading mail bodies".format(
                    len(mail_headers_all)
                )
            )
        )

        # load mail headers
        body_count = 0
        for header in mail_headers_all:
            try:
                with transaction.atomic():
                    try:
                        from_mailing_list = MailingList.objects.get(
                            list_id=header["from"]
                        )
                        from_entity = None
                    except MailingList.DoesNotExist:
                        from_entity, _ = EveEntity.objects.get_or_create_esi(
                            id=header["from"]
                        )
                        from_mailing_list = None

                    mail_obj, _ = Mail.objects.update_or_create(
                        owner=self,
                        mail_id=header["mail_id"],
                        defaults={
                            "from_entity": from_entity,
                            "from_mailing_list": from_mailing_list,
                            "is_read": header["is_read"],
                            "subject": header["subject"],
                            "timestamp": header["timestamp"],
                        },
                    )
                    MailRecipient.objects.filter(mail=mail_obj).delete()
                    for recipient in header["recipients"]:
                        if recipient["recipient_type"] != "mailing_list":
                            recipient, _ = EveEntity.objects.get_or_create_esi(
                                id=recipient["recipient_id"]
                            )
                            MailRecipient.objects.create(
                                mail=mail_obj, recipient=recipient
                            )
                    MailLabels.objects.filter(mail=mail_obj).delete()
                    for label in header["labels"]:
                        MailLabels.objects.create(label_id=label, mail=mail_obj)

                    if mail_obj.body is None:
                        logger.info(
                            add_prefix(
                                "Fetching body from ESI for mail ID {}".format(
                                    mail_obj.mail_id
                                )
                            )
                        )
                        mail = esi.client.Mail.get_characters_character_id_mail_mail_id(
                            character_id=self.character.character.character_id,
                            mail_id=mail_obj.mail_id,
                            token=token.valid_access_token(),
                        ).result()
                        mail_obj.body = mail["body"]
                        mail_obj.save()
                        body_count += 1

            except Exception as ex:
                logger.exception(
                    add_prefix(
                        "Unexpected error ocurred while processing mail {}: {}".format(
                            header["mail_id"], ex
                        )
                    )
                )
        if body_count > 0:
            logger.info("loaded {} mail bodies".format(body_count))

    def fetch_location(self) -> Optional[dict]:
        token = self.token()
        if not token:
            raise Token.DoesNotExist()

        location_info = esi.client.Location.get_characters_character_id_location(
            character_id=self.character.character.character_id,
            token=token.valid_access_token(),
        ).results()

        solar_system, _ = EveSolarSystem.objects.get_or_create_esi(
            id=location_info.get("solar_system_id")
        )
        if location_info.get("station_id"):
            station, _ = EveStation.objects.get_or_create_esi(
                id=location_info.get("station_id")
            )
        else:
            station = None

        return solar_system, station

    @classmethod
    def get_esi_scopes(cls) -> list:
        return ["esi-mail.read_mail.v1", "esi-location.read_location.v1"]


class CharacterDetail(models.Model):
    """Details for a character"""

    GENDER_MALE = "m"
    GENDER_FEMALE = "f"
    GENDER_CHOICES = (
        (GENDER_MALE, _("male")),
        (GENDER_FEMALE, _("female")),
    )
    owner = models.OneToOneField(
        Owner,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="owner_characters_detail",
        help_text="character this mailling list belongs to",
    )
    alliance = models.ForeignKey(
        EveEntity,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        related_name="owner_alliances",
    )
    eve_ancestry = models.ForeignKey(
        EveAncestry, on_delete=models.SET_DEFAULT, default=None, null=True, blank=True
    )
    birthday = models.DateTimeField()
    eve_bloodline = models.ForeignKey(EveBloodline, on_delete=models.CASCADE)
    corporation = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, related_name="owner_corporations"
    )
    description = models.TextField(default="", blank=True)
    faction = models.ForeignKey(
        EveFaction, on_delete=models.SET_DEFAULT, default=None, null=True, blank=True
    )
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    race = models.ForeignKey(EveRace, on_delete=models.CASCADE)
    security_status = models.FloatField(default=None, null=True, blank=True)
    title = models.TextField(default="", blank=True)

    def __str__(self):
        return str(self.owner)

    @property
    def description_plain(self) -> str:
        """returns the description without tags"""
        x = self.description.replace("<br>", "\n")
        x = strip_tags(x)
        x = x.replace("\n", "<br>")
        return mark_safe(x)


class MailingList(models.Model):
    """Mailing list of a character"""

    owner = models.ForeignKey(
        Owner,
        on_delete=models.CASCADE,
        help_text="character this mailling list belongs to",
    )
    list_id = models.PositiveIntegerField()
    name = models.CharField(max_length=254)

    class Meta:
        unique_together = (("owner", "list_id"),)

    def __str__(self):
        return self.name


class Mail(models.Model):
    """Mail of a character"""

    owner = models.ForeignKey(
        Owner, on_delete=models.CASCADE, help_text="character this mail belongs to"
    )
    mail_id = models.PositiveIntegerField(null=True, default=None, blank=True)
    from_entity = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, null=True, default=None, blank=True
    )
    from_mailing_list = models.ForeignKey(
        MailingList, on_delete=models.CASCADE, null=True, default=None, blank=True
    )
    is_read = models.BooleanField(null=True, default=None, blank=True)
    subject = models.CharField(max_length=255, null=True, default=None, blank=True)
    body = models.TextField(null=True, default=None, blank=True)
    timestamp = models.DateTimeField(null=True, default=None, blank=True)

    class Meta:
        unique_together = (("owner", "mail_id"),)

    def __str__(self):
        return str(self.mail_id)


class MailLabels(models.Model):
    """Mail label used in a mail"""

    mail = models.ForeignKey(Mail, on_delete=models.CASCADE)
    label_id = models.PositiveIntegerField()

    class Meta:
        unique_together = (("mail", "label_id"),)

    def __str__(self):
        return "{}-{}".format(self.mail, self.label_id)


class MailRecipient(models.Model):
    """Mail recipient used in a mail"""

    mail = models.ForeignKey(Mail, on_delete=models.CASCADE)
    recipient = models.ForeignKey(EveEntity, on_delete=models.CASCADE)

    class Meta:
        unique_together = (("mail", "recipient"),)

    def __str__(self):
        return "{}-{}".format(self.mail, self.recipient)
