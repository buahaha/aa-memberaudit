from unittest.mock import patch, Mock

from bravado.exception import HTTPUnauthorized
from celery.exceptions import Retry as CeleryRetry
from esi.models import Token

from django.core.cache import cache
from django.test import TestCase, override_settings

from . import create_memberaudit_character
from ..models import Character
from ..tasks import (
    update_all_characters,
    update_character,
    update_structure_esi,
    LOCATION_ESI_ERRORS_CACHE_KEY,
    ESI_ERROR_LIMIT,
)
from .testdata.esi_client_stub import esi_client_stub
from .testdata.load_eveuniverse import load_eveuniverse
from .testdata.load_entities import load_entities
from .testdata.load_locations import load_locations
from ..utils import generate_invalid_pk

MODELS_PATH = "memberaudit.models"
MANAGERS_PATH = "memberaudit.managers"
TASKS_PATH = "memberaudit.tasks"


@patch(MODELS_PATH + ".esi")
@override_settings(CELERY_ALWAYS_EAGER=True)
class TestUpdateCharacter(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        load_locations()

    def setUp(self) -> None:
        self.character = create_memberaudit_character(1001)

    def test_normal(self, mock_esi):
        mock_esi.client = esi_client_stub

        update_character(self.character.pk)
        self.assertTrue(self.character.is_update_status_ok())

    def test_report_error(self, mock_esi):
        mock_esi.client.Assets.get_characters_character_id_assets.side_effect = (
            RuntimeError("Dummy")
        )

        update_character(self.character.pk)
        self.assertFalse(self.character.is_update_status_ok())

        status = self.character.update_status_set.get(
            character=self.character, section=Character.UPDATE_SECTION_ASSETS
        )
        self.assertFalse(status.is_success)
        self.assertEqual(status.error_message, "RuntimeError: Dummy")


@patch(MODELS_PATH + ".esi")
@override_settings(CELERY_ALWAYS_EAGER=True)
class TestUpdateAllCharacters(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        load_locations()

    def setUp(self) -> None:
        self.character_1001 = create_memberaudit_character(1001)

    def test_normal(self, mock_esi):
        mock_esi.client = esi_client_stub

        update_all_characters()
        self.assertTrue(self.character_1001.is_update_status_ok())


@patch(TASKS_PATH + ".Location.objects.structure_update_or_create_esi")
class TestUpdateStructureEsi(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_entities()
        cls.character = create_memberaudit_character(1001)
        cls.token = cls.character.character_ownership.user.token_set.first()

    def setUp(self) -> None:
        cache.clear()

    def test_normal(self, mock_structure_update_or_create_esi):
        update_structure_esi(id=1, token_pk=self.token.pk)

    def test_below_error_limit(self, mock_structure_update_or_create_esi):
        cache.set(LOCATION_ESI_ERRORS_CACHE_KEY, 40)
        update_structure_esi(id=1, token_pk=self.token.pk)

    def test_raise_exception_on_invali_token(self, mock_structure_update_or_create_esi):
        with self.assertRaises(Token.DoesNotExist):
            update_structure_esi(id=1, token_pk=generate_invalid_pk(Token))

    def test_access_forbidden(self, mock_structure_update_or_create_esi):
        mock_structure_update_or_create_esi.side_effect = HTTPUnauthorized(Mock())

        update_structure_esi(id=1, token_pk=self.token.pk)
        self.assertTrue(cache.get(LOCATION_ESI_ERRORS_CACHE_KEY), 1)

    def test_above_error_limit(self, mock_structure_update_or_create_esi):
        cache.set(LOCATION_ESI_ERRORS_CACHE_KEY, ESI_ERROR_LIMIT + 1)
        with self.assertRaises(CeleryRetry):
            update_structure_esi(id=1, token_pk=self.token.pk)
