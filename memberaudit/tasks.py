import logging
import json

from celery import shared_task

from django.db import transaction
from django.utils.timezone import now
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder

from esi.clients import esi_client_factory
from esi.errors import TokenExpiredError, TokenInvalidError, TokenError
from esi.models import Token

from .app_settings import MEMBERAUDIT_MAX_MAILS
from .models import *
from .utils import LoggerAddTag, make_logger_prefix, get_swagger_spec_path


logger = LoggerAddTag(logging.getLogger(__name__), __package__)


def _get_token_for_owner(owner: Owner, add_prefix: make_logger_prefix) -> list:        
    """returns a valid token for given owner or an error code"""
    
    token = None
    error = None
    
    # abort if character does not have sufficient permissions
    if not owner.character.user.has_perm(
            'memberaudit.basic_access'
        ):
        error = 'Character does not have sufficient permission to sync'        

    else:
        try:
            # get token    
            token = Token.objects.filter(
                user=owner.character.user, 
                character_id=owner.character.character.character_id
            ).require_scopes(
                Owner.get_esi_scopes()
            ).require_valid().first()

        except TokenInvalidError:        
            error = 'Invalid token'            
            
        except TokenExpiredError:            
            error = 'Token expired'            
            
        else:
            if not token:
                error = 'Missing token'                
            
    if error:
        logger.error(add_prefix(error))
    
    if token:
        logger.debug('Using token: {}'.format(token))
    
    return token, error


def sync_mailinglists(
    owner: Owner, 
    esi_client: object, 
    add_prefix: make_logger_prefix
):    
    mailing_lists = \
        esi_client.Mail.get_characters_character_id_mail_lists(
            character_id=owner.character.character.character_id
        ).result()   
    
    logger.info(add_prefix('Received {} mailing lists from ESI'.format(
        len(mailing_lists)
    )))
    
    created_count = 0            
    for mailing_list in mailing_lists:                
        _, created = MailingList.objects.update_or_create(
            owner=owner,
            list_id=mailing_list['mailing_list_id'],
            defaults={
                'name': mailing_list['name']
            }
        )
        if created:
            created_count += 1

    if created_count > 0:
        logger.info(add_prefix('Added/Updated {} mailing lists'.format(
            created_count
        )))


def sync_mails(
    owner: Owner, 
    esi_client: object, 
    add_prefix: make_logger_prefix
):
    # fetch mail headers            
    last_mail_id = None
    mail_headers_all = list()
    page = 1

    while True:
        logger.info(add_prefix(
            'Fetching mail headers from ESI - page {}'.format(page)
        ))
        mail_headers = \
            esi_client.Mail.get_characters_character_id_mail(
                character_id=owner.character.character.character_id,
                last_mail_id=last_mail_id
            ).result()                            
        
        mail_headers_all += mail_headers
                        
        if (len(mail_headers) < 50 
            or len(mail_headers_all) >= MEMBERAUDIT_MAX_MAILS
        ):
            break
        else:
            last_mail_id = min([x['mail_id'] for x in mail_headers])
            page += 1                    
        
    logger.info(add_prefix('Received {} mail headers from ESI'.format(
        len(mail_headers_all)
    )))

    if settings.DEBUG:
        # store to disk (for debugging)
        with open(
            'mail_headers_raw_{}.json'.format(
                owner.character.character.character_id
            ), 
            'w', 
            encoding='utf-8'
        ) as f:
            json.dump(
                mail_headers_all, 
                f, 
                cls=DjangoJSONEncoder, 
                sort_keys=True, 
                indent=4
            )

    # update IDs from ESI
    ids = set()
    mailing_list_ids = [
        x['list_id'] 
        for x in MailingList.objects\
            .filter(owner=owner)\
            .select_related()\
            .values('list_id')            
    ]
    for header in mail_headers_all:
        if header['from'] not in mailing_list_ids:
            ids.add(header['from'])
        for recipient in header['recipients']:
            if recipient['recipient_type'] != 'mailing_list':
                ids.add(recipient['recipient_id'])
    
    EveEntity.objects.load_missing_from_esi_bulk(ids)

    logger.info(add_prefix(
        'Updating {} mail headers and loading mail bodies'.format(
            len(mail_headers_all)
    )))
    
    # load mail headers
    body_count = 0
    for header in mail_headers_all:
        try:
            with transaction.atomic():
                try:
                    from_mailing_list = MailingList.objects.get(
                        list_id=header['from']
                    )
                    from_entity = None
                except MailingList.DoesNotExist:
                    from_entity, _ = EveEntity.objects.get_or_create_from_esi(
                        header['from'],
                        esi_client
                    )
                    from_mailing_list = None
                
                mail_obj, _ = Mail.objects.update_or_create(
                    owner=owner,
                    mail_id=header['mail_id'],
                    defaults={
                        'from_entity': from_entity,
                        'from_mailing_list': from_mailing_list,
                        'is_read': header['is_read'],
                        'subject': header['subject'],
                        'timestamp': header['timestamp'],
                    }
                )
                MailRecipient.objects.filter(mail=mail_obj).delete()
                for recipient in header['recipients']:
                    if recipient['recipient_type'] != 'mailing_list':
                        recipient, _ = EveEntity.objects.get_or_create_from_esi(
                            recipient['recipient_id'],
                            esi_client
                        ) 
                        MailRecipient.objects.create(
                            mail=mail_obj,
                            recipient=recipient
                        )
                MailLabels.objects.filter(mail=mail_obj).delete()
                for label in header['labels']:
                    MailLabels.objects.create(
                        label_id=label,
                        mail=mail_obj
                    )
                
                if mail_obj.body is None:
                    logger.info(add_prefix(
                        'Fetching body from ESI for mail ID {}'.format(
                            mail_obj.mail_id
                    )))
                    mail = esi_client.Mail\
                        .get_characters_character_id_mail_mail_id(
                            character_id=owner.character.character.character_id,
                            mail_id=mail_obj.mail_id
                        ).result()
                    mail_obj.body = mail['body']
                    mail_obj.save()
                    body_count += 1
        
        except Exception as ex:    
            logger.exception(add_prefix(
                'Unexpected error ocurred while processing mail {}'.\
                    format(header['mail_id'], ex)
            ))
    if body_count > 0:
        logger.info('loaded {} mail bodies'. format(body_count))


@shared_task
def sync_owner(owner_pk, force_sync: bool = False):
    try:
        owner = Owner.objects.get(pk=owner_pk)
    except Owner.DoesNotExist:
        raise Owner.DoesNotExist(
            "Requested character with pk {} not registered".format(owner_pk)
        )
    
    add_prefix = make_logger_prefix(owner)

    try:        
        owner.last_sync = now()
        owner.last_error = None
        owner.save()
        
        token, error = _get_token_for_owner(owner, add_prefix)
        if not token:
            owner.last_error = error
            owner.save()
            raise RuntimeError()
        
        # fetch data from ESI
        try:            
            logger.info(add_prefix('Connecting to ESI...'))
            esi_client = esi_client_factory(
                token=token, 
                spec_file=get_swagger_spec_path()
            )            
            sync_mailinglists(owner, esi_client, add_prefix)            
            sync_mails(owner, esi_client, add_prefix)            
            
        except Exception as ex:
            error = 'Unexpected error ocurred {}'. format(ex)
            logger.exception(add_prefix(error))                                
            owner.last_error = error
            owner.save()       
            raise ex     

    except Exception as ex:
        success = False              
        error_code = str(ex)
    else:
        success = True
        error_code = None
   
    return success