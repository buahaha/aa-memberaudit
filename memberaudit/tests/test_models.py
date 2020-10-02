from unittest.mock import patch

from django.test import TestCase
from django.utils.dateparse import parse_datetime

from allianceauth.tests.auth_utils import AuthUtils

from . import create_memberaudit_character, create_user_from_evecharacter
from ..models import Character, CharacterDetails
from .testdata.esi_client_stub import esi_client_stub
from .testdata.load_eveuniverse import load_eveuniverse
from .testdata.load_entities import load_entities
from .utils import reload_user, queryset_pks
from ..utils import NoSocketsTestCase

MODULE_PATH = "memberaudit.models"


class TestCharacterUserHasAccess(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_entities()
        cls.character = create_memberaudit_character(1001)

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


class TestCharacterManagerUserHasAccess(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_entities()
        cls.character_1001 = create_memberaudit_character(1001)
        cls.character_1002 = create_memberaudit_character(1002)
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


@patch(MODULE_PATH + ".esi")
class TestCharacterEsiAccess(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        cls.character = create_memberaudit_character(1001)

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

    def test_fetch_location(self, mock_esi):
        mock_esi.client = esi_client_stub

        result = self.character.fetch_location()
        self.assertEqual(result[0].id, 30004984)
