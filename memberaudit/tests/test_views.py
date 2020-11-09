import datetime as dt
import json
from unittest.mock import patch

from bravado.exception import HTTPNotFound
import pytz

from django.http import JsonResponse
from django.test import TestCase, RequestFactory
from django.utils.timezone import now
from django.urls import reverse

from eveuniverse.models import EveSolarSystem, EveType, EveEntity, EveMarketPrice

from allianceauth.eveonline.models import EveAllianceInfo
from allianceauth.tests.auth_utils import AuthUtils

from .testdata.load_eveuniverse import load_eveuniverse
from .testdata.load_entities import load_entities
from .testdata.load_locations import load_locations

from . import create_memberaudit_character, add_memberaudit_character_to_user
from ..models import (
    Character,
    CharacterAsset,
    CharacterContact,
    CharacterContract,
    CharacterContractItem,
    CharacterCorporationHistory,
    CharacterImplant,
    CharacterJumpClone,
    CharacterJumpCloneImplant,
    CharacterLoyaltyEntry,
    CharacterMail,
    CharacterMailRecipient,
    CharacterMailingList,
    CharacterMailLabel,
    CharacterSkill,
    CharacterSkillqueueEntry,
    CharacterWalletJournalEntry,
    Doctrine,
    DoctrineShip,
    DoctrineShipSkill,
    Location,
)
from .utils import ResponseStub
from ..utils import generate_invalid_pk
from ..views import (
    index,
    launcher,
    character_viewer,
    character_location_data,
    character_assets_data,
    character_asset_container,
    character_asset_container_data,
    character_contacts_data,
    character_contracts_data,
    character_contract_details,
    character_contract_items_included_data,
    character_contract_items_requested_data,
    character_corporation_history,
    character_doctrines_data,
    character_implants_data,
    character_jump_clones_data,
    character_loyalty_data,
    character_mail_headers_by_label_data,
    character_mail_headers_by_list_data,
    character_mail_data,
    character_skills_data,
    character_skillqueue_data,
    character_wallet_journal_data,
    character_finder_data,
    compliance_report_data,
    doctrines_report_data,
    remove_character,
    share_character,
    unshare_character,
)

MODULE_PATH = "memberaudit.views"


def response_content_to_str(content) -> str:
    return content.decode("utf-8")


def json_response_to_python(response: JsonResponse) -> object:
    return json.loads(response_content_to_str(response.content))


def json_response_to_python_dict(response: JsonResponse) -> dict:
    return {x["id"]: x for x in json_response_to_python(response)}


def multi_assert_in(items, container) -> bool:
    for item in items:
        if item not in container:
            return False

    return True


def multi_assert_not_in(items, container) -> bool:
    for item in items:
        if item in container:
            return False

    return True


class TestViewsBase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.factory = RequestFactory()
        load_eveuniverse()
        load_entities()
        load_locations()
        cls.character = create_memberaudit_character(1001)
        cls.user = cls.character.character_ownership.user
        cls.jita = EveSolarSystem.objects.get(id=30000142)
        cls.jita_trade_hub = EveType.objects.get(id=52678)
        cls.corporation_2001 = EveEntity.objects.get(id=2001)
        cls.jita_44 = Location.objects.get(id=60003760)
        cls.structure_1 = Location.objects.get(id=1000000000001)
        cls.skill_type_1 = EveType.objects.get(id=24311)
        cls.skill_type_2 = EveType.objects.get(id=24312)


class TestCharacterAssets(TestViewsBase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()

    def test_character_assets_data_1(self):
        CharacterAsset.objects.create(
            character=self.character,
            item_id=1,
            location=self.jita_44,
            eve_type=EveType.objects.get(id=20185),
            is_singleton=False,
            name="Trucker",
            quantity=1,
        )
        request = self.factory.get(
            reverse("memberaudit:character_assets_data", args=[self.character.pk])
        )
        request.user = self.user
        response = character_assets_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["item_id"], 1)
        self.assertEqual(
            row["location"], "Jita IV - Moon 4 - Caldari Navy Assembly Plant (1)"
        )
        self.assertEqual(row["name"]["sort"], "Trucker")
        self.assertEqual(row["quantity"], 1)
        self.assertEqual(row["group"], "Charon")
        self.assertEqual(row["volume"], 16250000.0)
        self.assertEqual(row["solar_system"], "Jita")
        self.assertEqual(row["region"], "The Forge")

    def test_character_assets_data_2(self):
        CharacterAsset.objects.create(
            character=self.character,
            item_id=1,
            location=self.jita_44,
            eve_type=EveType.objects.get(id=20185),
            is_singleton=False,
            name="",
            quantity=1,
        )
        request = self.factory.get(
            reverse("memberaudit:character_assets_data", args=[self.character.pk])
        )
        request.user = self.user
        response = character_assets_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["item_id"], 1)
        self.assertEqual(
            row["location"], "Jita IV - Moon 4 - Caldari Navy Assembly Plant (1)"
        )
        self.assertEqual(row["name"]["sort"], "Charon")
        self.assertEqual(row["quantity"], 1)
        self.assertEqual(row["group"], "Freighter")
        self.assertEqual(row["volume"], 16250000.0)

    def test_character_asset_children_normal(self):
        parent_asset = CharacterAsset.objects.create(
            character=self.character,
            item_id=1,
            location=self.jita_44,
            eve_type=EveType.objects.get(id=20185),
            is_singleton=True,
            name="Trucker",
            quantity=1,
        )
        CharacterAsset.objects.create(
            character=self.character,
            item_id=2,
            parent=parent_asset,
            eve_type=EveType.objects.get(id=603),
            is_singleton=True,
            name="My Precious",
            quantity=1,
        )
        request = self.factory.get(
            reverse(
                "memberaudit:character_asset_container",
                args=[self.character.pk, parent_asset.pk],
            )
        )
        request.user = self.user
        response = character_asset_container(
            request, self.character.pk, parent_asset.pk
        )
        self.assertEqual(response.status_code, 200)

    def test_character_asset_children_error(self):
        parent_asset_pk = generate_invalid_pk(CharacterAsset)
        request = self.factory.get(
            reverse(
                "memberaudit:character_asset_container",
                args=[self.character.pk, parent_asset_pk],
            )
        )
        request.user = self.user
        response = character_asset_container(
            request, self.character.pk, parent_asset_pk
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "not found for character", response_content_to_str(response.content)
        )

    def test_character_asset_children_data(self):
        parent_asset = CharacterAsset.objects.create(
            character=self.character,
            item_id=1,
            location=self.jita_44,
            eve_type=EveType.objects.get(id=20185),
            is_singleton=True,
            name="Trucker",
            quantity=1,
        )
        CharacterAsset.objects.create(
            character=self.character,
            item_id=2,
            parent=parent_asset,
            eve_type=EveType.objects.get(id=603),
            is_singleton=True,
            name="My Precious",
            quantity=1,
        )
        CharacterAsset.objects.create(
            character=self.character,
            item_id=3,
            parent=parent_asset,
            eve_type=EveType.objects.get(id=19540),
            is_singleton=False,
            quantity=3,
        )
        request = self.factory.get(
            reverse(
                "memberaudit:character_asset_container_data",
                args=[self.character.pk, parent_asset.pk],
            )
        )
        request.user = self.user
        response = character_asset_container_data(
            request, self.character.pk, parent_asset.pk
        )
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 2)

        row = data[0]
        self.assertEqual(row["item_id"], 2)
        self.assertEqual(row["name"]["sort"], "My Precious")
        self.assertEqual(row["quantity"], "")
        self.assertEqual(row["group"], "Merlin")
        self.assertEqual(row["volume"], 16500.0)

        row = data[1]
        self.assertEqual(row["item_id"], 3)
        self.assertEqual(row["name"]["sort"], "High-grade Snake Alpha")
        self.assertEqual(row["quantity"], 3)
        self.assertEqual(row["group"], "Cyberimplant")
        self.assertEqual(row["volume"], 1.0)


