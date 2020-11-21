from unittest.mock import patch

from bravado.exception import HTTPInternalServerError
from celery.exceptions import Retry as CeleryRetry

from django.core.cache import cache
from django.test import TestCase, override_settings

from eveuniverse.models import EveSolarSystem, EveType
from esi.models import Token

from . import create_memberaudit_character
from ..helpers import EsiStatus
from ..models import (
    Character,
    CharacterAsset,
    CharacterUpdateStatus,
    Location,
)
from ..tasks import (
    run_regular_updates,
    update_all_characters,
    update_character,
    update_character_assets,
    update_structure_esi,
    update_character_mails,
    update_character_contacts,
    update_character_contracts,
    update_character_wallet_journal,
    update_market_prices,
)
from .testdata.esi_client_stub import esi_client_stub, esi_client_error_stub
from .testdata.load_eveuniverse import load_eveuniverse
from .testdata.load_entities import load_entities
from .testdata.load_locations import load_locations
from .testdata.esi_test_tools import BravadoResponseStub
from ..utils import generate_invalid_pk

MODELS_PATH = "memberaudit.models"
MANAGERS_PATH = "memberaudit.managers"
TASKS_PATH = "memberaudit.tasks"


@patch(TASKS_PATH + ".update_all_characters")
@patch(TASKS_PATH + ".update_market_prices")
class TestRegularUpdates(TestCase):
    @patch(TASKS_PATH + ".is_esi_online", lambda: True)
    def test_normal(
        self,
        mock_update_market_prices,
        mock_update_all_characters,
    ):
        run_regular_updates()

        self.assertTrue(mock_update_market_prices.apply_async.called)
        self.assertTrue(mock_update_all_characters.apply_async.called)

    @patch(TASKS_PATH + ".is_esi_online", lambda: False)
    def test_esi_down(
        self,
        mock_update_market_prices,
        mock_update_all_characters,
    ):
        run_regular_updates()

        self.assertFalse(mock_update_market_prices.apply_async.called)
        self.assertFalse(mock_update_all_characters.apply_async.called)


class TestOtherTasks(TestCase):
    @patch(TASKS_PATH + ".EveMarketPrice.objects.update_from_esi")
    def test_update_market_prices(self, mock_update_from_esi):
        update_market_prices()
        self.assertTrue(mock_update_from_esi.called)


