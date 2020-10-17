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
    CharacterAsset,
    CharacterContact,
    CharacterContactLabel,
    CharacterContract,
    CharacterContractBid,
    CharacterContractItem,
    CharacterDetails,
    CharacterMail,
    CharacterMailingList,
    CharacterMailLabel,
    CharacterMailRecipient,
    CharacterSkill,
    CharacterSkillqueueEntry,
    CharacterUpdateStatus,
    CharacterWalletJournalEntry,
    Doctrine,
    DoctrineShip,
    DoctrineShipSkill,
    Location,
    is_esi_online,
)
from .testdata.esi_client_stub import esi_client_stub
from .testdata.load_eveuniverse import load_eveuniverse
from .testdata.load_entities import load_entities
from .testdata.load_locations import load_locations
from .utils import queryset_pks
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
        user_3 = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_everything", user_3
        )
        self.assertTrue(self.character.user_has_access(user_3))

    def test_view_same_corporation_1(self):
        """
        when user has view_same_corporation permission
        and is in the same corporation as the character owner
        then return True
        """
        user_3, _ = create_user_from_evecharacter(1002)
        user_3 = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_same_corporation", user_3
        )
        self.assertTrue(self.character.user_has_access(user_3))

    def test_view_same_corporation_2(self):
        """
        when user has view_same_corporation permission
        and is NOT in the same corporation as the character owner
        then return False
        """

        user_3, _ = create_user_from_evecharacter(1003)
        user_3 = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_same_corporation", user_3
        )
        self.assertFalse(self.character.user_has_access(user_3))

    def test_view_same_alliance_1(self):
        """
        when user view_same_alliance permission
        and is in the same alliance as the character owner
        then return True
        """

        user_3, _ = create_user_from_evecharacter(1003)
        user_3 = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_same_alliance", user_3
        )
        self.assertTrue(self.character.user_has_access(user_3))

    def test_view_same_alliance_2(self):
        """
        when user has view_same_alliance permission
        and is NOT in the same alliance as the character owner
        then return False
        """
        user_3, _ = create_user_from_evecharacter(1101)
        user_3 = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_same_alliance", user_3
        )
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
        user_3 = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_shared_characters", user_3
        )
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
        user_3 = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_shared_characters", user_3
        )
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
        user = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_same_corporation", user
        )
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
        user = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_same_alliance", user
        )
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
        user = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_same_alliance", user
        )
        result_qs = Character.objects.user_has_access(user=user)
        self.assertSetEqual(queryset_pks(result_qs), {self.character_1102.pk})

    def test_view_everything(self):
        """
        when user has permission to view everything
        then include all characters
        """
        user = self.character_1001.character_ownership.user
        user = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_everything", user
        )
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
        user = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_shared_characters", user
        )
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


