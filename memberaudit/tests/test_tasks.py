from unittest.mock import patch

from django.test import TestCase, override_settings

from . import create_memberaudit_character
from ..tasks import update_character
from .testdata.esi_client_stub import esi_client_stub
from .testdata.load_eveuniverse import load_eveuniverse
from .testdata.load_entities import load_entities
from .testdata.load_locations import load_locations

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
