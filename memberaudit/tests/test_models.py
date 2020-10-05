import datetime as dt
from unittest.mock import patch, Mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils.dateparse import parse_datetime
from django.utils.timezone import now

from bravado.exception import HTTPNotFound, HTTPForbidden, HTTPUnauthorized

from eveuniverse.models import EveEntity, EveSolarSystem, EveType

from allianceauth.tests.auth_utils import AuthUtils

from . import create_memberaudit_character, create_user_from_evecharacter
from ..models import (
    Character,
    CharacterDetails,
    CharacterMail,
    CharacterUpdateStatus,
    CharacterWalletJournalEntry,
    Location,
    is_esi_online,
)
from .testdata.esi_client_stub import esi_client_stub
from .testdata.load_eveuniverse import load_eveuniverse
from .testdata.load_entities import load_entities
from .testdata.load_locations import load_locations
from .utils import reload_user, queryset_pks
from ..utils import NoSocketsTestCase

MODELS_PATH = "memberaudit.models"
MANAGERS_PATH = "memberaudit.managers"
TASKS_PATH = "memberaudit.tasks"


@patch(MODELS_PATH + ".esi")
class TestIsEsiOnline(NoSocketsTestCase):
    def test_normal(self, mock_esi):
        mock_esi.client = esi_client_stub

        result = is_esi_online()
        self.assertTrue(result)


class TestCharacterOtherMethods(NoSocketsTestCase):
    def test_update_section_method_name(self):
        result = Character.section_method_name(
            Character.UPDATE_SECTION_CORPORATION_HISTORY
        )
        self.assertEqual(result, "update_corporation_history")

        result = Character.section_method_name(Character.UPDATE_SECTION_MAILS)
        self.assertEqual(result, "update_mails")


class TestCharacterUserHasAccess(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_entities()

    def setUp(self) -> None:
        self.character = create_memberaudit_character(1001)

    def test_user_owning_character_has_access(self):
        """
        when user is the owner of the character
        then return True
        """
        self.assertTrue(
            self.character.user_has_access(self.character.character_ownership.user)
        )

    def test_other_user_has_no_access(self):
        """
        when user is not the owner of the character
        and has no special permissions
        then return False
        """
        user_2 = AuthUtils.create_user("Lex Luthor")
        self.assertFalse(self.character.user_has_access(user_2))

    def test_view_everything(self):
        """
        when user has view_everything permission
        then return True
        """
        user_3 = AuthUtils.create_user("Peter Parker")
        AuthUtils.add_permission_to_user_by_name("memberaudit.view_everything", user_3)
        user_3 = reload_user(user_3)
        self.assertTrue(self.character.user_has_access(user_3))

    def test_view_same_corporation_1(self):
        """
        when user has view_same_corporation permission
        and is in the same corporation as the character owner
        then return True
        """
        user_3, _ = create_user_from_evecharacter(1002)
        AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_same_corporation", user_3
        )
        user_3 = reload_user(user_3)
        self.assertTrue(self.character.user_has_access(user_3))

    def test_view_same_corporation_2(self):
        """
        when user has view_same_corporation permission
        and is NOT in the same corporation as the character owner
        then return False
        """

        user_3, _ = create_user_from_evecharacter(1003)
        AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_same_corporation", user_3
        )
        user_3 = reload_user(user_3)
        self.assertFalse(self.character.user_has_access(user_3))

    def test_view_same_alliance_1(self):
        """
        when user view_same_alliance permission
        and is in the same alliance as the character owner
        then return True
        """

        user_3, _ = create_user_from_evecharacter(1003)
        AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_same_alliance", user_3
        )
        user_3 = reload_user(user_3)
        self.assertTrue(self.character.user_has_access(user_3))

    def test_view_same_alliance_2(self):
        """
        when user has view_same_alliance permission
        and is NOT in the same alliance as the character owner
        then return False
        """
        user_3, _ = create_user_from_evecharacter(1101)
        AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_same_alliance", user_3
        )
        user_3 = reload_user(user_3)
        self.assertFalse(self.character.user_has_access(user_3))

    def test_recruiter_access_1(self):
        """
        when user has recruiter permission
        and character is shared
        then return True
        """
        self.character.is_shared = True
        self.character.save()
        user_3, _ = create_user_from_evecharacter(1101)
        AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_shared_characters", user_3
        )
        user_3 = reload_user(user_3)
        self.assertTrue(self.character.user_has_access(user_3))

    def test_recruiter_access_2(self):
        """
        when user has recruiter permission
        and character is NOT shared
        then return False
        """
        self.character.is_shared = False
        self.character.save()
        user_3, _ = create_user_from_evecharacter(1101)
        AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_shared_characters", user_3
        )
        user_3 = reload_user(user_3)
        self.assertFalse(self.character.user_has_access(user_3))


