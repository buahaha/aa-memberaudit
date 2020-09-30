"""
import os
import inspect
import json
import logging
import sys
from unittest.mock import Mock

from django.test import TestCase
from django.contrib.auth.models import User

from allianceauth.eveonline.models import (
    EveCharacter,
    EveCorporationInfo,
)
from allianceauth.authentication.models import CharacterOwnership

from ..models import Character
from .. import tasks


# reconfigure logger so we get logging from tasks to console during test
c_handler = logging.StreamHandler(sys.stdout)
logger = logging.getLogger("memberaudit.tasks")
logger.level = logging.DEBUG
logger.addHandler(c_handler)

class TestTasks(TestCase):
    @classmethod
    def setUpClass(cls):
        super(TestTasks, cls).setUpClass()

        currentdir = os.path.dirname(
            os.path.abspath(inspect.getfile(inspect.currentframe()))
        )

        # entities
        with open(currentdir + "/testdata/entities.json", "r", encoding="utf-8") as f:
            cls.entities = json.load(f)

        with open(currentdir + "/testdata/esi_data.json", "r", encoding="utf-8") as f:
            cls.esi_data = json.load(f)

    def setUp(self):

        entities_def = [EveCorporationInfo, EveCharacter]

        for EntityClass in entities_def:
            entity_name = EntityClass.__name__
            for x in self.entities[entity_name]:
                EntityClass.objects.create(**x)
            assert len(self.entities[entity_name]) == EntityClass.objects.count()

        self.character = EveCharacter.objects.get(character_id=1001)

        self.corporation = EveCorporationInfo.objects.get(corporation_id=2001)
        self.user = User.objects.create_user(
            self.character.character_name, "abc@example.com", "password"
        )

        self.main_ownership = CharacterOwnership.objects.create(
            character=self.character, owner_hash="x1", user=self.user
        )
        self.owner = Character.objects.create(character=self.main_ownership)

    def test_sync_mailinglist(self):
        esi_client = Mock()
        esi_client.Mail.get_characters_character_id_mail_lists.return_value.result.return_value = (
            []
        )
        tasks.sync_mailinglists(self.owner, esi_client)
"""