@override_settings(CELERY_ALWAYS_EAGER=True)
@patch(MODELS_PATH + ".esi")
class TestUpdateCharacterAssets(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        load_locations()
        cls.character_1001 = create_memberaudit_character(1001)
        cls.character_1002 = create_memberaudit_character(1002)
        cls.token = cls.character_1001.character_ownership.user.token_set.first()
        cls.jita = EveSolarSystem.objects.get(id=30000142)
        cls.jita_44 = Location.objects.get(id=60003760)
        cls.amamake = EveSolarSystem.objects.get(id=30002537)
        cls.structure_1 = Location.objects.get(id=1000000000001)

    @patch(TASKS_PATH + ".MEMBERAUDIT_TASKS_MAX_ASSETS_PER_PASS", 1)
    def test_update_assets_1(self, mock_esi):
        """can create assets from scratch"""
        mock_esi.client = esi_client_stub

        update_character_assets(self.character_1001.pk)
        self.assertSetEqual(
            set(self.character_1001.assets.values_list("item_id", flat=True)),
            {
                1100000000001,
                1100000000002,
                1100000000003,
                1100000000004,
                1100000000005,
                1100000000006,
                1100000000007,
                1100000000008,
            },
        )

        asset = self.character_1001.assets.get(item_id=1100000000001)
        self.assertTrue(asset.is_blueprint_copy)
        self.assertTrue(asset.is_singleton)
        self.assertEqual(asset.location_flag, "Hangar")
        self.assertEqual(asset.location_id, 60003760)
        self.assertEqual(asset.quantity, 1)
        self.assertEqual(asset.eve_type, EveType.objects.get(id=20185))
        self.assertEqual(asset.name, "Parent Item 1")

        asset = self.character_1001.assets.get(item_id=1100000000002)
        self.assertFalse(asset.is_blueprint_copy)
        self.assertTrue(asset.is_singleton)
        self.assertEqual(asset.location_flag, "???")
        self.assertEqual(asset.parent.item_id, 1100000000001)
        self.assertEqual(asset.quantity, 1)
        self.assertEqual(asset.eve_type, EveType.objects.get(id=19540))
        self.assertEqual(asset.name, "Leaf Item 2")

        asset = self.character_1001.assets.get(item_id=1100000000003)
        self.assertEqual(asset.parent.item_id, 1100000000001)
        self.assertEqual(asset.eve_type, EveType.objects.get(id=23))

        asset = self.character_1001.assets.get(item_id=1100000000004)
        self.assertEqual(asset.parent.item_id, 1100000000003)
        self.assertEqual(asset.eve_type, EveType.objects.get(id=19553))

        asset = self.character_1001.assets.get(item_id=1100000000005)
        self.assertEqual(asset.location, self.structure_1)
        self.assertEqual(asset.eve_type, EveType.objects.get(id=20185))

        asset = self.character_1001.assets.get(item_id=1100000000006)
        self.assertEqual(asset.parent.item_id, 1100000000005)
        self.assertEqual(asset.eve_type, EveType.objects.get(id=19540))

        asset = self.character_1001.assets.get(item_id=1100000000007)
        self.assertEqual(asset.location_id, 30000142)
        self.assertEqual(asset.name, "")
        self.assertEqual(asset.eve_type, EveType.objects.get(id=19540))

        asset = self.character_1001.assets.get(item_id=1100000000008)
        self.assertEqual(asset.location_id, 1000000000001)

    def test_update_assets_2(self, mock_esi):
        """can remove obsolete assets"""
        mock_esi.client = esi_client_stub
        CharacterAsset.objects.create(
            character=self.character_1001,
            item_id=1100000000666,
            location=self.jita_44,
            eve_type=EveType.objects.get(id=20185),
            is_singleton=False,
            name="Trucker",
            quantity=1,
        )

        update_character_assets(self.character_1001.pk)
        self.assertSetEqual(
            set(self.character_1001.assets.values_list("item_id", flat=True)),
            {
                1100000000001,
                1100000000002,
                1100000000003,
                1100000000004,
                1100000000005,
                1100000000006,
                1100000000007,
                1100000000008,
            },
        )

    def test_update_assets_3(self, mock_esi):
        """can update existing assets"""
        mock_esi.client = esi_client_stub
        CharacterAsset.objects.create(
            character=self.character_1001,
            item_id=1100000000001,
            location=self.jita_44,
            eve_type=EveType.objects.get(id=20185),
            is_singleton=True,
            name="Parent Item 1",
            quantity=10,
        )

        update_character_assets(self.character_1001.pk)
        self.assertSetEqual(
            set(self.character_1001.assets.values_list("item_id", flat=True)),
            {
                1100000000001,
                1100000000002,
                1100000000003,
                1100000000004,
                1100000000005,
                1100000000006,
                1100000000007,
                1100000000008,
            },
        )

        asset = self.character_1001.assets.get(item_id=1100000000001)
        self.assertTrue(asset.is_singleton)
        self.assertEqual(asset.location_id, 60003760)
        self.assertEqual(asset.quantity, 1)
        self.assertEqual(asset.eve_type, EveType.objects.get(id=20185))
        self.assertEqual(asset.name, "Parent Item 1")

    def test_update_assets_4(self, mock_esi):
        """assets moved to different locations are kept"""
        mock_esi.client = esi_client_stub
        parent_asset = CharacterAsset.objects.create(
            character=self.character_1001,
            item_id=1100000000666,
            location=self.jita_44,
            eve_type=EveType.objects.get(id=20185),
            is_singleton=True,
            name="Obsolete Container",
            quantity=1,
        )
        CharacterAsset.objects.create(
            character=self.character_1001,
            item_id=1100000000002,
            parent=parent_asset,
            eve_type=EveType.objects.get(id=19540),
            is_singleton=True,
            is_blueprint_copy=False,
            quantity=1,
        )

        update_character_assets(self.character_1001.pk)
        self.assertSetEqual(
            set(self.character_1001.assets.values_list("item_id", flat=True)),
            {
                1100000000001,
                1100000000002,
                1100000000003,
                1100000000004,
                1100000000005,
                1100000000006,
                1100000000007,
                1100000000008,
            },
        )

    def test_update_assets_5(self, mock_esi):
        """when update succeeded then report update success"""
        mock_esi.client = esi_client_stub

        update_character_assets(self.character_1001.pk)

        status = self.character_1001.update_status_set.get(
            section=Character.UPDATE_SECTION_ASSETS
        )
        self.assertTrue(status.is_success)
        self.assertFalse(status.error_message)

    def test_update_assets_6(self, mock_esi):
        """when update failed then report the error"""
        mock_esi.client.Assets.get_characters_character_id_assets.side_effect = (
            HTTPInternalServerError(response=BravadoResponseStub(500, "Test exception"))
        )

        with self.assertRaises(HTTPInternalServerError):
            update_character_assets(self.character_1001.pk)

        status = self.character_1001.update_status_set.get(
            section=Character.UPDATE_SECTION_ASSETS
        )
        self.assertFalse(status.is_success)
        self.assertEqual(
            status.error_message, "HTTPInternalServerError: 500 Test exception"
        )


@override_settings(CELERY_ALWAYS_EAGER=True)
@patch(MODELS_PATH + ".esi")
class TestUpdateCharacterMails(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        cls.character_1001 = create_memberaudit_character(1001)
        cls.token = cls.character_1001.character_ownership.user.token_set.first()

    def test_update_ok(self, mock_esi):
        """when update succeeded then report update success"""
        mock_esi.client = esi_client_stub

        update_character_mails(self.character_1001.pk)

        status = self.character_1001.update_status_set.get(
            section=Character.UPDATE_SECTION_MAILS
        )
        self.assertTrue(status.is_success)
        self.assertFalse(status.error_message)

    def test_detect_error(self, mock_esi):
        """when update failed then report the error"""
        mock_esi.client.Mail.get_characters_character_id_mail_lists.side_effect = (
            HTTPInternalServerError(response=BravadoResponseStub(500, "Test exception"))
        )

        try:
            update_character_mails(self.character_1001.pk)
        except Exception:
            status = self.character_1001.update_status_set.get(
                section=Character.UPDATE_SECTION_MAILS
            )
            self.assertFalse(status.is_success)
            self.assertEqual(
                status.error_message, "HTTPInternalServerError: 500 Test exception"
            )
        else:
            self.assertTrue(False)  # Hack to ensure the test fails when it gets here


@override_settings(CELERY_ALWAYS_EAGER=True)
@patch(MODELS_PATH + ".esi")
class TestUpdateCharacterContacts(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        cls.character_1001 = create_memberaudit_character(1001)
        cls.token = cls.character_1001.character_ownership.user.token_set.first()

    def test_update_ok(self, mock_esi):
        """when update succeeded then report update success"""
        mock_esi.client = esi_client_stub

        update_character_contacts(self.character_1001.pk)

        status = self.character_1001.update_status_set.get(
            section=Character.UPDATE_SECTION_CONTACTS
        )
        self.assertTrue(status.is_success)
        self.assertFalse(status.error_message)

    def test_detect_error(self, mock_esi):
        """when update failed then report the error"""
        mock_esi.client.Contacts.get_characters_character_id_contacts_labels.side_effect = HTTPInternalServerError(
            response=BravadoResponseStub(500, "Test exception")
        )

        try:
            update_character_contacts(self.character_1001.pk)
        except Exception:
            status = self.character_1001.update_status_set.get(
                section=Character.UPDATE_SECTION_CONTACTS
            )
            self.assertFalse(status.is_success)
            self.assertEqual(
                status.error_message, "HTTPInternalServerError: 500 Test exception"
            )
        else:
            self.assertTrue(False)  # Hack to ensure the test fails when it gets here


@override_settings(CELERY_ALWAYS_EAGER=True)
@patch(MODELS_PATH + ".esi")
class TestUpdateCharacterContracts(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        load_locations()
        cls.character_1001 = create_memberaudit_character(1001)
        cls.token = cls.character_1001.character_ownership.user.token_set.first()

    def test_update_ok(self, mock_esi):
        """when update succeeded then report update success"""
        mock_esi.client = esi_client_stub

        update_character_contracts(self.character_1001.pk)

        status = self.character_1001.update_status_set.get(
            section=Character.UPDATE_SECTION_CONTRACTS
        )
        self.assertTrue(status.is_success)
        self.assertFalse(status.error_message)

    def test_detect_error(self, mock_esi):
        """when update failed then report the error"""
        mock_esi.client.Contracts.get_characters_character_id_contracts.side_effect = (
            HTTPInternalServerError(response=BravadoResponseStub(500, "Test exception"))
        )

        try:
            update_character_contracts(self.character_1001.pk)
        except Exception:
            status = self.character_1001.update_status_set.get(
                section=Character.UPDATE_SECTION_CONTRACTS
            )
            self.assertFalse(status.is_success)
            self.assertEqual(
                status.error_message, "HTTPInternalServerError: 500 Test exception"
            )
        else:
            self.assertTrue(False)  # Hack to ensure the test fails when it gets here


@override_settings(CELERY_ALWAYS_EAGER=True)
@patch(MODELS_PATH + ".esi")
class TestUpdateCharacterWalletJournal(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        cls.character_1001 = create_memberaudit_character(1001)
        cls.token = cls.character_1001.character_ownership.user.token_set.first()

    def test_update_ok(self, mock_esi):
        """when update succeeded then report update success"""
        mock_esi.client = esi_client_stub

        update_character_wallet_journal(self.character_1001.pk)

        status = self.character_1001.update_status_set.get(
            section=Character.UPDATE_SECTION_WALLET_JOURNAL
        )
        self.assertTrue(status.is_success)
        self.assertFalse(status.error_message)

    def test_detect_error(self, mock_esi):
        """when update failed then report the error"""
        mock_esi.client.Wallet.get_characters_character_id_wallet_journal.side_effect = HTTPInternalServerError(
            response=BravadoResponseStub(500, "Test exception")
        )

        try:
            update_character_wallet_journal(self.character_1001.pk)
        except Exception:
            status = self.character_1001.update_status_set.get(
                section=Character.UPDATE_SECTION_WALLET_JOURNAL
            )
            self.assertFalse(status.is_success)
            self.assertEqual(
                status.error_message, "HTTPInternalServerError: 500 Test exception"
            )
        else:
            self.assertTrue(False)  # Hack to ensure the test fails when it gets here


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

        result = update_character(self.character.pk)
        self.assertTrue(result)
        self.assertTrue(self.character.is_update_status_ok())

    def test_report_error(self, mock_esi):
        mock_esi.client = esi_client_error_stub

        update_character(self.character.pk)
        self.assertFalse(self.character.is_update_status_ok())

        status = self.character.update_status_set.get(
            character=self.character, section=Character.UPDATE_SECTION_CHARACTER_DETAILS
        )
        self.assertFalse(status.is_success)
        self.assertEqual(
            status.error_message, "HTTPInternalServerError: 500 Test exception"
        )

    @patch(TASKS_PATH + ".Character.update_skills")
    def test_do_not_update_current_section_1(self, mock_update_skills, mock_esi):
        """When generic section has recently been updated, then do not update again"""
        mock_esi.client = esi_client_stub
        CharacterUpdateStatus.objects.create(
            character=self.character,
            section=Character.UPDATE_SECTION_SKILLS,
            is_success=True,
        )

        update_character(self.character.pk)

        self.assertFalse(mock_update_skills.called)

    @patch(TASKS_PATH + ".update_character_assets")
    def test_do_not_update_current_section_2(
        self, mock_update_character_assets, mock_esi
    ):
        """When special section has recently been updated, then do not update again"""
        mock_esi.client = esi_client_stub
        CharacterUpdateStatus.objects.create(
            character=self.character,
            section=Character.UPDATE_SECTION_ASSETS,
            is_success=True,
        )

        update_character(self.character.pk)

        self.assertFalse(mock_update_character_assets.apply_async.called)

    @patch(TASKS_PATH + ".Character.update_skills")
    def test_do_not_update_current_section_3(self, mock_update_skills, mock_esi):
        """When generic section has recently been updated and force_update is called
        then update again
        """
        mock_esi.client = esi_client_stub
        CharacterUpdateStatus.objects.create(
            character=self.character,
            section=Character.UPDATE_SECTION_SKILLS,
            is_success=True,
        )

        update_character(self.character.pk, force_update=True)

        self.assertTrue(mock_update_skills.called)

    def test_no_update_required(self, mock_esi):
        """Do not update anything when not required"""
        mock_esi.client = esi_client_stub
        for section in Character.update_sections():
            CharacterUpdateStatus.objects.create(
                character=self.character,
                section=section,
                is_success=True,
            )

        result = update_character(self.character.pk)
        self.assertFalse(result)


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


@patch(MANAGERS_PATH + ".esi")
@patch(TASKS_PATH + ".fetch_esi_status")
class TestUpdateStructureEsi(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_entities()
        load_eveuniverse()
        cls.character = create_memberaudit_character(1001)
        cls.token = cls.character.character_ownership.user.token_set.first()

    def setUp(self) -> None:
        cache.clear()
        Location.objects.all().delete()

    def test_normal(self, mock_fetch_esi_status, mock_esi):
        """
        when character has access and there are no ESI errors
        then update succeeds and structure is created
        """
        mock_fetch_esi_status.return_value = EsiStatus(True, 99, 60)
        mock_esi.client = esi_client_stub

        update_structure_esi(id=1000000000001, token_pk=self.token.pk)
        self.assertTrue(Location.objects.filter(id=1000000000001).exists())

    def test_raise_exception_on_invalid_token(self, mock_fetch_esi_status, mock_esi):
        """when token is invalid, then raise exception"""
        mock_fetch_esi_status.return_value = EsiStatus(True, 99, 60)
        mock_esi.client = esi_client_stub

        with self.assertRaises(Token.DoesNotExist):
            update_structure_esi(id=1000000000001, token_pk=generate_invalid_pk(Token))

    @patch("memberaudit.helpers.MEMBERAUDIT_ESI_ERROR_LIMIT_THRESHOLD", 25)
    def test_below_error_limit(self, mock_fetch_esi_status, mock_esi):
        """when error limit threshold not exceeded, then make request to ESI"""
        mock_fetch_esi_status.return_value = EsiStatus(True, 99, 60)
        mock_esi.client = esi_client_stub

        update_structure_esi(id=1000000000001, token_pk=self.token.pk)
        self.assertTrue(Location.objects.filter(id=1000000000001).exists())

    @patch("memberaudit.helpers.MEMBERAUDIT_ESI_ERROR_LIMIT_THRESHOLD", 25)
    def test_above_error_limit(self, mock_fetch_esi_status, mock_esi):
        """
        when error limit threshold is exceeded,
        then make no request to ESI and retry task
        """
        mock_fetch_esi_status.return_value = EsiStatus(True, 15, 60)
        mock_esi.client = esi_client_stub

        # TODO: Add ability to verify countdown is set correctly for retry
        with self.assertRaises(CeleryRetry):
            update_structure_esi(id=1000000000001, token_pk=self.token.pk)
