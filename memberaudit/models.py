from django.db import models
from django.core.validators import MinValueValidator

from allianceauth.authentication.models import CharacterOwnership

from .managers import EveEntityManager
from .utils import LoggerAddTag, DATETIME_FORMAT, make_logger_prefix


# Create your models here.

class Memberaudit(models.Model):
    """Meta model for app permissions"""

    class Meta:
        managed = False                         
        default_permissions = ()
        permissions = ( 
            ('basic_access', 'Can access this app'), 
        )


class EveEntity(models.Model):
    """An Eve entity like a corporation or a character"""

    # entity categories supported by this class
    CATEGORY_ALLIANCE = 'alliance'
    CATEGORY_CORPORATION = 'corporation'
    CATEGORY_CHARACTER = 'character'
    CATEGORIES_DEF = [
        (CATEGORY_ALLIANCE, 'Alliance'),
        (CATEGORY_CORPORATION, 'Corporation'),
        (CATEGORY_CHARACTER, 'Character'),
    ]
    
    id = models.IntegerField(        
        primary_key=True,
        validators=[MinValueValidator(0)],
    )
    category = models.CharField(
        max_length=32,
        choices=CATEGORIES_DEF, 
    )
    name = models.CharField(
        max_length=254
    )

    objects = EveEntityManager()

    def __str__(self):
        return self.name


class Owner(models.Model):
    """Character who owns mails or wallet or ... """
    character = models.OneToOneField(
        CharacterOwnership,
        related_name='memberaudit_owner',
        on_delete=models.CASCADE,        
        help_text='character registered to member audit'
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

    def __str__(self):
        return str(self.character)

    @classmethod
    def get_esi_scopes(cls) -> list:
        return [
            'esi-mail.read_mail.v1'
        ]


class MailingList(models.Model):
    """Mailing list of a character"""
    owner = models.ForeignKey(
        Owner,
        on_delete=models.CASCADE,
        help_text='character this mailling list belongs to'
    )
    list_id = models.IntegerField(
        validators=[MinValueValidator(0)],       
    )
    name = models.CharField(
        max_length=254
    )

    class Meta:
        unique_together = (('owner', 'list_id'),)

    def __str__(self):
        return self.name


class Mail(models.Model):
    """Mail of a character"""
    owner = models.ForeignKey(
        Owner,
        on_delete=models.CASCADE,
        help_text='character this mail belongs to'
    )
    mail_id = models.IntegerField(
        null=True, 
        default=None, 
        blank=True,
        validators=[MinValueValidator(0)],
    )
    from_entity = models.ForeignKey(
        EveEntity,
        on_delete=models.CASCADE,
        null=True, 
        default=None, 
        blank=True
    )
    from_mailing_list = models.ForeignKey(
        MailingList,
        on_delete=models.CASCADE,
        null=True, 
        default=None, 
        blank=True
    )
    is_read = models.BooleanField(
        null=True, 
        default=None, 
        blank=True,
    )    
    subject = models.CharField(
        max_length=255,
        null=True, 
        default=None, 
        blank=True
    )
    body = models.TextField(        
        null=True, 
        default=None, 
        blank=True
    )
    timestamp = models.DateTimeField(
        null=True, 
        default=None, 
        blank=True,
    )

    class Meta:
        unique_together = (('owner', 'mail_id'),)

    def __str__(self):
        return str(self.mail_id)


class MailLabels(models.Model):    
    """Mail label used in a mail"""
    mail = models.ForeignKey(
        Mail,
        on_delete=models.CASCADE
    )
    label_id = models.IntegerField(
        validators=[MinValueValidator(0)],
    )
    

    class Meta:
        unique_together = (('mail', 'label_id'),)

    def __str__(self):
        return '{}-{}'.format(
            self.mail,
            self.label_id
        )


class MailRecipient(models.Model):   
    """Mail recipient used in a mail""" 
    mail = models.ForeignKey(
        Mail,
        on_delete=models.CASCADE
    )
    recipient = models.ForeignKey(
        EveEntity,
        on_delete=models.CASCADE
    )
    
    class Meta:
        unique_together = (('mail', 'recipient'),)

    def __str__(self):        
        return '{}-{}'.format(
            self.mail,
            self.recipient
        )