class TestCharacterManagerUserHasAccess(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_entities()
        cls.character_1001 = create_memberaudit_character(1001)
        cls.character_1002 = create_memberaudit_character(1002)
        cls.character_1002.is_shared = True
        cls.character_1002.save()
        cls.character_1003 = create_memberaudit_character(1003)
        cls.character_1101 = create_memberaudit_character(1101)
        cls.character_1102 = create_memberaudit_character(1102)

    def test_user_owning_character_has_access(self):
        """
        when user is the owner of characters
        then include those characters only
        """
        result_qs = Character.objects.user_has_access(
            user=self.character_1001.character_ownership.user
        )
        self.assertSetEqual(queryset_pks(result_qs), {self.character_1001.pk})

    def test_view_own_corporation(self):
        """
        when user has permission to view own corporation
        then include those characters only
        """
        user = self.character_1001.character_ownership.user
        AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_same_corporation", user
        )
        user = reload_user(user)
        result_qs = Character.objects.user_has_access(user=user)
        self.assertSetEqual(
            queryset_pks(result_qs),
            {self.character_1001.pk, self.character_1002.pk},
        )

    def test_view_own_alliance_1(self):
        """
        when user has permission to view own alliance
        then include those characters only
        """
        user = self.character_1001.character_ownership.user
        AuthUtils.add_permission_to_user_by_name("memberaudit.view_same_alliance", user)
        user = reload_user(user)
        result_qs = Character.objects.user_has_access(user=user)
        self.assertSetEqual(
            queryset_pks(result_qs),
            {self.character_1001.pk, self.character_1002.pk, self.character_1003.pk},
        )

    def test_view_own_alliance_2(self):
        """
        when user has permission to view own alliance
        and does not belong to any alliance
        then do not include any alliance characters
        """
        user = self.character_1102.character_ownership.user
        AuthUtils.add_permission_to_user_by_name("memberaudit.view_same_alliance", user)
        user = reload_user(user)
        result_qs = Character.objects.user_has_access(user=user)
        self.assertSetEqual(queryset_pks(result_qs), {self.character_1102.pk})

    def test_view_everything(self):
        """
        when user has permission to view everything
        then include all characters
        """
        user = self.character_1001.character_ownership.user
        AuthUtils.add_permission_to_user_by_name("memberaudit.view_everything", user)
        user = reload_user(user)
        result_qs = Character.objects.user_has_access(user=user)
        self.assertSetEqual(
            queryset_pks(result_qs),
            {
                self.character_1001.pk,
                self.character_1002.pk,
                self.character_1003.pk,
                self.character_1101.pk,
                self.character_1102.pk,
            },
        )

    def test_recruiter_access(self):
        """
        when user has recruiter permission
        then include own character plus shared characters
        """
        user = self.character_1102.character_ownership.user
        AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_shared_characters", user
        )
        user = reload_user(user)
        result_qs = Character.objects.user_has_access(user=user)
        self.assertSetEqual(
            queryset_pks(result_qs), {self.character_1002.pk, self.character_1102.pk}
        )