@override_settings(CELERY_ALWAYS_EAGER=True)
@patch(MODELS_PATH + ".esi")
class TestCharacterEsiAccess(NoSocketsTestCase):
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

    def test_update_assets_1(self, mock_esi):
        """can create assets from scratch"""
        mock_esi.client = esi_client_stub

        self.character_1001.update_assets()
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

        self.character_1001.update_assets()
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

        self.character_1001.update_assets()
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

        self.character_1001.update_assets()
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

    def test_update_contact_labels_1(self, mock_esi):
        """can create new contact labels from scratch"""
        mock_esi.client = esi_client_stub

        self.character_1001.update_contacts()
        self.assertEqual(self.character_1001.contact_labels.count(), 2)

        label = self.character_1001.contact_labels.get(label_id=1)
        self.assertEqual(label.name, "friend")

        label = self.character_1001.contact_labels.get(label_id=2)
        self.assertEqual(label.name, "pirate")

    def test_update_contact_labels_2(self, mock_esi):
        """can remove obsolete labels"""
        mock_esi.client = esi_client_stub
        CharacterContactLabel.objects.create(
            character=self.character_1001, label_id=99, name="Obsolete"
        )

        self.character_1001.update_contacts()
        self.assertEqual(
            {x.label_id for x in self.character_1001.contact_labels.all()}, {1, 2}
        )

    def test_update_contact_labels_3(self, mock_esi):
        """can update existing labels"""
        mock_esi.client = esi_client_stub
        CharacterContactLabel.objects.create(
            character=self.character_1001, label_id=1, name="Obsolete"
        )

        self.character_1001.update_contacts()
        self.assertEqual(
            {x.label_id for x in self.character_1001.contact_labels.all()}, {1, 2}
        )

        label = self.character_1001.contact_labels.get(label_id=1)
        self.assertEqual(label.name, "friend")

    def test_update_contacts_1(self, mock_esi):
        """can create contacts"""
        mock_esi.client = esi_client_stub

        self.character_1001.update_contacts()
        self.assertEqual(self.character_1001.contacts.count(), 2)

        obj = self.character_1001.contacts.get(contact_id=1101)
        self.assertEqual(obj.contact.category, EveEntity.CATEGORY_CHARACTER)
        self.assertFalse(obj.is_blocked)
        self.assertTrue(obj.is_watched)
        self.assertEqual(obj.standing, -10)
        self.assertEqual({x.label_id for x in obj.labels.all()}, {2})

        obj = self.character_1001.contacts.get(contact_id=2002)
        self.assertEqual(obj.contact.category, EveEntity.CATEGORY_CORPORATION)
        self.assertFalse(obj.is_blocked)
        self.assertFalse(obj.is_watched)
        self.assertEqual(obj.standing, 5)
        self.assertEqual(obj.labels.count(), 0)

    def test_update_contacts_2(self, mock_esi):
        """can remove obsolete contacts"""
        mock_esi.client = esi_client_stub
        CharacterContact.objects.create(
            character=self.character_1001,
            contact=EveEntity.objects.get(id=3101),
            standing=-5,
        )
        self.character_1001.update_contacts()
        self.assertEqual(
            {x.contact_id for x in self.character_1001.contacts.all()}, {1101, 2002}
        )

    def test_update_contacts_3(self, mock_esi):
        """can update existing contacts"""
        mock_esi.client = esi_client_stub
        my_label = CharacterContactLabel.objects.create(
            character=self.character_1001, label_id=1, name="Dummy"
        )
        my_contact = CharacterContact.objects.create(
            character=self.character_1001,
            contact=EveEntity.objects.get(id=1101),
            is_blocked=True,
            is_watched=False,
            standing=-5,
        )
        my_contact.labels.add(my_label)

        self.character_1001.update_contacts()

        obj = self.character_1001.contacts.get(contact_id=1101)
        self.assertEqual(obj.contact.category, EveEntity.CATEGORY_CHARACTER)
        self.assertFalse(obj.is_blocked)
        self.assertTrue(obj.is_watched)
        self.assertEqual(obj.standing, -10)
        self.assertEqual({x.label_id for x in obj.labels.all()}, {2})

    @override_settings(CELERY_ALWAYS_EAGER=True)
    def test_update_contracts_1(self, mock_esi):
        """can create new courier contract"""
        mock_esi.client = esi_client_stub

        self.character_1001.update_contracts()
        self.assertEqual(self.character_1001.contracts.count(), 3)

        obj = self.character_1001.contracts.get(contract_id=100000001)
        self.assertEqual(obj.contract_type, CharacterContract.TYPE_COURIER)
        self.assertEqual(obj.acceptor, EveEntity.objects.get(id=1101))
        self.assertEqual(obj.assignee, EveEntity.objects.get(id=2101))
        self.assertEqual(obj.availability, CharacterContract.AVAILABILITY_PERSONAL)
        self.assertIsNone(obj.buyout)
        self.assertEqual(float(obj.collateral), 550000000.0)
        self.assertEqual(obj.date_accepted, parse_datetime("2019-10-06T13:15:21Z"))
        self.assertEqual(obj.date_completed, parse_datetime("2019-10-07T13:15:21Z"))
        self.assertEqual(obj.date_expired, parse_datetime("2019-10-09T13:15:21Z"))
        self.assertEqual(obj.date_issued, parse_datetime("2019-10-02T13:15:21Z"))
        self.assertEqual(obj.days_to_complete, 3)
        self.assertEqual(obj.end_location, self.structure_1)
        self.assertFalse(obj.for_corporation)
        self.assertEqual(obj.issuer_corporation, EveEntity.objects.get(id=2001))
        self.assertEqual(obj.issuer, EveEntity.objects.get(id=1001))
        self.assertEqual(float(obj.price), 0.0)
        self.assertEqual(float(obj.reward), 500000000.0)
        self.assertEqual(obj.start_location, self.jita_44)
        self.assertEqual(obj.status, CharacterContract.STATUS_IN_PROGRESS)
        self.assertEqual(obj.title, "Test 1")
        self.assertEqual(obj.volume, 486000.0)

    def test_update_contracts_2(self, mock_esi):
        """can create new item exchange contract"""
        mock_esi.client = esi_client_stub

        self.character_1001.update_contracts()
        obj = self.character_1001.contracts.get(contract_id=100000002)
        self.assertEqual(obj.contract_type, CharacterContract.TYPE_ITEM_EXCHANGE)
        self.assertEqual(float(obj.price), 270000000.0)
        self.assertEqual(obj.volume, 486000.0)
        self.assertEqual(obj.status, CharacterContract.STATUS_FINISHED)
        self.assertEqual(obj.items.count(), 2)

        item = obj.items.get(record_id=1)
        self.assertTrue(item.is_included)
        self.assertFalse(item.is_singleton)
        self.assertEqual(item.quantity, 3)
        self.assertEqual(item.eve_type, EveType.objects.get(id=19540))

        item = obj.items.get(record_id=2)
        self.assertTrue(item.is_included)
        self.assertFalse(item.is_singleton)
        self.assertEqual(item.quantity, 5)
        self.assertEqual(item.raw_quantity, -1)
        self.assertEqual(item.eve_type, EveType.objects.get(id=19551))

    def test_update_contracts_3(self, mock_esi):
        """can create new auction contract"""
        mock_esi.client = esi_client_stub

        self.character_1001.update_contracts()
        obj = self.character_1001.contracts.get(contract_id=100000003)
        self.assertEqual(obj.contract_type, CharacterContract.TYPE_AUCTION)
        self.assertEqual(float(obj.buyout), 200_000_000.0)
        self.assertEqual(float(obj.price), 20_000_000.0)
        self.assertEqual(obj.volume, 400.0)
        self.assertEqual(obj.status, CharacterContract.STATUS_OUTSTANDING)
        self.assertEqual(obj.items.count(), 1)

        bid = obj.bids.get(bid_id=1)
        self.assertEqual(float(bid.amount), 1_000_000.23)
        self.assertEqual(bid.date_bid, parse_datetime("2017-01-01T10:10:10Z"))
        self.assertEqual(bid.bidder, EveEntity.objects.get(id=1101))

    def test_update_contracts_4(self, mock_esi):
        """old contracts must be kept"""
        mock_esi.client = esi_client_stub

        CharacterContract.objects.create(
            character=self.character_1001,
            contract_id=190000001,
            availability=CharacterContract.AVAILABILITY_PERSONAL,
            contract_type=CharacterContract.TYPE_COURIER,
            assignee=EveEntity.objects.get(id=1002),
            date_issued=now() - dt.timedelta(days=60),
            date_expired=now() - dt.timedelta(days=30),
            for_corporation=False,
            issuer=EveEntity.objects.get(id=1001),
            issuer_corporation=EveEntity.objects.get(id=2001),
            status=CharacterContract.STATUS_IN_PROGRESS,
            start_location=self.jita_44,
            end_location=self.structure_1,
            title="Old contract",
        )

        self.character_1001.update_contracts()
        self.assertEqual(self.character_1001.contracts.count(), 4)

    def test_update_contracts_5(self, mock_esi):
        """Existing contracts are updated"""
        mock_esi.client = esi_client_stub

        CharacterContract.objects.create(
            character=self.character_1001,
            contract_id=100000001,
            availability=CharacterContract.AVAILABILITY_PERSONAL,
            contract_type=CharacterContract.TYPE_COURIER,
            assignee=EveEntity.objects.get(id=2101),
            date_issued=parse_datetime("2019-10-02T13:15:21Z"),
            date_expired=parse_datetime("2019-10-09T13:15:21Z"),
            for_corporation=False,
            issuer=EveEntity.objects.get(id=1001),
            issuer_corporation=EveEntity.objects.get(id=2001),
            status=CharacterContract.STATUS_OUTSTANDING,
            start_location=self.jita_44,
            end_location=self.structure_1,
            title="Test 1",
            collateral=550000000,
            reward=500000000,
            volume=486000,
            days_to_complete=3,
        )

        self.character_1001.update_contracts()

        obj = self.character_1001.contracts.get(contract_id=100000001)
        self.assertEqual(obj.contract_type, CharacterContract.TYPE_COURIER)
        self.assertEqual(obj.acceptor, EveEntity.objects.get(id=1101))
        self.assertEqual(obj.assignee, EveEntity.objects.get(id=2101))
        self.assertEqual(obj.availability, CharacterContract.AVAILABILITY_PERSONAL)
        self.assertIsNone(obj.buyout)
        self.assertEqual(float(obj.collateral), 550000000.0)
        self.assertEqual(obj.date_accepted, parse_datetime("2019-10-06T13:15:21Z"))
        self.assertEqual(obj.date_completed, parse_datetime("2019-10-07T13:15:21Z"))
        self.assertEqual(obj.date_expired, parse_datetime("2019-10-09T13:15:21Z"))
        self.assertEqual(obj.date_issued, parse_datetime("2019-10-02T13:15:21Z"))
        self.assertEqual(obj.days_to_complete, 3)
        self.assertEqual(obj.end_location, self.structure_1)
        self.assertFalse(obj.for_corporation)
        self.assertEqual(obj.issuer_corporation, EveEntity.objects.get(id=2001))
        self.assertEqual(obj.issuer, EveEntity.objects.get(id=1001))
        self.assertEqual(float(obj.reward), 500000000.0)
        self.assertEqual(obj.start_location, self.jita_44)
        self.assertEqual(obj.status, CharacterContract.STATUS_IN_PROGRESS)
        self.assertEqual(obj.title, "Test 1")
        self.assertEqual(obj.volume, 486000.0)

    def test_update_contracts_6(self, mock_esi):
        """can add new bids to auction contract"""
        mock_esi.client = esi_client_stub

        contract = CharacterContract.objects.create(
            character=self.character_1001,
            contract_id=100000003,
            availability=CharacterContract.AVAILABILITY_PERSONAL,
            contract_type=CharacterContract.TYPE_AUCTION,
            assignee=EveEntity.objects.get(id=2101),
            date_issued=parse_datetime("2019-10-02T13:15:21Z"),
            date_expired=parse_datetime("2019-10-09T13:15:21Z"),
            for_corporation=False,
            issuer=EveEntity.objects.get(id=1001),
            issuer_corporation=EveEntity.objects.get(id=2001),
            status=CharacterContract.STATUS_OUTSTANDING,
            start_location=self.jita_44,
            end_location=self.jita_44,
            buyout=200_000_000,
            price=20_000_000,
            volume=400,
        )
        CharacterContractBid.objects.create(
            contract=contract,
            bid_id=2,
            amount=21_000_000,
            bidder=EveEntity.objects.get(id=1003),
            date_bid=now(),
        )

        self.character_1001.update_contracts()

        obj = self.character_1001.contracts.get(contract_id=100000003)
        self.assertEqual(obj.bids.count(), 2)

        bid = obj.bids.get(bid_id=1)
        self.assertEqual(float(bid.amount), 1_000_000.23)
        self.assertEqual(bid.date_bid, parse_datetime("2017-01-01T10:10:10Z"))
        self.assertEqual(bid.bidder, EveEntity.objects.get(id=1101))

        bid = obj.bids.get(bid_id=2)
        self.assertEqual(float(bid.amount), 21_000_000)

    def test_update_character_details(self, mock_esi):
        mock_esi.client = esi_client_stub

        self.character_1001.update_character_details()
        self.assertEqual(self.character_1001.details.eve_ancestry.id, 11)
        self.assertEqual(
            self.character_1001.details.birthday, parse_datetime("2015-03-24T11:37:00Z")
        )
        self.assertEqual(self.character_1001.details.eve_bloodline.id, 1)
        self.assertEqual(self.character_1001.details.corporation.id, 2001)
        self.assertEqual(self.character_1001.details.description, "Scio me nihil scire")
        self.assertEqual(
            self.character_1001.details.gender, CharacterDetails.GENDER_MALE
        )
        self.assertEqual(self.character_1001.details.name, "Bruce Wayne")
        self.assertEqual(self.character_1001.details.eve_race.id, 1)
        self.assertEqual(
            self.character_1001.details.title, "All round pretty awesome guy"
        )

    def test_update_corporation_history(self, mock_esi):
        mock_esi.client = esi_client_stub
        self.character_1001.update_corporation_history()
        self.assertEqual(self.character_1001.corporation_history.count(), 2)

        obj = self.character_1001.corporation_history.get(record_id=500)
        self.assertEqual(obj.corporation.id, 2001)
        self.assertTrue(obj.is_deleted)
        self.assertEqual(obj.start_date, parse_datetime("2016-06-26T20:00:00Z"))

        obj = self.character_1001.corporation_history.get(record_id=501)
        self.assertEqual(obj.corporation.id, 2002)
        self.assertFalse(obj.is_deleted)
        self.assertEqual(obj.start_date, parse_datetime("2016-07-26T20:00:00Z"))

    def test_update_jump_clones_1(self, mock_esi):
        """can update jump clones with implants"""
        mock_esi.client = esi_client_stub

        self.character_1001.update_jump_clones()
        self.assertEqual(self.character_1001.jump_clones.count(), 1)

        obj = self.character_1001.jump_clones.get(jump_clone_id=12345)
        self.assertEqual(obj.location, self.jita_44)
        self.assertEqual(
            {x for x in obj.implants.values_list("eve_type", flat=True)},
            {19540, 19551, 19553},
        )

    def test_update_jump_clones_2(self, mock_esi):
        """can update jump clones without implants"""
        mock_esi.client = esi_client_stub

        self.character_1002.update_jump_clones()
        self.assertEqual(self.character_1002.jump_clones.count(), 1)

        obj = self.character_1002.jump_clones.get(jump_clone_id=12345)
        self.assertEqual(obj.location, self.jita_44)
        self.assertEqual(obj.implants.count(), 0)

    def test_update_mailing_lists_1(self, mock_esi):
        """can create new mailing lists from scratch"""
        mock_esi.client = esi_client_stub

        self.character_1001.update_mails()

        self.assertSetEqual(
            set(self.character_1001.mailing_lists.values_list("list_id", flat=True)),
            {9001, 9002},
        )

        obj = self.character_1001.mailing_lists.get(list_id=9001)
        self.assertEqual(obj.name, "Dummy 1")

        obj = self.character_1001.mailing_lists.get(list_id=9002)
        self.assertEqual(obj.name, "Dummy 2")

    def test_update_mailing_lists_2(self, mock_esi):
        """removes obsolete mailing lists"""
        mock_esi.client = esi_client_stub
        CharacterMailingList.objects.create(
            character=self.character_1001, list_id=5, name="Obsolete"
        )

        self.character_1001.update_mails()

        self.assertSetEqual(
            set(self.character_1001.mailing_lists.values_list("list_id", flat=True)),
            {9001, 9002},
        )

    def test_update_mail_labels_1(self, mock_esi):
        """can create from scratch"""
        mock_esi.client = esi_client_stub

        self.character_1001.update_mails()

        self.assertEqual(self.character_1001.unread_mail_count.total, 5)
        self.assertSetEqual(
            set(self.character_1001.mail_labels.values_list("label_id", flat=True)),
            {3, 17},
        )

        obj = self.character_1001.mail_labels.get(label_id=3)
        self.assertEqual(obj.name, "PINK")
        self.assertEqual(obj.unread_count, 4)
        self.assertEqual(obj.color, "#660066")

        obj = self.character_1001.mail_labels.get(label_id=17)
        self.assertEqual(obj.name, "WHITE")
        self.assertEqual(obj.unread_count, 1)
        self.assertEqual(obj.color, "#ffffff")

    def test_update_mail_labels_2(self, mock_esi):
        """will remove obsolete labels"""
        mock_esi.client = esi_client_stub
        CharacterMailLabel.objects.create(
            character=self.character_1001, label_id=666, name="Obsolete"
        )

        self.character_1001.update_mails()

        self.assertSetEqual(
            set(self.character_1001.mail_labels.values_list("label_id", flat=True)),
            {3, 17},
        )

    def test_update_mail_labels_3(self, mock_esi):
        """will update existing labels"""
        mock_esi.client = esi_client_stub
        CharacterMailLabel.objects.create(
            character=self.character_1001,
            label_id=3,
            name="Update me",
            unread_count=0,
            color=0,
        )

        self.character_1001.update_mails()

        self.assertSetEqual(
            set(self.character_1001.mail_labels.values_list("label_id", flat=True)),
            {3, 17},
        )

        obj = self.character_1001.mail_labels.get(label_id=3)
        self.assertEqual(obj.name, "PINK")
        self.assertEqual(obj.unread_count, 4)
        self.assertEqual(obj.color, "#660066")

    def test_update_mails_1(self, mock_esi):
        """can create new mail from scratch"""
        mock_esi.client = esi_client_stub

        self.character_1001.update_mails()
        self.assertSetEqual(
            set(self.character_1001.mails.values_list("mail_id", flat=True)),
            {1, 2},
        )

        obj = self.character_1001.mails.get(mail_id=1)
        self.assertEqual(obj.from_entity.id, 1002)
        self.assertIsNone(obj.from_mailing_list)
        self.assertTrue(obj.is_read)
        self.assertEqual(obj.subject, "Mail 1")
        self.assertEqual(obj.timestamp, parse_datetime("2015-09-30T16:07:00Z"))
        self.assertEqual(obj.body, "blah blah blah")
        self.assertTrue(obj.recipients.filter(eve_entity_id=1001).exists())
        self.assertTrue(obj.recipients.filter(mailing_list__list_id=9001).exists())

        obj = self.character_1001.mails.get(mail_id=2)
        self.assertIsNone(obj.from_entity)
        self.assertEqual(obj.from_mailing_list.list_id, 9001)
        self.assertFalse(obj.is_read)
        self.assertEqual(obj.subject, "Mail 2")
        self.assertEqual(obj.timestamp, parse_datetime("2015-09-30T18:07:00Z"))
        self.assertEqual(obj.body, "Another mail")

    def test_update_mails_2(self, mock_esi):
        """can update existing mail"""
        mock_esi.client = esi_client_stub
        mail = CharacterMail.objects.create(
            character=self.character_1001,
            mail_id=1,
            from_entity=EveEntity.objects.get(id=1002),
            subject="Mail 1",
            body="blah blah blah",
            is_read=False,
            timestamp=parse_datetime("2015-09-30T16:07:00Z"),
        )
        CharacterMailRecipient.objects.create(
            mail=mail, eve_entity=EveEntity.objects.get(id=1001)
        )

        self.character_1001.update_mails()
        self.assertSetEqual(
            set(self.character_1001.mails.values_list("mail_id", flat=True)),
            {1, 2},
        )

        obj = self.character_1001.mails.get(mail_id=1)
        self.assertEqual(obj.from_entity.id, 1002)
        self.assertIsNone(obj.from_mailing_list)
        self.assertTrue(obj.is_read)
        self.assertEqual(obj.subject, "Mail 1")
        self.assertEqual(obj.timestamp, parse_datetime("2015-09-30T16:07:00Z"))
        self.assertEqual(obj.body, "blah blah blah")
        self.assertTrue(obj.recipients.filter(eve_entity_id=1001).exists())

    def test_update_skill_queue(self, mock_esi):
        mock_esi.client = esi_client_stub

        self.character_1001.update_skill_queue()
        self.assertEqual(self.character_1001.skillqueue.count(), 2)

        entry = self.character_1001.skillqueue.get(skill_id=24311)
        self.assertEqual(entry.finish_date, parse_datetime("2016-06-29T10:47:00Z"))
        self.assertEqual(entry.finished_level, 3)
        self.assertEqual(entry.queue_position, 0)
        self.assertEqual(entry.start_date, parse_datetime("2016-06-29T10:46:00Z"))

        entry = self.character_1001.skillqueue.get(skill_id=24312)
        self.assertEqual(entry.finish_date, parse_datetime("2016-07-15T10:47:00Z"))
        self.assertEqual(entry.finished_level, 4)
        self.assertEqual(entry.level_end_sp, 1000)
        self.assertEqual(entry.level_start_sp, 100)
        self.assertEqual(entry.queue_position, 1)
        self.assertEqual(entry.start_date, parse_datetime("2016-06-29T10:47:00Z"))
        self.assertEqual(entry.training_start_sp, 50)

    def test_update_skills_1(self, mock_esi):
        """can create new skills"""
        mock_esi.client = esi_client_stub

        self.character_1001.update_skills()
        self.assertEqual(self.character_1001.skillpoints.total, 30_000)
        self.assertEqual(self.character_1001.skillpoints.unallocated, 1_000)

        self.assertSetEqual(
            set(self.character_1001.skills.values_list("eve_type_id", flat=True)),
            {24311, 24312},
        )

        skill = self.character_1001.skills.get(eve_type_id=24311)
        self.assertEqual(skill.active_skill_level, 3)
        self.assertEqual(skill.skillpoints_in_skill, 20_000)
        self.assertEqual(skill.trained_skill_level, 4)

        skill = self.character_1001.skills.get(eve_type_id=24312)
        self.assertEqual(skill.active_skill_level, 1)
        self.assertEqual(skill.skillpoints_in_skill, 10_000)
        self.assertEqual(skill.trained_skill_level, 1)

    def test_update_skills_2(self, mock_esi):
        """can update existing skills"""
        mock_esi.client = esi_client_stub

        CharacterSkill.objects.create(
            character=self.character_1001,
            eve_type=EveType.objects.get(id=24311),
            active_skill_level=1,
            skillpoints_in_skill=1,
            trained_skill_level=1,
        )

        self.character_1001.update_skills()

        self.assertEqual(self.character_1001.skills.count(), 2)
        skill = self.character_1001.skills.get(eve_type_id=24311)
        self.assertEqual(skill.active_skill_level, 3)
        self.assertEqual(skill.skillpoints_in_skill, 20_000)
        self.assertEqual(skill.trained_skill_level, 4)

    def test_update_skills_3(self, mock_esi):
        """can delete obsolete skills"""
        mock_esi.client = esi_client_stub

        CharacterSkill.objects.create(
            character=self.character_1001,
            eve_type=EveType.objects.get(id=20185),
            active_skill_level=1,
            skillpoints_in_skill=1,
            trained_skill_level=1,
        )

        self.character_1001.update_skills()

        self.assertSetEqual(
            set(self.character_1001.skills.values_list("eve_type_id", flat=True)),
            {24311, 24312},
        )

    def test_update_wallet_balance(self, mock_esi):
        mock_esi.client = esi_client_stub

        self.character_1001.update_wallet_balance()
        self.assertEqual(self.character_1001.wallet_balance.total, 123456789)

    def test_update_wallet_journal_1(self, mock_esi):
        """can create wallet journal entry from scratch"""
        mock_esi.client = esi_client_stub

        self.character_1001.update_wallet_journal()

        self.assertSetEqual(
            set(self.character_1001.wallet_journal.values_list("entry_id", flat=True)),
            {89},
        )
        obj = self.character_1001.wallet_journal.get(entry_id=89)
        self.assertEqual(obj.amount, -100_000)
        self.assertEqual(float(obj.balance), 500_000.43)
        self.assertEqual(obj.context_id, 4)
        self.assertEqual(obj.context_id_type, obj.CONTEXT_ID_TYPE_CONTRACT_ID)
        self.assertEqual(obj.date, parse_datetime("2018-02-23T14:31:32Z"))
        self.assertEqual(obj.description, "Contract Deposit")
        self.assertEqual(obj.first_party.id, 2001)
        self.assertEqual(obj.ref_type, "contract_deposit")
        self.assertEqual(obj.second_party.id, 2002)

    def test_update_wallet_journal_2(self, mock_esi):
        """can add entry to existing wallet journal"""
        mock_esi.client = esi_client_stub
        CharacterWalletJournalEntry.objects.create(
            character=self.character_1001,
            entry_id=1,
            amount=1_000_000,
            balance=10_000_000,
            context_id_type=CharacterWalletJournalEntry.CONTEXT_ID_TYPE_UNDEFINED,
            date=now(),
            description="dummy",
            first_party=EveEntity.objects.get(id=1001),
            second_party=EveEntity.objects.get(id=1002),
        )

        self.character_1001.update_wallet_journal()

        self.assertSetEqual(
            set(self.character_1001.wallet_journal.values_list("entry_id", flat=True)),
            {1, 89},
        )

        obj = self.character_1001.wallet_journal.get(entry_id=89)
        self.assertEqual(obj.amount, -100_000)
        self.assertEqual(float(obj.balance), 500_000.43)
        self.assertEqual(obj.context_id, 4)
        self.assertEqual(obj.context_id_type, obj.CONTEXT_ID_TYPE_CONTRACT_ID)
        self.assertEqual(obj.date, parse_datetime("2018-02-23T14:31:32Z"))
        self.assertEqual(obj.description, "Contract Deposit")
        self.assertEqual(obj.first_party.id, 2001)
        self.assertEqual(obj.ref_type, "contract_deposit")
        self.assertEqual(obj.second_party.id, 2002)

    def test_update_wallet_journal_3(self, mock_esi):
        """does not update existing entries"""
        mock_esi.client = esi_client_stub
        CharacterWalletJournalEntry.objects.create(
            character=self.character_1001,
            entry_id=89,
            amount=1_000_000,
            balance=10_000_000,
            context_id_type=CharacterWalletJournalEntry.CONTEXT_ID_TYPE_UNDEFINED,
            date=now(),
            description="dummy",
            first_party=EveEntity.objects.get(id=1001),
            second_party=EveEntity.objects.get(id=1002),
        )

        self.character_1001.update_wallet_journal()

        self.assertSetEqual(
            set(self.character_1001.wallet_journal.values_list("entry_id", flat=True)),
            {89},
        )
        obj = self.character_1001.wallet_journal.get(entry_id=89)
        self.assertEqual(obj.amount, 1_000_000)
        self.assertEqual(float(obj.balance), 10_000_000)
        self.assertEqual(
            obj.context_id_type, CharacterWalletJournalEntry.CONTEXT_ID_TYPE_UNDEFINED
        )
        self.assertEqual(obj.description, "dummy")
        self.assertEqual(obj.first_party.id, 1001)
        self.assertEqual(obj.second_party.id, 1002)

    def test_fetch_location_station(self, mock_esi):
        mock_esi.client = esi_client_stub

        result = self.character_1001.fetch_location()
        self.assertEqual(result[0], self.jita)
        self.assertEqual(result[1], self.jita_44)

    def test_fetch_location_structure(self, mock_esi):
        mock_esi.client = esi_client_stub

        result = self.character_1002.fetch_location()
        self.assertEqual(result[0], self.amamake)
        self.assertEqual(result[1], self.structure_1)


