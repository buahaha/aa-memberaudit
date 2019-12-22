import logging

from django.db import models, transaction

from bravado.exception import HTTPNotFound
from esi.clients import esi_client_factory
from allianceauth.eveonline.providers import ObjectNotFound

from .utils import LoggerAddTag, make_logger_prefix, get_swagger_spec_path


logger = LoggerAddTag(logging.getLogger(__name__), __package__)


class EveEntityManager(models.Manager):
    
    def get_or_create_from_esi(
            self,             
            id: int, 
            esi_client: object = None
        ) -> list:
        """gets or creates entity object with data fetched from ESI"""
        from .models import EveEntity
        try:
            entity = self.get(id=id)
            created = False
        except EveEntity.DoesNotExist:
            entity, created = self.update_or_create_from_esi(id, esi_client)
        
        return entity, created


    def update_or_create_from_esi(
            self,             
            id: int, 
            esi_client: object = None
        ) -> list:
        """updates or creates entity object with data fetched from ESI"""
        from .models import EveEntity

        addPrefix = make_logger_prefix(id)
        
        logger.info(addPrefix('Fetching entity from ESI'))
        try:
            if not esi_client:
                esi_client = esi_client_factory(
                    spec_file=get_swagger_spec_path()
                )
            response = esi_client.Universe.post_universe_names(
                ids=[id]
            ).result()
            if len(response) != 1:
                raise ObjectNotFound(id, 'unknown_type')
            else:
                entity_data = response[0]
            entity, created = self.update_or_create(
                id=entity_data['id'],
                defaults={
                    'name': entity_data['name'],
                    'category': entity_data['category'],
                }
            ) 
        except Exception as ex:
            logger.exception(addPrefix(
                'Failed to load entity with id {} from ESI: '.format(id, ex)
            ))
            raise ex
        
       
        return entity, created


    def load_missing_from_esi_bulk(
            self,             
            ids: list, 
            esi_client: object = None
        ) -> list:
        """loads missing entities from ESI in bulk"""

        def chunks(lst, size):
            """Yield successive size-sized chunks from lst."""
            for i in range(0, len(lst), size):
                yield lst[i: i + size]

        from .models import EveEntity

        ids_cleaned = {int(x) for x in ids}
        unknown_ids = set()
                
        for id in ids_cleaned:
            try:
                self.get(id=id)
            except EveEntity.DoesNotExist:
                unknown_ids.add(id)
            
        created_count = 0
        if len(unknown_ids) > 0:                        
            for unknown_ids_chk in chunks(list(unknown_ids), 500):
                logger.info(
                    'Fetching {} entities from ESI'.format(
                        len(unknown_ids_chk)
                ))            
                try:
                    if not esi_client:
                        esi_client = esi_client_factory(
                            spec_file=get_swagger_spec_path()
                        )
                    entities_data = esi_client.Universe.post_universe_names(
                        ids=unknown_ids_chk
                    ).result()
                    if len(entities_data) > 0:
                        for entity_data in entities_data:                
                            entity, created = self.update_or_create(
                                id=entity_data['id'],
                                defaults={
                                    'name': entity_data['name'],
                                    'category': entity_data['category'],
                                }
                            )
                            if created:
                                created_count += 1 
                
                except HTTPNotFound:
                    logger.warning(
                        'Failed to bulk load {} IDs from ESI.'.format(len(ids))
                        + 'Now trying one by one'
                    )
                    for id in unknown_ids_chk:
                        self.update_or_create_from_esi(
                            id=id,
                            esi_client=esi_client
                        )

                except Exception as ex:
                    logger.exception(
                        'Failed to load {} entities from ESI: '.format(
                            len(unknown_ids_chk),
                            ex
                    ))
                    raise ex

        return created_count
       