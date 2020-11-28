from unittest.mock import patch

from bravado.exception import HTTPInternalServerError
from celery.exceptions import Retry as CeleryRetry

from django.test import TestCase, override_settings

from esi.models import Token

from . import create_memberaudit_character
from ..helpers import EsiOffline, EsiErrorLimitExceeded
from ..models import (
    Character,
    CharacterUpdateStatus,
)
from ..tasks import (
    run_regular_updates,
    update_all_characters,
    update_character,
    update_structure_esi,
    update_character_mails,
    update_character_contacts,
    update_character_contracts,
    update_character_wallet_journal,
    update_market_prices,
    update_mail_entity_esi,
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
            section=Character.UpdateSection.MAILS
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
                section=Character.UpdateSection.MAILS
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
            section=Character.UpdateSection.CONTACTS
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
                section=Character.UpdateSection.CONTACTS
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
            section=Character.UpdateSection.CONTRACTS
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
                section=Character.UpdateSection.CONTRACTS
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
            section=Character.UpdateSection.WALLET_JOURNAL
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
                section=Character.UpdateSection.WALLET_JOURNAL
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
            character=self.character, section=Character.UpdateSection.CHARACTER_DETAILS
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
            section=Character.UpdateSection.SKILLS,
            is_success=True,
        )

        update_character(self.character.pk)

        self.assertFalse(mock_update_skills.called)

    @patch(TASKS_PATH + ".update_character_mails")
    def test_do_not_update_current_section_2(self, update_character_mails, mock_esi):
        """When special section has recently been updated, then do not update again"""
        mock_esi.client = esi_client_stub
        CharacterUpdateStatus.objects.create(
            character=self.character,
            section=Character.UpdateSection.MAILS,
            is_success=True,
        )

        update_character(self.character.pk)

        self.assertFalse(update_character_mails.apply_async.called)

    @patch(TASKS_PATH + ".Character.update_skills")
    def test_do_not_update_current_section_3(self, mock_update_skills, mock_esi):
        """When generic section has recently been updated and force_update is called
        then update again
        """
        mock_esi.client = esi_client_stub
        CharacterUpdateStatus.objects.create(
            character=self.character,
            section=Character.UpdateSection.SKILLS,
            is_success=True,
        )

        update_character(self.character.pk, force_update=True)

        self.assertTrue(mock_update_skills.called)

    def test_no_update_required(self, mock_esi):
        """Do not update anything when not required"""
        mock_esi.client = esi_client_stub
        for section in Character.UpdateSection.values:
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


@patch(TASKS_PATH + ".Location.objects.structure_update_or_create_esi")
class TestUpdateStructureEsi(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_entities()
        cls.character = create_memberaudit_character(1001)
        cls.token = cls.character.character_ownership.user.token_set.first()

    def test_normal(self, mock_structure_update_or_create_esi):
        """When ESI status is ok, then create MailEntity"""
        mock_structure_update_or_create_esi.return_value = None
        try:
            update_structure_esi(id=1000000000001, token_pk=self.token.pk)
        except Exception as ex:
            self.fail(f"Unexpected exception occurred: {ex}")

    def test_invalid_token(self, mock_structure_update_or_create_esi):
        """When called with invalid token, raise exception"""
        mock_structure_update_or_create_esi.side_effect = EsiOffline

        with self.assertRaises(Token.DoesNotExist):
            update_structure_esi(id=1000000000001, token_pk=generate_invalid_pk(Token))

    def test_esi_status_1(self, mock_structure_update_or_create_esi):
        """When ESI is offline, then retry"""
        mock_structure_update_or_create_esi.side_effect = EsiOffline

        with self.assertRaises(CeleryRetry):
            update_structure_esi(id=1000000000001, token_pk=self.token.pk)

    def test_esi_status_2(self, mock_structure_update_or_create_esi):
        """When ESI error limit reached, then retry"""
        mock_structure_update_or_create_esi.side_effect = EsiErrorLimitExceeded(5)

        with self.assertRaises(CeleryRetry):
            update_structure_esi(id=1000000000001, token_pk=self.token.pk)


@patch(TASKS_PATH + ".MailEntity.objects.update_or_create_esi")
class TestUpdateMailEntityEsi(TestCase):
    def test_normal(self, mock_update_or_create_esi):
        """When ESI status is ok, then create MailEntity"""
        mock_update_or_create_esi.return_value = None
        try:
            update_mail_entity_esi(1001)
        except Exception:
            self.fail("Unexpected exception occurred")

    def test_esi_status_1(self, mock_update_or_create_esi):
        """When ESI is offline, then retry"""
        mock_update_or_create_esi.side_effect = EsiOffline

        with self.assertRaises(CeleryRetry):
            update_mail_entity_esi(1001)

    def test_esi_status_2(self, mock_update_or_create_esi):
        """When ESI error limit reached, then retry"""
        mock_update_or_create_esi.side_effect = EsiErrorLimitExceeded(5)

        with self.assertRaises(CeleryRetry):
            update_mail_entity_esi(1001)