class TestCharacterContracts(TestViewsBase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.item_type_1 = EveType.objects.get(id=19540)
        cls.item_type_2 = EveType.objects.get(id=19551)

    @patch(MODULE_PATH + ".now")
    def test_character_contracts_data_1(self, mock_now):
        """items exchange single item"""
        date_issued = dt.datetime(2020, 10, 8, 16, 45, tzinfo=pytz.utc)
        date_now = date_issued + dt.timedelta(days=1)
        date_expired = date_now + dt.timedelta(days=2, hours=3)
        mock_now.return_value = date_now
        contract = CharacterContract.objects.create(
            character=self.character,
            contract_id=42,
            availability=CharacterContract.AVAILABILITY_PERSONAL,
            contract_type=CharacterContract.TYPE_ITEM_EXCHANGE,
            assignee=EveEntity.objects.get(id=1002),
            date_issued=date_issued,
            date_expired=date_expired,
            for_corporation=False,
            issuer=EveEntity.objects.get(id=1001),
            issuer_corporation=EveEntity.objects.get(id=2001),
            status=CharacterContract.STATUS_IN_PROGRESS,
            start_location=self.jita_44,
            end_location=self.jita_44,
            title="Dummy info",
        )
        CharacterContractItem.objects.create(
            contract=contract,
            record_id=1,
            is_included=True,
            is_singleton=False,
            quantity=1,
            eve_type=self.item_type_1,
        )

        # main view
        request = self.factory.get(
            reverse("memberaudit:character_contracts_data", args=[self.character.pk])
        )
        request.user = self.user
        response = character_contracts_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["contract_id"], 42)
        self.assertEqual(row["summary"], "High-grade Snake Alpha")
        self.assertEqual(row["type"], "Item Exchange")
        self.assertEqual(row["from"], "Bruce Wayne")
        self.assertEqual(row["to"], "Clark Kent")
        self.assertEqual(row["status"], "in progress")
        self.assertEqual(row["date_issued"], date_issued.isoformat())
        self.assertEqual(row["time_left"], "2\xa0days, 3\xa0hours")
        self.assertEqual(row["info"], "Dummy info")

        # details view
        request = self.factory.get(
            reverse(
                "memberaudit:character_contract_details",
                args=[self.character.pk, contract.pk],
            )
        )
        request.user = self.user
        response = character_contract_details(request, self.character.pk, contract.pk)
        self.assertEqual(response.status_code, 200)

    @patch(MODULE_PATH + ".now")
    def test_character_contracts_data_2(self, mock_now):
        """items exchange multiple item"""
        date_issued = dt.datetime(2020, 10, 8, 16, 45, tzinfo=pytz.utc)
        date_now = date_issued + dt.timedelta(days=1)
        date_expired = date_now + dt.timedelta(days=2, hours=3)
        mock_now.return_value = date_now
        contract = CharacterContract.objects.create(
            character=self.character,
            availability=CharacterContract.AVAILABILITY_PUBLIC,
            contract_id=42,
            contract_type=CharacterContract.TYPE_ITEM_EXCHANGE,
            assignee=EveEntity.objects.get(id=1002),
            date_issued=date_issued,
            date_expired=date_expired,
            for_corporation=False,
            issuer=EveEntity.objects.get(id=1001),
            issuer_corporation=EveEntity.objects.get(id=2001),
            status=CharacterContract.STATUS_IN_PROGRESS,
            title="Dummy info",
            start_location=self.jita_44,
            end_location=self.jita_44,
        )
        CharacterContractItem.objects.create(
            contract=contract,
            record_id=1,
            is_included=True,
            is_singleton=False,
            quantity=1,
            eve_type=self.item_type_1,
        )
        CharacterContractItem.objects.create(
            contract=contract,
            record_id=2,
            is_included=True,
            is_singleton=False,
            quantity=1,
            eve_type=self.item_type_2,
        )
        request = self.factory.get(
            reverse("memberaudit:character_contracts_data", args=[self.character.pk])
        )

        # main view
        request.user = self.user
        response = character_contracts_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["contract_id"], 42)
        self.assertEqual(row["summary"], "[Multiple Items]")
        self.assertEqual(row["type"], "Item Exchange")

        # details view
        request = self.factory.get(
            reverse(
                "memberaudit:character_contract_details",
                args=[self.character.pk, contract.pk],
            )
        )
        request.user = self.user
        response = character_contract_details(request, self.character.pk, contract.pk)
        self.assertEqual(response.status_code, 200)

    @patch(MODULE_PATH + ".now")
    def test_character_contracts_data_3(self, mock_now):
        """courier contract"""
        date_issued = dt.datetime(2020, 10, 8, 16, 45, tzinfo=pytz.utc)
        date_now = date_issued + dt.timedelta(days=1)
        date_expired = date_now + dt.timedelta(days=2, hours=3)
        mock_now.return_value = date_now
        contract = CharacterContract.objects.create(
            character=self.character,
            contract_id=42,
            availability=CharacterContract.AVAILABILITY_PERSONAL,
            contract_type=CharacterContract.TYPE_COURIER,
            assignee=EveEntity.objects.get(id=1002),
            date_issued=date_issued,
            date_expired=date_expired,
            for_corporation=False,
            issuer=EveEntity.objects.get(id=1001),
            issuer_corporation=EveEntity.objects.get(id=2001),
            status=CharacterContract.STATUS_IN_PROGRESS,
            title="Dummy info",
            start_location=self.jita_44,
            end_location=self.structure_1,
            volume=10,
            days_to_complete=3,
            reward=10000000,
            collateral=500000000,
        )

        # main view
        request = self.factory.get(
            reverse("memberaudit:character_contracts_data", args=[self.character.pk])
        )
        request.user = self.user
        response = character_contracts_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["contract_id"], 42)
        self.assertEqual(row["summary"], "Jita >> Amamake (10 m3)")
        self.assertEqual(row["type"], "Courier")

        # details view
        request = self.factory.get(
            reverse(
                "memberaudit:character_contract_details",
                args=[self.character.pk, contract.pk],
            )
        )
        request.user = self.user
        response = character_contract_details(request, self.character.pk, contract.pk)
        self.assertEqual(response.status_code, 200)

    def test_character_contract_details_error(self):
        contract_pk = generate_invalid_pk(CharacterContract)
        request = self.factory.get(
            reverse(
                "memberaudit:character_contract_details",
                args=[self.character.pk, contract_pk],
            )
        )
        request.user = self.user
        response = character_contract_details(request, self.character.pk, contract_pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "not found for character", response_content_to_str(response.content)
        )

    @patch(MODULE_PATH + ".now")
    def test_items_included_data_normal(self, mock_now):
        """items exchange single item"""
        date_issued = dt.datetime(2020, 10, 8, 16, 45, tzinfo=pytz.utc)
        date_now = date_issued + dt.timedelta(days=1)
        date_expired = date_now + dt.timedelta(days=2, hours=3)
        mock_now.return_value = date_now
        contract = CharacterContract.objects.create(
            character=self.character,
            contract_id=42,
            availability=CharacterContract.AVAILABILITY_PERSONAL,
            contract_type=CharacterContract.TYPE_ITEM_EXCHANGE,
            assignee=EveEntity.objects.get(id=1002),
            date_issued=date_issued,
            date_expired=date_expired,
            for_corporation=False,
            issuer=EveEntity.objects.get(id=1001),
            issuer_corporation=EveEntity.objects.get(id=2001),
            status=CharacterContract.STATUS_IN_PROGRESS,
            start_location=self.jita_44,
            end_location=self.jita_44,
            title="Dummy info",
        )
        CharacterContractItem.objects.create(
            contract=contract,
            record_id=1,
            is_included=True,
            is_singleton=False,
            quantity=3,
            eve_type=self.item_type_1,
        )
        CharacterContractItem.objects.create(
            contract=contract,
            record_id=2,
            is_included=False,
            is_singleton=False,
            quantity=3,
            eve_type=self.item_type_2,
        )
        EveMarketPrice.objects.create(eve_type=self.item_type_1, average_price=5000000)
        request = self.factory.get(
            reverse(
                "memberaudit:character_contract_items_included_data",
                args=[self.character.pk, contract.pk],
            )
        )
        request.user = self.user
        response = character_contract_items_included_data(
            request, self.character.pk, contract.pk
        )
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python_dict(response)

        self.assertSetEqual(set(data.keys()), {1})
        obj = data[1]
        self.assertEqual(obj["name"]["sort"], "High-grade Snake Alpha")
        self.assertEqual(obj["quantity"], 3)
        self.assertEqual(obj["group"], "Cyberimplant")
        self.assertEqual(obj["category"], "Implant")
        self.assertEqual(obj["price"], 5000000)
        self.assertEqual(obj["total"], 15000000)
        self.assertFalse(obj["is_bpo"])

    @patch(MODULE_PATH + ".now")
    def test_items_included_data_bpo(self, mock_now):
        """items exchange single item, which is an BPO"""
        date_issued = dt.datetime(2020, 10, 8, 16, 45, tzinfo=pytz.utc)
        date_now = date_issued + dt.timedelta(days=1)
        date_expired = date_now + dt.timedelta(days=2, hours=3)
        mock_now.return_value = date_now
        contract = CharacterContract.objects.create(
            character=self.character,
            contract_id=42,
            availability=CharacterContract.AVAILABILITY_PERSONAL,
            contract_type=CharacterContract.TYPE_ITEM_EXCHANGE,
            assignee=EveEntity.objects.get(id=1002),
            date_issued=date_issued,
            date_expired=date_expired,
            for_corporation=False,
            issuer=EveEntity.objects.get(id=1001),
            issuer_corporation=EveEntity.objects.get(id=2001),
            status=CharacterContract.STATUS_IN_PROGRESS,
            start_location=self.jita_44,
            end_location=self.jita_44,
            title="Dummy info",
        )
        CharacterContractItem.objects.create(
            contract=contract,
            record_id=1,
            is_included=True,
            is_singleton=True,
            quantity=1,
            raw_quantity=-2,
            eve_type=self.item_type_1,
        )
        CharacterContractItem.objects.create(
            contract=contract,
            record_id=2,
            is_included=True,
            is_singleton=False,
            quantity=3,
            eve_type=self.item_type_2,
        )
        EveMarketPrice.objects.create(eve_type=self.item_type_1, average_price=5000000)
        request = self.factory.get(
            reverse(
                "memberaudit:character_contract_items_included_data",
                args=[self.character.pk, contract.pk],
            )
        )
        request.user = self.user
        response = character_contract_items_included_data(
            request, self.character.pk, contract.pk
        )
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python_dict(response)

        self.assertSetEqual(set(data.keys()), {1, 2})
        obj = data[1]
        self.assertEqual(obj["name"]["sort"], "High-grade Snake Alpha [BPC]")
        self.assertEqual(obj["quantity"], "")
        self.assertEqual(obj["group"], "Cyberimplant")
        self.assertEqual(obj["category"], "Implant")
        self.assertIsNone(obj["price"])
        self.assertIsNone(obj["total"])
        self.assertTrue(obj["is_bpo"])

    @patch(MODULE_PATH + ".now")
    def test_items_requested_data_normal(self, mock_now):
        """items exchange single item"""
        date_issued = dt.datetime(2020, 10, 8, 16, 45, tzinfo=pytz.utc)
        date_now = date_issued + dt.timedelta(days=1)
        date_expired = date_now + dt.timedelta(days=2, hours=3)
        mock_now.return_value = date_now
        contract = CharacterContract.objects.create(
            character=self.character,
            contract_id=42,
            availability=CharacterContract.AVAILABILITY_PERSONAL,
            contract_type=CharacterContract.TYPE_ITEM_EXCHANGE,
            assignee=EveEntity.objects.get(id=1002),
            date_issued=date_issued,
            date_expired=date_expired,
            for_corporation=False,
            issuer=EveEntity.objects.get(id=1001),
            issuer_corporation=EveEntity.objects.get(id=2001),
            status=CharacterContract.STATUS_IN_PROGRESS,
            start_location=self.jita_44,
            end_location=self.jita_44,
            title="Dummy info",
        )
        CharacterContractItem.objects.create(
            contract=contract,
            record_id=1,
            is_included=False,
            is_singleton=False,
            quantity=3,
            eve_type=self.item_type_1,
        )
        CharacterContractItem.objects.create(
            contract=contract,
            record_id=2,
            is_included=True,
            is_singleton=False,
            quantity=3,
            eve_type=self.item_type_2,
        )
        EveMarketPrice.objects.create(eve_type=self.item_type_1, average_price=5000000)
        request = self.factory.get(
            reverse(
                "memberaudit:character_contract_items_requested_data",
                args=[self.character.pk, contract.pk],
            )
        )
        request.user = self.user
        response = character_contract_items_requested_data(
            request, self.character.pk, contract.pk
        )
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python_dict(response)

        self.assertSetEqual(set(data.keys()), {1})
        obj = data[1]
        self.assertEqual(obj["name"]["sort"], "High-grade Snake Alpha")
        self.assertEqual(obj["quantity"], 3)
        self.assertEqual(obj["group"], "Cyberimplant")
        self.assertEqual(obj["category"], "Implant")
        self.assertEqual(obj["price"], 5000000)
        self.assertEqual(obj["total"], 15000000)
        self.assertFalse(obj["is_bpo"])