class TestCharacterCanFlyDoctrines(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        load_locations()
        cls.character = create_memberaudit_character(1001)
        cls.skill_1 = EveType.objects.get(id=24311)
        cls.skill_2 = EveType.objects.get(id=24312)

    def test_has_all_skills(self):
        CharacterSkill.objects.create(
            character=self.character,
            eve_type=self.skill_1,
            active_skill_level=5,
            skillpoints_in_skill=10,
            trained_skill_level=5,
        )
        CharacterSkill.objects.create(
            character=self.character,
            eve_type=self.skill_2,
            active_skill_level=5,
            skillpoints_in_skill=10,
            trained_skill_level=5,
        )
        ship = DoctrineShip.objects.create(name="Ship 1")
        DoctrineShipSkill.objects.create(ship=ship, skill=self.skill_1, level=5)
        DoctrineShipSkill.objects.create(ship=ship, skill=self.skill_2, level=3)
        doctrine = Doctrine.objects.create(name="Dummy")
        doctrine.ships.add(ship)

        self.character.update_doctrines()

        self.assertEqual(self.character.doctrine_ships.count(), 1)
        first = self.character.doctrine_ships.first()
        self.assertEqual(first.ship.pk, ship.pk)
        self.assertEqual(first.insufficient_skills.count(), 0)

    def test_one_skill_below(self):
        CharacterSkill.objects.create(
            character=self.character,
            eve_type=self.skill_1,
            active_skill_level=5,
            skillpoints_in_skill=10,
            trained_skill_level=5,
        )
        CharacterSkill.objects.create(
            character=self.character,
            eve_type=self.skill_2,
            active_skill_level=2,
            skillpoints_in_skill=10,
            trained_skill_level=5,
        )
        ship = DoctrineShip.objects.create(name="Ship 1")
        DoctrineShipSkill.objects.create(ship=ship, skill=self.skill_1, level=5)
        skill_2 = DoctrineShipSkill.objects.create(
            ship=ship, skill=self.skill_2, level=3
        )
        doctrine = Doctrine.objects.create(name="Dummy")
        doctrine.ships.add(ship)

        self.character.update_doctrines()

        self.assertEqual(self.character.doctrine_ships.count(), 1)
        first = self.character.doctrine_ships.first()
        self.assertEqual(first.ship.pk, ship.pk)
        self.assertEqual(
            {obj.pk for obj in first.insufficient_skills.all()}, {skill_2.pk}
        )

    def test_misses_one_skill(self):
        CharacterSkill.objects.create(
            character=self.character,
            eve_type=self.skill_1,
            active_skill_level=5,
            skillpoints_in_skill=10,
            trained_skill_level=5,
        )
        ship = DoctrineShip.objects.create(name="Ship 1")
        DoctrineShipSkill.objects.create(ship=ship, skill=self.skill_1, level=5)
        skill_2 = DoctrineShipSkill.objects.create(
            ship=ship, skill=self.skill_2, level=3
        )
        doctrine = Doctrine.objects.create(name="Dummy")
        doctrine.ships.add(ship)

        self.character.update_doctrines()

        self.assertEqual(self.character.doctrine_ships.count(), 1)
        first = self.character.doctrine_ships.first()
        self.assertEqual(first.ship.pk, ship.pk)
        self.assertEqual(
            {obj.pk for obj in first.insufficient_skills.all()}, {skill_2.pk}
        )

    def test_misses_all_skills(self):
        ship = DoctrineShip.objects.create(name="Ship 1")
        skill_1 = DoctrineShipSkill.objects.create(
            ship=ship, skill=self.skill_1, level=5
        )
        skill_2 = DoctrineShipSkill.objects.create(
            ship=ship, skill=self.skill_2, level=3
        )
        doctrine = Doctrine.objects.create(name="Dummy")
        doctrine.ships.add(ship)

        self.character.update_doctrines()

        self.assertEqual(self.character.doctrine_ships.count(), 1)
        first = self.character.doctrine_ships.first()
        self.assertEqual(first.ship.pk, ship.pk)
        self.assertEqual(
            {obj.pk for obj in first.insufficient_skills.all()},
            {skill_1.pk, skill_2.pk},
        )

    def test_does_not_require_doctrine_definition(self):
        ship = DoctrineShip.objects.create(name="Ship 1")
        skill_1 = DoctrineShipSkill.objects.create(
            ship=ship, skill=self.skill_1, level=5
        )
        skill_2 = DoctrineShipSkill.objects.create(
            ship=ship, skill=self.skill_2, level=3
        )

        self.character.update_doctrines()

        self.assertEqual(self.character.doctrine_ships.count(), 1)
        first = self.character.doctrine_ships.first()
        self.assertEqual(first.ship.pk, ship.pk)
        self.assertEqual(
            {obj.pk for obj in first.insufficient_skills.all()},
            {skill_1.pk, skill_2.pk},
        )


class TestCharacterContract(NoSocketsTestCase):
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

    def setUp(self) -> None:
        self.contract = CharacterContract.objects.create(
            character=self.character_1001,
            contract_id=42,
            availability=CharacterContract.AVAILABILITY_PERSONAL,
            contract_type=CharacterContract.TYPE_ITEM_EXCHANGE,
            date_issued=now(),
            date_expired=now() + dt.timedelta(days=3),
            for_corporation=False,
            issuer=EveEntity.objects.get(id=1001),
            issuer_corporation=EveEntity.objects.get(id=2001),
            status=CharacterContract.STATUS_OUTSTANDING,
            start_location=self.jita_44,
            end_location=self.jita_44,
        )

    def test_summary_one_item_1(self):
        CharacterContractItem.objects.create(
            contract=self.contract,
            record_id=1,
            is_included=True,
            is_singleton=False,
            quantity=1,
            eve_type=EveType.objects.get(id=19540),
        )
        self.assertEqual(self.contract.summary(), "High-grade Snake Alpha")

    def test_summary_one_item_2(self):
        CharacterContractItem.objects.create(
            contract=self.contract,
            record_id=1,
            is_included=True,
            is_singleton=False,
            quantity=1,
            eve_type=EveType.objects.get(id=19540),
        )
        CharacterContractItem.objects.create(
            contract=self.contract,
            record_id=2,
            is_included=False,
            is_singleton=False,
            quantity=1,
            eve_type=EveType.objects.get(id=19551),
        )
        self.assertEqual(self.contract.summary(), "High-grade Snake Alpha")

    def test_summary_multiple_item(self):
        CharacterContractItem.objects.create(
            contract=self.contract,
            record_id=1,
            is_included=True,
            is_singleton=False,
            quantity=1,
            eve_type=EveType.objects.get(id=19540),
        ),
        CharacterContractItem.objects.create(
            contract=self.contract,
            record_id=2,
            is_included=True,
            is_singleton=False,
            quantity=1,
            eve_type=EveType.objects.get(id=19551),
        )
        self.assertEqual(self.contract.summary(), "[Multiple Items]")

    def test_summary_no_items(self):
        self.assertEqual(self.contract.summary(), "(no items)")


class TestCharacterSkillQueue(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        load_locations()
        cls.character_1001 = create_memberaudit_character(1001)
        cls.skill_1 = EveType.objects.get(id=24311)
        cls.skill_2 = EveType.objects.get(id=24312)

    def test_is_active_1(self):
        """when training is active and skill is in first position then return True"""
        entry = CharacterSkillqueueEntry.objects.create(
            character=self.character_1001,
            skill=self.skill_1,
            finish_date=now() + dt.timedelta(days=3),
            finished_level=5,
            queue_position=0,
            start_date=now() - dt.timedelta(days=1),
        )
        self.assertTrue(entry.is_active)

    def test_is_active_2(self):
        """when training is active and skill is not in first position then return False"""
        entry = CharacterSkillqueueEntry.objects.create(
            character=self.character_1001,
            skill=self.skill_1,
            finish_date=now() + dt.timedelta(days=3),
            finished_level=5,
            queue_position=1,
            start_date=now() - dt.timedelta(days=1),
        )
        self.assertFalse(entry.is_active)

    def test_is_active_3(self):
        """when training is not active and skill is in first position then return False"""
        entry = CharacterSkillqueueEntry.objects.create(
            character=self.character_1001,
            skill=self.skill_1,
            finished_level=5,
            queue_position=0,
        )
        self.assertFalse(entry.is_active)


class TestLocation(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        load_locations()

    def test_is_solar_system(self):
        location = Location.objects.create(
            id=30000142, eve_solar_system=EveSolarSystem.objects.get(id=30000142)
        )
        self.assertTrue(location.is_solar_system)
        self.assertFalse(location.is_station)
        self.assertFalse(location.is_structure)

    def test_is_station(self):
        location = Location.objects.get(id=60003760)
        self.assertFalse(location.is_solar_system)
        self.assertTrue(location.is_station)
        self.assertFalse(location.is_structure)

    def test_is_structure(self):
        location = Location.objects.get(id=1000000000001)
        self.assertFalse(location.is_solar_system)
        self.assertFalse(location.is_station)
        self.assertTrue(location.is_structure)


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
        self.assertEqual(obj.name, "Amamake - Test Structure Alpha")
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
        self.assertEqual(obj.name, "Amamake - Test Structure Alpha")
        self.assertEqual(obj.eve_solar_system, self.amamake)
        self.assertEqual(obj.eve_type, self.astrahus)
        self.assertEqual(obj.owner, self.corporation_2001)

    def test_does_not_update_existing_location_during_grace_period(self, mock_esi):
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
            Location.objects.update_or_create_esi(id=1000000000099, token=self.token)

    def test_always_creates_empty_location_for_invalid_ids(self, mock_esi):
        mock_esi.client = esi_client_stub

        obj, created = Location.objects.update_or_create_esi(
            id=80000000, token=self.token
        )
        self.assertTrue(created)
        self.assertTrue(obj.is_empty)

    def test_propagates_exceptions_on_structure_create(self, mock_esi):
        mock_esi.client.Universe.get_universe_structures_structure_id.side_effect = (
            RuntimeError
        )

        with self.assertRaises(RuntimeError):
            Location.objects.update_or_create_esi(id=1000000000099, token=self.token)

    def test_can_create_empty_location_on_access_error_1(self, mock_esi):
        mock_esi.client.Universe.get_universe_structures_structure_id.side_effect = (
            HTTPForbidden(Mock())
        )

        obj, created = Location.objects.update_or_create_esi(
            id=1000000000099, token=self.token
        )
        self.assertTrue(created)
        self.assertEqual(obj.id, 1000000000099)

    def test_can_create_empty_location_on_access_error_2(self, mock_esi):
        mock_esi.client.Universe.get_universe_structures_structure_id.side_effect = (
            HTTPUnauthorized(Mock())
        )

        obj, created = Location.objects.update_or_create_esi(
            id=1000000000099, token=self.token
        )
        self.assertTrue(created)
        self.assertEqual(obj.id, 1000000000099)

    def test_does_not_creates_empty_location_on_access_errors_if_requested(
        self, mock_esi
    ):
        mock_esi.client.Universe.get_universe_structures_structure_id.side_effect = (
            RuntimeError
        )
        with self.assertRaises(RuntimeError):
            Location.objects.update_or_create_esi(id=1000000000099, token=self.token)

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
            Location.objects.update_or_create_esi(id=1000000000099, token=self.token)

    # Solar System

    def test_can_create_solar_system(self, mock_esi):
        mock_esi.client = esi_client_stub

        obj, created = Location.objects.update_or_create_esi(
            id=30002537, token=self.token
        )
        self.assertTrue(created)
        self.assertEqual(obj.id, 30002537)
        self.assertEqual(obj.name, "Amamake")
        self.assertEqual(obj.eve_solar_system, self.amamake)
        self.assertEqual(obj.eve_type, EveType.objects.get(id=5))
        self.assertIsNone(obj.owner)


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
        self.assertEqual(obj.name, "Amamake - Test Structure Alpha")
        self.assertEqual(obj.eve_solar_system, self.amamake)
        self.assertEqual(obj.eve_type, self.astrahus)
        self.assertEqual(obj.owner, self.corporation_2001)


class TestCharacterWalletJournalEntry(NoSocketsTestCase):
    def test_match_context_type_id(self):
        self.assertEqual(
            CharacterWalletJournalEntry.match_context_type_id("character_id"),
            CharacterWalletJournalEntry.CONTEXT_ID_TYPE_CHARACTER_ID,
        )
        self.assertEqual(
            CharacterWalletJournalEntry.match_context_type_id("contract_id"),
            CharacterWalletJournalEntry.CONTEXT_ID_TYPE_CONTRACT_ID,
        )
        self.assertEqual(
            CharacterWalletJournalEntry.match_context_type_id(None),
            CharacterWalletJournalEntry.CONTEXT_ID_TYPE_UNDEFINED,
        )