class TestCharacterHasTopic(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_entities()

    def setUp(self) -> None:
        self.character = create_memberaudit_character(1001)

    def test_has_mails_1(self):
        """when mails exist then return True"""
        CharacterMail.objects.create(character=self.character, mail_id=1)
        self.assertTrue(self.character.has_mails)

    def test_has_mails_2(self):
        """when update status is ok then return True"""
        CharacterUpdateStatus.objects.create(
            character=self.character,
            section=Character.UPDATE_SECTION_MAILS,
            is_success=True,
        )
        self.assertTrue(self.character.has_mails)

    def test_has_mails_3(self):
        """when no update status and no mails then return False"""
        self.assertFalse(self.character.has_mails)

    def test_has_wallet_journal_1(self):
        """when mails exist then return True"""
        CharacterWalletJournalEntry.objects.create(
            character=self.character, entry_id=1, amount=100, balance=100, date=now()
        )
        self.assertTrue(self.character.has_wallet_journal)

    def test_has_wallet_journal_2(self):
        """when update status is ok then return True"""
        CharacterUpdateStatus.objects.create(
            character=self.character,
            section=Character.UPDATE_SECTION_WALLET_JOURNAL,
            is_success=True,
        )
        self.assertTrue(self.character.has_wallet_journal)

    def test_has_wallet_journal_3(self):
        """when no update status and no mails then return False"""
        self.assertFalse(self.character.has_wallet_journal)


@patch(MODELS_PATH + ".esi")
class TestCharacterEsiAccess(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        load_locations()
        cls.character = create_memberaudit_character(1001)
        cls.token = cls.character.character_ownership.user.token_set.first()

    def test_update_character_details(self, mock_esi):
        mock_esi.client = esi_client_stub

        self.character.update_character_details()
        self.assertEqual(self.character.details.eve_ancestry.id, 11)
        self.assertEqual(
            self.character.details.birthday, parse_datetime("2015-03-24T11:37:00Z")
        )
        self.assertEqual(self.character.details.eve_bloodline.id, 1)
        self.assertEqual(self.character.details.corporation.id, 2001)
        self.assertEqual(self.character.details.description, "Scio me nihil scire")
        self.assertEqual(self.character.details.gender, CharacterDetails.GENDER_MALE)
        self.assertEqual(self.character.details.name, "Bruce Wayne")
        self.assertEqual(self.character.details.eve_race.id, 1)
        self.assertEqual(self.character.details.title, "All round pretty awesome guy")

    def test_update_corporation_history(self, mock_esi):
        mock_esi.client = esi_client_stub
        self.character.update_corporation_history()
        self.assertEqual(self.character.corporation_history.count(), 2)

        obj = self.character.corporation_history.get(record_id=500)
        self.assertEqual(obj.corporation.id, 2001)
        self.assertTrue(obj.is_deleted)
        self.assertEqual(obj.start_date, parse_datetime("2016-06-26T20:00:00Z"))

        obj = self.character.corporation_history.get(record_id=501)
        self.assertEqual(obj.corporation.id, 2002)
        self.assertFalse(obj.is_deleted)
        self.assertEqual(obj.start_date, parse_datetime("2016-07-26T20:00:00Z"))

    def test_update_jump_clones(self, mock_esi):
        mock_esi.client = esi_client_stub
        jita_44 = Location.objects.get(id=60003760)

        self.character.update_jump_clones()
        self.assertEqual(self.character.jump_clones.count(), 1)

        obj = self.character.jump_clones.get(jump_clone_id=12345)
        self.assertEqual(obj.location, jita_44)
        self.assertEqual(
            {x for x in obj.implants.values_list("eve_type", flat=True)},
            {19540, 19551, 19553},
        )

    def test_update_mails(self, mock_esi):
        mock_esi.client = esi_client_stub

        self.character.update_mails()

        # mailing lists
        self.assertEqual(self.character.mailing_lists.count(), 2)

        obj = self.character.mailing_lists.get(list_id=1)
        self.assertEqual(obj.name, "Dummy 1")

        obj = self.character.mailing_lists.get(list_id=2)
        self.assertEqual(obj.name, "Dummy 2")

        # mail labels
        self.assertEqual(self.character.mail_labels.count(), 2)
        self.assertEqual(self.character.unread_mail_count.total, 5)

        obj = self.character.mail_labels.get(label_id=3)
        self.assertEqual(obj.name, "PINK")
        self.assertEqual(obj.unread_count, 4)
        self.assertEqual(obj.color, "#660066")

        obj = self.character.mail_labels.get(label_id=17)
        self.assertEqual(obj.name, "WHITE")
        self.assertEqual(obj.unread_count, 1)
        self.assertEqual(obj.color, "#ffffff")

        # mail
        self.assertEqual(self.character.mails.count(), 2)

        obj = self.character.mails.get(mail_id=1)
        self.assertEqual(obj.from_entity.id, 1002)
        self.assertTrue(obj.is_read)
        self.assertEqual(obj.subject, "Mail 1")
        self.assertEqual(obj.timestamp, parse_datetime("2015-09-30T16:07:00Z"))
        self.assertEqual(obj.body, "blah blah blah")
        self.assertTrue(obj.recipients.filter(eve_entity_id=1001).exists())
        self.assertTrue(obj.recipients.filter(mailing_list__list_id=1).exists())

        obj = self.character.mails.get(mail_id=2)
        self.assertEqual(obj.from_entity.id, 1101)
        self.assertFalse(obj.is_read)
        self.assertEqual(obj.subject, "Mail 2")
        self.assertEqual(obj.timestamp, parse_datetime("2015-09-30T18:07:00Z"))

    def test_update_skills(self, mock_esi):
        mock_esi.client = esi_client_stub

        self.character.update_skills()
        self.assertEqual(self.character.skillpoints.total, 30_000)
        self.assertEqual(self.character.skillpoints.unallocated, 1_000)

        self.assertEqual(self.character.skills.count(), 2)

        skill = self.character.skills.get(eve_type_id=24311)
        self.assertEqual(skill.active_skill_level, 3)
        self.assertEqual(skill.skillpoints_in_skill, 20_000)
        self.assertEqual(skill.trained_skill_level, 4)

        skill = self.character.skills.get(eve_type_id=24312)
        self.assertEqual(skill.active_skill_level, 1)
        self.assertEqual(skill.skillpoints_in_skill, 10_000)
        self.assertEqual(skill.trained_skill_level, 1)

    def test_update_wallet_balance(self, mock_esi):
        mock_esi.client = esi_client_stub

        self.character.update_wallet_balance()
        self.assertEqual(self.character.wallet_balance.total, 123456789)

    def test_update_wallet_journal(self, mock_esi):
        mock_esi.client = esi_client_stub

        self.character.update_wallet_journal()
        self.assertEqual(self.character.wallet_journal.count(), 1)
        obj = self.character.wallet_journal.first()
        self.assertEqual(obj.amount, -100_000)
        self.assertEqual(float(obj.balance), 500_000.43)
        self.assertEqual(obj.context_id, 4)
        self.assertEqual(obj.context_id_type, obj.CONTEXT_ID_TYPE_CONTRACT_ID)
        self.assertEqual(obj.date, parse_datetime("2018-02-23T14:31:32Z"))
        self.assertEqual(obj.description, "Contract Deposit")
        self.assertEqual(obj.first_party.id, 2001)
        self.assertEqual(obj.entry_id, 89)
        self.assertEqual(obj.ref_type, "contract_deposit")
        self.assertEqual(obj.second_party.id, 2002)

    def test_fetch_location(self, mock_esi):
        mock_esi.client = esi_client_stub

        result = self.character.fetch_location()
        self.assertEqual(result[0].id, 30004984)


@patch(MANAGERS_PATH + ".esi")
class TestLocationManager(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        cls.jita = EveSolarSystem.objects.get(id=30000142)
        cls.amamake = EveSolarSystem.objects.get(id=30002537)
        cls.astrahus = EveType.objects.get(id=35832)
        cls.athanor = EveType.objects.get(id=35835)
        cls.jita_trade_hub = EveType.objects.get(id=52678)
        cls.corporation_2001 = EveEntity.objects.get(id=2001)
        cls.corporation_2002 = EveEntity.objects.get(id=2002)
        cls.character = create_memberaudit_character(1001)
        cls.token = cls.character.character_ownership.user.token_set.first()

    # Structures

    def test_can_create_structure(self, mock_esi):
        mock_esi.client = esi_client_stub

        obj, created = Location.objects.update_or_create_esi(
            id=1000000000001, token=self.token
        )
        self.assertTrue(created)
        self.assertEqual(obj.id, 1000000000001)
        self.assertEqual(obj.name, "Test Structure Alpha")
        self.assertEqual(obj.eve_solar_system, self.amamake)
        self.assertEqual(obj.eve_type, self.astrahus)
        self.assertEqual(obj.owner, self.corporation_2001)

    def test_can_update_structure(self, mock_esi):
        mock_esi.client = esi_client_stub

        obj, _ = Location.objects.update_or_create_esi(
            id=1000000000001, token=self.token
        )
        obj.name = "Not my structure"
        obj.eve_solar_system = self.jita
        obj.eve_type = self.jita_trade_hub
        obj.owner = self.corporation_2002
        obj.save()
        obj, created = Location.objects.update_or_create_esi(
            id=1000000000001, token=self.token
        )
        self.assertFalse(created)
        self.assertEqual(obj.id, 1000000000001)
        self.assertEqual(obj.name, "Test Structure Alpha")
        self.assertEqual(obj.eve_solar_system, self.amamake)
        self.assertEqual(obj.eve_type, self.astrahus)
        self.assertEqual(obj.owner, self.corporation_2001)

    def test_does_not_update_existing_location(self, mock_esi):
        mock_esi.client = esi_client_stub

        obj_existing = Location.objects.create(
            id=1000000000001,
            name="Existing Structure",
            eve_solar_system=self.jita,
            eve_type=self.jita_trade_hub,
            owner=self.corporation_2002,
        )
        obj, created = Location.objects.get_or_create_esi(
            id=1000000000001, token=self.token
        )
        self.assertFalse(created)
        self.assertEqual(obj, obj_existing)

    def test_always_update_existing_empty_locations_after_grace_period_1(
        self, mock_esi
    ):
        mock_esi.client = esi_client_stub

        Location.objects.create(id=1000000000001)
        obj, _ = Location.objects.get_or_create_esi(id=1000000000001, token=self.token)
        self.assertIsNone(obj.eve_solar_system)

    def test_always_update_existing_empty_locations_after_grace_period_2(
        self, mock_esi
    ):
        mock_esi.client = esi_client_stub

        mocked_update_at = now() - dt.timedelta(minutes=6)
        with patch("django.utils.timezone.now", Mock(return_value=mocked_update_at)):
            Location.objects.create(id=1000000000001)
            obj, _ = Location.objects.get_or_create_esi(
                id=1000000000001, token=self.token
            )
        self.assertEqual(obj.eve_solar_system, self.amamake)

    @patch(MANAGERS_PATH + ".MEMBERAUDIT_LOCATION_STALE_HOURS", 24)
    def test_always_update_existing_locations_which_are_stale(self, mock_esi):
        mock_esi.client = esi_client_stub

        mocked_update_at = now() - dt.timedelta(hours=25)
        with patch("django.utils.timezone.now", Mock(return_value=mocked_update_at)):
            Location.objects.create(
                id=1000000000001,
                name="Existing Structure",
                eve_solar_system=self.jita,
                eve_type=self.jita_trade_hub,
                owner=self.corporation_2002,
            )
        obj, created = Location.objects.get_or_create_esi(
            id=1000000000001, token=self.token
        )
        self.assertFalse(created)
        self.assertEqual(obj.eve_solar_system, self.amamake)

    def test_propagates_http_error_on_structure_create(self, mock_esi):
        mock_esi.client = esi_client_stub

        with self.assertRaises(HTTPNotFound):
            Location.objects.update_or_create_esi(
                id=42, token=self.token, add_unknown=False
            )

    def test_propagates_exceptions_on_structure_create(self, mock_esi):
        mock_esi.client.Universe.get_universe_structures_structure_id.side_effect = (
            RuntimeError
        )

        with self.assertRaises(RuntimeError):
            Location.objects.update_or_create_esi(
                id=42, token=self.token, add_unknown=False
            )

    def test_can_create_empty_location_on_access_error_1(self, mock_esi):
        mock_esi.client.Universe.get_universe_structures_structure_id.side_effect = (
            HTTPForbidden(Mock())
        )

        obj, created = Location.objects.update_or_create_esi(
            id=42, token=self.token, add_unknown=True
        )
        self.assertTrue(created)
        self.assertEqual(obj.id, 42)

    def test_can_create_empty_location_on_access_error_2(self, mock_esi):
        mock_esi.client.Universe.get_universe_structures_structure_id.side_effect = (
            HTTPUnauthorized(Mock())
        )

        obj, created = Location.objects.update_or_create_esi(
            id=42, token=self.token, add_unknown=True
        )
        self.assertTrue(created)
        self.assertEqual(obj.id, 42)

    def test_does_not_creates_empty_location_on_access_errors_if_requested(
        self, mock_esi
    ):
        mock_esi.client.Universe.get_universe_structures_structure_id.side_effect = (
            RuntimeError
        )
        with self.assertRaises(RuntimeError):
            Location.objects.update_or_create_esi(
                id=42, token=self.token, add_unknown=True
            )

    # Stations

    def test_can_create_station(self, mock_esi):
        mock_esi.client = esi_client_stub

        obj, created = Location.objects.update_or_create_esi(
            id=60003760, token=self.token
        )
        self.assertTrue(created)
        self.assertEqual(obj.id, 60003760)
        self.assertEqual(obj.name, "Jita IV - Moon 4 - Caldari Navy Assembly Plant")
        self.assertEqual(obj.eve_solar_system, self.jita)
        self.assertEqual(obj.eve_type, self.jita_trade_hub)
        self.assertEqual(obj.owner, self.corporation_2002)

    def test_can_update_station(self, mock_esi):
        mock_esi.client = esi_client_stub

        obj, created = Location.objects.update_or_create_esi(
            id=60003760, token=self.token
        )
        obj.name = "Not my station"
        obj.eve_solar_system = self.amamake
        obj.eve_type = self.astrahus
        obj.owner = self.corporation_2001
        obj.save()

        obj, created = Location.objects.update_or_create_esi(
            id=60003760, token=self.token
        )
        self.assertFalse(created)
        self.assertEqual(obj.id, 60003760)
        self.assertEqual(obj.name, "Jita IV - Moon 4 - Caldari Navy Assembly Plant")
        self.assertEqual(obj.eve_solar_system, self.jita)
        self.assertEqual(obj.eve_type, self.jita_trade_hub)
        self.assertEqual(obj.owner, self.corporation_2002)

    def test_propagates_http_error_on_station_create(self, mock_esi):
        mock_esi.client = esi_client_stub

        with self.assertRaises(HTTPNotFound):
            Location.objects.update_or_create_esi(
                id=42, token=self.token, add_unknown=False
            )


@patch(MANAGERS_PATH + ".esi")
class TestLocationManagerAsync(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        cls.jita = EveSolarSystem.objects.get(id=30000142)
        cls.amamake = EveSolarSystem.objects.get(id=30002537)
        cls.astrahus = EveType.objects.get(id=35832)
        cls.athanor = EveType.objects.get(id=35835)
        cls.jita_trade_hub = EveType.objects.get(id=52678)
        cls.corporation_2001 = EveEntity.objects.get(id=2001)
        cls.corporation_2002 = EveEntity.objects.get(id=2002)
        cls.character = create_memberaudit_character(1001)
        cls.token = cls.character.character_ownership.user.token_set.first()

    def setUp(self) -> None:
        cache.clear()

    @override_settings(CELERY_ALWAYS_EAGER=True)
    def test_can_create_structure_async(self, mock_esi):
        mock_esi.client = esi_client_stub

        obj, created = Location.objects.update_or_create_esi_async(
            id=1000000000001, token=self.token
        )
        self.assertTrue(created)
        self.assertEqual(obj.id, 1000000000001)
        self.assertIsNone(obj.eve_solar_system)
        self.assertIsNone(obj.eve_type)

        obj.refresh_from_db()
        self.assertEqual(obj.name, "Test Structure Alpha")
        self.assertEqual(obj.eve_solar_system, self.amamake)
        self.assertEqual(obj.eve_type, self.astrahus)
        self.assertEqual(obj.owner, self.corporation_2001)