class TestViewsOther(TestViewsBase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()

    def test_can_open_index_view(self):
        request = self.factory.get(reverse("memberaudit:index"))
        request.user = self.user
        response = index(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("memberaudit:launcher"))

    def test_can_open_launcher_view_1(self):
        """user with main"""
        request = self.factory.get(reverse("memberaudit:launcher"))
        request.user = self.user
        response = launcher(request)
        self.assertEqual(response.status_code, 200)

    def test_can_open_launcher_view_2(self):
        """user without main"""
        user = AuthUtils.create_user("John Doe")
        user = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.basic_access", user
        )

        request = self.factory.get(reverse("memberaudit:launcher"))
        request.user = user
        response = launcher(request)
        self.assertEqual(response.status_code, 200)

    def test_can_open_character_main_view(self):
        request = self.factory.get(
            reverse("memberaudit:character_viewer", args=[self.character.pk])
        )
        request.user = self.user
        response = character_viewer(request, self.character.pk)
        self.assertEqual(response.status_code, 200)

    def test_character_contacts_data(self):
        CharacterContact.objects.create(
            character=self.character,
            eve_entity=EveEntity.objects.get(id=1101),
            standing=-10,
            is_blocked=True,
        )
        CharacterContact.objects.create(
            character=self.character,
            eve_entity=EveEntity.objects.get(id=2001),
            standing=10,
        )

        request = self.factory.get(
            reverse("memberaudit:character_contacts_data", args=[self.character.pk])
        )
        request.user = self.user
        response = character_contacts_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python_dict(response)

        self.assertEqual(len(data), 2)

        row = data[1101]
        self.assertEqual(row["name"]["sort"], "Lex Luther")
        self.assertEqual(row["standing"], -10)
        self.assertEqual(row["type"], "Character")
        self.assertEqual(row["is_watched"], False)
        self.assertEqual(row["is_blocked"], True)
        self.assertEqual(row["level"], "Terrible Standing")

        row = data[2001]
        self.assertEqual(row["name"]["sort"], "Wayne Technologies")
        self.assertEqual(row["standing"], 10)
        self.assertEqual(row["type"], "Corporation")
        self.assertEqual(row["is_watched"], False)
        self.assertEqual(row["is_blocked"], False)
        self.assertEqual(row["level"], "Excellent Standing")

    def test_doctrines_data(self):
        CharacterSkill.objects.create(
            character=self.character,
            eve_type=self.skill_type_1,
            active_skill_level=5,
            skillpoints_in_skill=10,
            trained_skill_level=5,
        )
        CharacterSkill.objects.create(
            character=self.character,
            eve_type=self.skill_type_2,
            active_skill_level=2,
            skillpoints_in_skill=10,
            trained_skill_level=5,
        )

        doctrine_1 = Doctrine.objects.create(name="Alpha")
        doctrine_2 = Doctrine.objects.create(name="Bravo")

        # can fly ship 1
        ship_1 = DoctrineShip.objects.create(name="Ship 1")
        DoctrineShipSkill.objects.create(
            ship=ship_1, eve_type=self.skill_type_1, level=3
        )
        doctrine_1.ships.add(ship_1)
        doctrine_2.ships.add(ship_1)

        # can not fly ship 2
        ship_2 = DoctrineShip.objects.create(name="Ship 2")
        DoctrineShipSkill.objects.create(
            ship=ship_2, eve_type=self.skill_type_1, level=5
        )
        DoctrineShipSkill.objects.create(
            ship=ship_2, eve_type=self.skill_type_2, level=3
        )
        doctrine_1.ships.add(ship_2)

        # can fly ship 3 (No Doctrine)
        ship_3 = DoctrineShip.objects.create(name="Ship 3")
        DoctrineShipSkill.objects.create(
            ship=ship_3, eve_type=self.skill_type_1, level=1
        )

        self.character.update_doctrines()

        request = self.factory.get(
            reverse("memberaudit:character_doctrines_data", args=[self.character.pk])
        )
        request.user = self.user
        response = character_doctrines_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 4)

        row = data[0]
        self.assertEqual(row["doctrine"], "(No Doctrine)")
        self.assertEqual(row["ship_name"], "Ship 3")
        self.assertTrue(row["can_fly"])
        self.assertEqual(row["insufficient_skills"], "-")

        row = data[1]
        self.assertEqual(row["doctrine"], "Alpha")
        self.assertEqual(row["ship_name"], "Ship 1")
        self.assertTrue(row["can_fly"])
        self.assertEqual(row["insufficient_skills"], "-")

        row = data[2]
        self.assertEqual(row["doctrine"], "Alpha")
        self.assertEqual(row["ship_name"], "Ship 2")
        self.assertFalse(row["can_fly"])
        self.assertEqual(row["insufficient_skills"], "Caldari Carrier&nbsp;III")

        row = data[3]
        self.assertEqual(row["doctrine"], "Bravo")
        self.assertEqual(row["ship_name"], "Ship 1")
        self.assertTrue(row["can_fly"])
        self.assertEqual(row["insufficient_skills"], "-")

    def test_character_jump_clones_data(self):
        clone_1 = jump_clone = CharacterJumpClone.objects.create(
            character=self.character, location=self.jita_44, jump_clone_id=1
        )
        CharacterJumpCloneImplant.objects.create(
            jump_clone=jump_clone, eve_type=EveType.objects.get(id=19540)
        )
        CharacterJumpCloneImplant.objects.create(
            jump_clone=jump_clone, eve_type=EveType.objects.get(id=19551)
        )

        location_2 = Location.objects.create(id=123457890)
        clone_2 = jump_clone = CharacterJumpClone.objects.create(
            character=self.character, location=location_2, jump_clone_id=2
        )
        request = self.factory.get(
            reverse("memberaudit:character_jump_clones_data", args=[self.character.pk])
        )
        request.user = self.user
        response = character_jump_clones_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python_dict(response)
        self.assertEqual(len(data), 2)

        row = data[clone_1.pk]
        self.assertEqual(row["region"], "The Forge")
        self.assertIn("Jita", row["solar_system"])
        self.assertEqual(
            row["location"], "Jita IV - Moon 4 - Caldari Navy Assembly Plant"
        )
        self.assertTrue(
            multi_assert_in(
                ["High-grade Snake Alpha", "High-grade Snake Beta"], row["implants"]
            )
        )

        row = data[clone_2.pk]
        self.assertEqual(row["region"], "-")
        self.assertEqual(row["solar_system"], "-")
        self.assertEqual(row["location"], "Unknown location #123457890")
        self.assertEqual(row["implants"], "(none)")

    def test_character_loyalty_data(self):
        CharacterLoyaltyEntry.objects.create(
            character=self.character,
            corporation=EveEntity.objects.get(id=2101),
            loyalty_points=99,
        )
        request = self.factory.get(
            reverse("memberaudit:character_loyalty_data", args=[self.character.pk])
        )
        request.user = self.user
        response = character_loyalty_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["corporation"]["sort"], "Lexcorp")
        self.assertEqual(row["loyalty_points"], 99)

    def test_character_skills_data(self):
        CharacterSkill.objects.create(
            character=self.character,
            eve_type=self.skill_type_1,
            active_skill_level=1,
            skillpoints_in_skill=1000,
            trained_skill_level=1,
        )
        request = self.factory.get(
            reverse("memberaudit:character_skills_data", args=[self.character.pk])
        )
        request.user = self.user
        response = character_skills_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["group"], "Spaceship Command")
        self.assertEqual(row["skill"], "Amarr Carrier")
        self.assertEqual(row["level"], 1)

    def test_character_skillqueue_data_1(self):
        """Char has skills in training"""
        finish_date_1 = now() + dt.timedelta(days=3)
        CharacterSkillqueueEntry.objects.create(
            character=self.character,
            eve_type=self.skill_type_1,
            finish_date=finish_date_1,
            finished_level=5,
            queue_position=0,
            start_date=now() - dt.timedelta(days=1),
        )
        finish_date_2 = now() + dt.timedelta(days=10)
        CharacterSkillqueueEntry.objects.create(
            character=self.character,
            eve_type=self.skill_type_2,
            finish_date=finish_date_2,
            finished_level=5,
            queue_position=1,
            start_date=now() - dt.timedelta(days=1),
        )
        request = self.factory.get(
            reverse("memberaudit:character_skillqueue_data", args=[self.character.pk])
        )
        request.user = self.user
        response = character_skillqueue_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 2)

        row = data[0]
        self.assertEqual(row["skill"], "Amarr Carrier&nbsp;V [ACTIVE]")
        self.assertEqual(row["finished"]["sort"], finish_date_1.isoformat())
        self.assertTrue(row["is_active"])

        row = data[1]
        self.assertEqual(row["skill"], "Caldari Carrier&nbsp;V")
        self.assertEqual(row["finished"]["sort"], finish_date_2.isoformat())
        self.assertFalse(row["is_active"])

    def test_character_skillqueue_data_2(self):
        """Char has no skills in training"""
        CharacterSkillqueueEntry.objects.create(
            character=self.character,
            eve_type=self.skill_type_1,
            finished_level=5,
            queue_position=0,
        )
        request = self.factory.get(
            reverse("memberaudit:character_skillqueue_data", args=[self.character.pk])
        )
        request.user = self.user
        response = character_skillqueue_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["skill"], "Amarr Carrier&nbsp;V")
        self.assertIsNone(row["finished"]["sort"])
        self.assertFalse(row["is_active"])

    def test_character_wallet_journal_data(self):
        CharacterWalletJournalEntry.objects.create(
            character=self.character,
            entry_id=1,
            amount=1000000,
            balance=10000000,
            context_id_type=CharacterWalletJournalEntry.CONTEXT_ID_TYPE_UNDEFINED,
            date=now(),
            description="dummy",
            first_party=EveEntity.objects.get(id=1001),
            second_party=EveEntity.objects.get(id=1002),
        )
        request = self.factory.get(
            reverse(
                "memberaudit:character_wallet_journal_data", args=[self.character.pk]
            )
        )
        request.user = self.user
        response = character_wallet_journal_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["amount"], "1000000.00")
        self.assertEqual(row["balance"], "10000000.00")

    def test_character_mail_data(self):
        mailing_list = CharacterMailingList.objects.create(
            character=self.character, list_id=5, name="Mailing List"
        )
        mail = CharacterMail.objects.create(
            character=self.character,
            mail_id=99,
            from_entity=EveEntity.objects.get(id=1002),
            subject="Dummy",
            body="This is the body",
            timestamp=now(),
        )
        CharacterMailRecipient.objects.create(
            mail=mail, eve_entity=EveEntity.objects.get(id=1001)
        )
        CharacterMailRecipient.objects.create(mail=mail, mailing_list=mailing_list)
        request = self.factory.get(
            reverse(
                "memberaudit:character_mail_data", args=[self.character.pk, mail.pk]
            )
        )
        request.user = self.user
        response = character_mail_data(request, self.character.pk, mail.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(data["mail_id"], 99)
        self.assertEqual(data["from"], "Clark Kent")
        self.assertEqual(data["to"], "Bruce Wayne, Mailing List")
        self.assertEqual(data["body"], "This is the body")

    def test_character_finder_data(self):
        self.user = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.finder_access", self.user
        )
        request = self.factory.get(reverse("memberaudit:character_finder_data"))
        request.user = self.user
        response = character_finder_data(request)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertSetEqual({x["character_pk"] for x in data}, {self.character.pk})

    def test_character_corporation_history(self):
        date_1 = now() - dt.timedelta(days=60)
        CharacterCorporationHistory.objects.create(
            character=self.character,
            record_id=1,
            corporation=EveEntity.objects.get(id=2101),
            start_date=date_1,
        )
        date_2 = now() - dt.timedelta(days=20)
        CharacterCorporationHistory.objects.create(
            character=self.character,
            record_id=2,
            corporation=EveEntity.objects.get(id=2001),
            start_date=date_2,
        )
        request = self.factory.get(
            reverse(
                "memberaudit:character_corporation_history", args=[self.character.pk]
            )
        )
        request.user = self.user
        response = character_corporation_history(request, self.character.pk)
        self.assertEqual(response.status_code, 200)

    def test_character_character_implants_data(self):
        implant_1 = CharacterImplant.objects.create(
            character=self.character, eve_type=EveType.objects.get(id=19553)
        )
        implant_2 = CharacterImplant.objects.create(
            character=self.character, eve_type=EveType.objects.get(id=19540)
        )
        implant_3 = CharacterImplant.objects.create(
            character=self.character, eve_type=EveType.objects.get(id=19551)
        )
        request = self.factory.get(
            reverse("memberaudit:character_implants_data", args=[self.character.pk])
        )
        request.user = self.user
        response = character_implants_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)

        data = json_response_to_python_dict(response)
        self.assertSetEqual(
            set(data.keys()), {implant_1.pk, implant_2.pk, implant_3.pk}
        )
        self.assertIn(
            "High-grade Snake Gamma",
            data[implant_1.pk]["implant"]["display"],
        )
        self.assertEqual(data[implant_1.pk]["implant"]["sort"], 3)


class TestMailHeaderData(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.factory = RequestFactory()
        load_eveuniverse()
        load_entities()
        cls.character = create_memberaudit_character(1001)
        cls.user = cls.character.character_ownership.user
        cls.corporation_2001 = EveEntity.objects.get(id=2001)

        mailing_list = CharacterMailingList.objects.create(
            character=cls.character, list_id=5, name="Mailing List"
        )
        label_1 = CharacterMailLabel.objects.create(
            character=cls.character, label_id=42, name="Dummy"
        )
        labels2 = CharacterMailLabel.objects.create(
            character=cls.character, label_id=8, name="Another label"
        )
        mail_1 = CharacterMail.objects.create(
            character=cls.character,
            mail_id=7001,
            from_entity=EveEntity.objects.get(id=1002),
            subject="Dummy 1",
            body="Mail with normal entity and mailing list as recipient",
            timestamp=now(),
        )
        CharacterMailRecipient.objects.create(
            mail=mail_1, eve_entity=EveEntity.objects.get(id=1001)
        )
        CharacterMailRecipient.objects.create(
            mail=mail_1, eve_entity=EveEntity.objects.get(id=1003)
        )
        mail_1.labels.add(label_1)

        mail_2 = CharacterMail.objects.create(
            character=cls.character,
            mail_id=7002,
            from_entity=EveEntity.objects.get(id=1002),
            subject="Dummy 2",
            body="Mail with another label",
            timestamp=now(),
        )
        mail_2.labels.add(labels2)

        CharacterMail.objects.create(
            character=cls.character,
            mail_id=7003,
            from_mailing_list=mailing_list,
            subject="Dummy 3",
            body="Mailing List as sender",
            timestamp=now(),
        )

        mail_4 = CharacterMail.objects.create(
            character=cls.character,
            mail_id=7004,
            from_entity=EveEntity.objects.get(id=1002),
            subject="Dummy 4",
            body="Mailing List as recipient",
            timestamp=now(),
        )
        CharacterMailRecipient.objects.create(mail=mail_4, mailing_list=mailing_list)

    def test_mail_by_Label(self):
        """returns list of mails for given label only"""

        request = self.factory.get(
            reverse(
                "memberaudit:character_mail_headers_by_label_data",
                args=[self.character.pk, 42],
            )
        )
        request.user = self.user
        response = character_mail_headers_by_label_data(request, self.character.pk, 42)

        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)

        self.assertSetEqual({x["mail_id"] for x in data}, {7001})
        row = data[0]
        self.assertEqual(row["mail_id"], 7001)
        self.assertEqual(row["from"], "Clark Kent")
        self.assertEqual(row["to"], "Bruce Wayne, Peter Parker")

    def test_all_mails(self):
        """can return all mails"""

        request = self.factory.get(
            reverse(
                "memberaudit:character_mail_headers_by_label_data",
                args=[self.character.pk, 0],
            )
        )
        request.user = self.user
        response = character_mail_headers_by_label_data(request, self.character.pk, 0)

        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)

        self.assertSetEqual({x["mail_id"] for x in data}, {7001, 7002, 7003, 7004})

    def test_mail_to_mailinglist(self):
        """can return mail sent to mailing list"""

        request = self.factory.get(
            reverse(
                "memberaudit:character_mail_headers_by_list_data",
                args=[self.character.pk, 5],
            )
        )
        request.user = self.user
        response = character_mail_headers_by_list_data(request, self.character.pk, 5)

        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)

        self.assertSetEqual({x["mail_id"] for x in data}, {7004})
        row = data[0]
        self.assertEqual(row["to"], "Mailing List")


@patch(MODULE_PATH + ".messages_plus")
class TestRemoveCharacter(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.factory = RequestFactory()
        load_entities()

    def setUp(self) -> None:
        self.character_1001 = create_memberaudit_character(1001)
        self.user_1001 = self.character_1001.character_ownership.user

        self.character_1002 = create_memberaudit_character(1002)
        self.user_1002 = self.character_1002.character_ownership.user

    def test_normal(self, mock_message_plus):
        request = self.factory.get(
            reverse("memberaudit:remove_character", args=[self.character_1001.pk])
        )
        request.user = self.user_1001
        response = remove_character(request, self.character_1001.pk)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("memberaudit:launcher"))
        self.assertFalse(Character.objects.filter(pk=self.character_1001.pk).exists())
        self.assertTrue(mock_message_plus.success.called)

    def test_no_permission(self, mock_message_plus):
        request = self.factory.get(
            reverse("memberaudit:remove_character", args=[self.character_1001.pk])
        )
        request.user = self.user_1002
        response = remove_character(request, self.character_1001.pk)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Character.objects.filter(pk=self.character_1001.pk).exists())
        self.assertFalse(mock_message_plus.success.called)

    def test_not_found(self, mock_message_plus):
        invalid_character_pk = generate_invalid_pk(Character)
        request = self.factory.get(
            reverse("memberaudit:remove_character", args=[invalid_character_pk])
        )
        request.user = self.user_1001
        response = remove_character(request, invalid_character_pk)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Character.objects.filter(pk=self.character_1001.pk).exists())
        self.assertFalse(mock_message_plus.success.called)


class TestShareCharacter(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.factory = RequestFactory()
        load_entities()

    def setUp(self) -> None:
        self.character_1001 = create_memberaudit_character(1001)
        self.user_1001 = self.character_1001.character_ownership.user

        self.character_1002 = create_memberaudit_character(1002)
        self.user_1002 = self.character_1002.character_ownership.user

    def test_normal(self):
        request = self.factory.get(
            reverse("memberaudit:share_character", args=[self.character_1001.pk])
        )
        request.user = self.user_1001
        response = share_character(request, self.character_1001.pk)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("memberaudit:launcher"))
        self.assertTrue(Character.objects.get(pk=self.character_1001.pk).is_shared)

    def test_no_permission(self):
        request = self.factory.get(
            reverse("memberaudit:share_character", args=[self.character_1001.pk])
        )
        request.user = self.user_1002
        response = share_character(request, self.character_1001.pk)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Character.objects.get(pk=self.character_1001.pk).is_shared)

    def test_not_found(self):
        invalid_character_pk = generate_invalid_pk(Character)
        request = self.factory.get(
            reverse("memberaudit:share_character", args=[invalid_character_pk])
        )
        request.user = self.user_1001
        response = share_character(request, invalid_character_pk)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Character.objects.get(pk=self.character_1001.pk).is_shared)


class TestUnshareCharacter(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.factory = RequestFactory()
        load_entities()

    def setUp(self) -> None:
        self.character_1001 = create_memberaudit_character(1001)
        self.character_1001.is_shared = True
        self.character_1001.save()
        self.user_1001 = self.character_1001.character_ownership.user

        self.character_1002 = create_memberaudit_character(1002)
        self.user_1002 = self.character_1002.character_ownership.user

    def test_normal(self):
        request = self.factory.get(
            reverse("memberaudit:unshare_character", args=[self.character_1001.pk])
        )
        request.user = self.user_1001
        response = unshare_character(request, self.character_1001.pk)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("memberaudit:launcher"))
        self.assertFalse(Character.objects.get(pk=self.character_1001.pk).is_shared)

    def test_no_permission(self):
        request = self.factory.get(
            reverse("memberaudit:unshare_character", args=[self.character_1001.pk])
        )
        request.user = self.user_1002
        response = unshare_character(request, self.character_1001.pk)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Character.objects.get(pk=self.character_1001.pk).is_shared)

    def test_not_found(self):
        invalid_character_pk = generate_invalid_pk(Character)
        request = self.factory.get(
            reverse("memberaudit:unshare_character", args=[invalid_character_pk])
        )
        request.user = self.user_1001
        response = unshare_character(request, invalid_character_pk)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Character.objects.get(pk=self.character_1001.pk).is_shared)


class TestComplianceReportData(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.factory = RequestFactory()
        load_eveuniverse()
        load_entities()
        state = AuthUtils.get_member_state()
        state.member_alliances.add(EveAllianceInfo.objects.get(alliance_id=3001))

        cls.character_1001 = create_memberaudit_character(1001)
        cls.character_1002 = create_memberaudit_character(1002)
        cls.character_1003 = create_memberaudit_character(1003)
        cls.character_1101 = create_memberaudit_character(1101)
        cls.character_1102 = create_memberaudit_character(1102)

        cls.user = cls.character_1001.character_ownership.user
        cls.user = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.reports_access", cls.user
        )

    @staticmethod
    def user_pks_set(data) -> set:
        return {x["user_pk"] for x in data}

    def _execute_request(self) -> list:
        request = self.factory.get(reverse("memberaudit:compliance_report_data"))
        request.user = self.user
        response = compliance_report_data(request)
        self.assertEqual(response.status_code, 200)
        return json_response_to_python(response)

    def test_no_scope(self):
        result = self._execute_request()
        self.assertSetEqual(self.user_pks_set(result), set())

    def test_corporation_permission(self):
        self.user = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_same_corporation", self.user
        )
        result = self._execute_request()
        self.assertSetEqual(
            self.user_pks_set(result),
            {
                self.character_1001.character_ownership.user.pk,
                self.character_1002.character_ownership.user.pk,
            },
        )

    def test_alliance_permission(self):
        self.user = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_same_alliance", self.user
        )
        result = self._execute_request()
        self.assertSetEqual(
            self.user_pks_set(result),
            {
                self.character_1001.character_ownership.user.pk,
                self.character_1002.character_ownership.user.pk,
                self.character_1003.character_ownership.user.pk,
            },
        )


@patch(MODULE_PATH + ".Character.fetch_location")
class TestCharacterLocationData(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.factory = RequestFactory()
        load_eveuniverse()
        load_entities()
        load_locations()
        cls.character = create_memberaudit_character(1001)
        cls.user = cls.character.character_ownership.user
        cls.jita = EveSolarSystem.objects.get(id=30000142)
        cls.jita_44 = Location.objects.get(id=60003760)

    def test_location_normal(self, mock_fetch_location):
        mock_fetch_location.return_value = (self.jita, self.jita_44)

        request = self.factory.get(
            reverse("memberaudit:character_location_data", args=[self.character.pk])
        )
        request.user = self.user
        orig_view = character_location_data.__wrapped__
        response = orig_view(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Caldari Navy Assembly Plant", response.content.decode("utf8"))

    def test_solar_system_normal(self, mock_fetch_location):
        mock_fetch_location.return_value = (self.jita, self.jita_44)

        request = self.factory.get(
            reverse("memberaudit:character_location_data", args=[self.character.pk])
        )
        request.user = self.user
        orig_view = character_location_data.__wrapped__
        response = orig_view(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Jita", response.content.decode("utf8"))

    def test_http_error(self, mock_fetch_location):
        mock_fetch_location.side_effect = HTTPNotFound(
            response=ResponseStub(404, "Test exception")
        )

        request = self.factory.get(
            reverse("memberaudit:character_location_data", args=[self.character.pk])
        )
        request.user = self.user
        orig_view = character_location_data.__wrapped__
        response = orig_view(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Network error", response.content.decode("utf8"))

    def test_unexpected_error(self, mock_fetch_location):
        mock_fetch_location.side_effect = RuntimeError

        request = self.factory.get(
            reverse("memberaudit:character_location_data", args=[self.character.pk])
        )
        request.user = self.user
        orig_view = character_location_data.__wrapped__
        response = orig_view(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Unexpected error", response.content.decode("utf8"))


class TestDoctrineReportData(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.factory = RequestFactory()
        load_eveuniverse()
        load_entities()
        state = AuthUtils.get_member_state()
        state.member_alliances.add(EveAllianceInfo.objects.get(alliance_id=3001))

        # user 1 is manager requesting the report
        cls.character_1001 = create_memberaudit_character(1001)
        cls.user = cls.character_1001.character_ownership.user
        cls.user = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.reports_access", cls.user
        )
        cls.user = AuthUtils.add_permission_to_user_by_name(
            "memberaudit.view_everything", cls.user
        )

        # user 2 is normal user and has two characters
        cls.character_1002 = create_memberaudit_character(1002)
        cls.character_1101 = add_memberaudit_character_to_user(
            cls.character_1002.character_ownership.user, 1101
        )
        # cls.character_1003 = create_memberaudit_character(1003)

        cls.skill_type_1 = EveType.objects.get(id=24311)
        cls.skill_type_2 = EveType.objects.get(id=24312)

    def test_normal(self):
        def make_data_id(doctrine: Doctrine, character: Character) -> str:
            doctrine_pk = doctrine.pk if doctrine else 0
            return f"{doctrine_pk}_{character.pk}"

        # define doctrines
        ship_1 = DoctrineShip.objects.create(name="Ship 1")
        DoctrineShipSkill.objects.create(
            ship=ship_1, eve_type=self.skill_type_1, level=3
        )

        ship_2 = DoctrineShip.objects.create(name="Ship 2")
        DoctrineShipSkill.objects.create(
            ship=ship_2, eve_type=self.skill_type_1, level=5
        )
        DoctrineShipSkill.objects.create(
            ship=ship_2, eve_type=self.skill_type_2, level=3
        )

        ship_3 = DoctrineShip.objects.create(name="Ship 3")
        DoctrineShipSkill.objects.create(
            ship=ship_3, eve_type=self.skill_type_1, level=1
        )

        doctrine_1 = Doctrine.objects.create(name="Alpha")
        doctrine_1.ships.add(ship_1)
        doctrine_1.ships.add(ship_2)

        doctrine_2 = Doctrine.objects.create(name="Bravo")
        doctrine_2.ships.add(ship_1)

        # character 1002
        CharacterSkill.objects.create(
            character=self.character_1002,
            eve_type=self.skill_type_1,
            active_skill_level=5,
            skillpoints_in_skill=10,
            trained_skill_level=5,
        )
        CharacterSkill.objects.create(
            character=self.character_1002,
            eve_type=self.skill_type_2,
            active_skill_level=2,
            skillpoints_in_skill=10,
            trained_skill_level=2,
        )

        # character 1101
        CharacterSkill.objects.create(
            character=self.character_1101,
            eve_type=self.skill_type_1,
            active_skill_level=5,
            skillpoints_in_skill=10,
            trained_skill_level=5,
        )
        CharacterSkill.objects.create(
            character=self.character_1101,
            eve_type=self.skill_type_2,
            active_skill_level=5,
            skillpoints_in_skill=10,
            trained_skill_level=5,
        )

        self.character_1001.update_doctrines()
        self.character_1002.update_doctrines()
        self.character_1101.update_doctrines()

        request = self.factory.get(reverse("memberaudit:doctrines_report_data"))
        request.user = self.user
        response = doctrines_report_data(request)

        self.assertEqual(response.status_code, 200)
        data = json_response_to_python_dict(response)
        self.assertEqual(len(data), 9)

        row = data[make_data_id(doctrine_1, self.character_1001)]
        self.assertEqual(row["doctrine"], "Alpha")
        self.assertEqual(row["character"], "Bruce Wayne")
        self.assertEqual(row["main"], "Bruce Wayne")
        self.assertTrue(multi_assert_not_in(["Ship 1", "Ship 2"], row["can_fly"]))

        row = data[make_data_id(doctrine_1, self.character_1002)]
        self.assertEqual(row["doctrine"], "Alpha")
        self.assertEqual(row["character"], "Clark Kent")
        self.assertEqual(row["main"], "Clark Kent")

        self.assertTrue(multi_assert_in(["Ship 1"], row["can_fly"]))
        self.assertTrue(multi_assert_not_in(["Ship 2", "Ship 3"], row["can_fly"]))

        row = data[make_data_id(doctrine_1, self.character_1101)]
        self.assertEqual(row["doctrine"], "Alpha")
        self.assertEqual(row["character"], "Lex Luther")
        self.assertEqual(row["main"], "Clark Kent")
        self.assertTrue(multi_assert_in(["Ship 1", "Ship 2"], row["can_fly"]))

        row = data[make_data_id(doctrine_2, self.character_1101)]
        self.assertEqual(row["doctrine"], "Bravo")
        self.assertEqual(row["character"], "Lex Luther")
        self.assertEqual(row["main"], "Clark Kent")
        self.assertTrue(multi_assert_in(["Ship 1"], row["can_fly"]))
        self.assertTrue(multi_assert_not_in(["Ship 2"], row["can_fly"]))

        row = data[make_data_id(None, self.character_1101)]
        self.assertEqual(row["doctrine"], "(No Doctrine)")
        self.assertEqual(row["character"], "Lex Luther")
        self.assertEqual(row["main"], "Clark Kent")
        self.assertTrue(multi_assert_in(["Ship 3"], row["can_fly"]))
