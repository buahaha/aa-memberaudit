from unittest.mock import patch, Mock

from allianceauth.tests.auth_utils import AuthUtils
from allianceauth.authentication.models import CharacterOwnership
from bravado.exception import HTTPUnauthorized
from celery.exceptions import Retry as CeleryRetry

from django.core.cache import cache
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings

from eveuniverse.models import EveSolarSystem, EveType
from esi.models import Token

from . import create_memberaudit_character
from ..models import (
    Character,
    CharacterAsset,
    CharacterUpdateStatus,
    Location,
    Settings,
)
from ..tasks import (
    LOCATION_ESI_ERRORS_CACHE_KEY,
    ESI_ERROR_LIMIT,
    update_all_characters,
    update_character,
    update_character_assets,
    update_structure_esi,
    update_all_user_assignments,
)
from .testdata.esi_client_stub import esi_client_stub
from .testdata.load_eveuniverse import load_eveuniverse
from .testdata.load_entities import load_entities
from .testdata.load_locations import load_locations
from ..utils import generate_invalid_pk

MODELS_PATH = "memberaudit.models"
MANAGERS_PATH = "memberaudit.managers"
TASKS_PATH = "memberaudit.tasks"


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


@patch(MODELS_PATH + ".is_esi_online", lambda: True)
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


@patch(TASKS_PATH + ".is_esi_online", lambda: True)
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

    def test_raise_exception_on_invalid_token(
        self, mock_structure_update_or_create_esi
    ):
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


@override_settings(CELERY_ALWAYS_EAGER=True)
class TestGroupProvisioning(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_entities()

    def setUp(self) -> None:
        self.user = AuthUtils.create_user("George_RR_Martin")
        self.character_1 = AuthUtils.add_main_character_2(
            self.user, "Sansha Stark", 1005
        )
        self.character_2 = AuthUtils.add_main_character_2(self.user, "Aria Stark", 1006)
        self.group, _ = Group.objects.get_or_create(name="Test Group")

    def _associate_character(self, user, character):
        return CharacterOwnership.objects.create(
            character=character,
            owner_hash="x1" + character.character_name,
            user=user,
        )

    @patch(MODELS_PATH + ".Settings.load")
    def test_update_user_assignment_none(self, mock_settings_load):
        """When we have no compliance group defined, we should not add users"""
        mock_settings_load.return_value = Settings(compliant_user_group=None)
        self._associate_character(self.user, self.character_1)
        update_all_user_assignments()
        self.assertEquals(len(self.user.groups.values()), 0)

    @patch(MODELS_PATH + ".Settings.load")
    def test_update_user_assignment_single_not_added(self, mock_settings_load):
        """When we have a single character not registered with member audit, we should not add users"""
        mock_settings_load.return_value = Settings(compliant_user_group=self.group)
        self._associate_character(self.user, self.character_1)
        update_all_user_assignments()
        self.assertEquals(len(self.user.groups.values()), 0)

    @patch(MODELS_PATH + ".Settings.load")
    def test_update_user_assignment_single_remove(self, mock_settings_load):
        """When we have a single character not registered with member audit, we should remove existing users"""
        mock_settings_load.return_value = Settings(compliant_user_group=self.group)
        self._associate_character(self.user, self.character_1)
        self.group.user_set.add(self.user)
        update_all_user_assignments()
        self.assertEquals(len(self.user.groups.values()), 0)

    @patch(MODELS_PATH + ".Settings.load")
    def test_update_user_assignment_zero_not_added(self, mock_settings_load):
        """When we have no characters not registered with member audit, we should NOT add users"""
        mock_settings_load.return_value = Settings(compliant_user_group=self.group)
        update_all_user_assignments()
        self.assertEquals(len(self.user.groups.values()), 0)

    @patch(MODELS_PATH + ".Settings.load")
    def test_update_user_assignment_single_added(self, mock_settings_load):
        """When we have a single character registered with member audit, we should add users"""
        mock_settings_load.return_value = Settings(compliant_user_group=self.group)
        ownership = self._associate_character(self.user, self.character_1)
        Character.objects.create(character_ownership=ownership)
        update_all_user_assignments()
        self.assertEquals(self.user.groups.first(), self.group)

    @patch(MODELS_PATH + ".Settings.load")
    def test_update_user_assignment_partial_not_added(self, mock_settings_load):
        """When we have a single character registered with member audit AND one character not registered, we should not add users"""
        mock_settings_load.return_value = Settings(compliant_user_group=self.group)
        ownership_1 = self._associate_character(self.user, self.character_1)
        self._associate_character(self.user, self.character_2)
        Character.objects.create(character_ownership=ownership_1)
        update_all_user_assignments()
        self.assertEquals(len(self.user.groups.values()), 0)

    @patch(MODELS_PATH + ".Settings.load")
    def test_update_user_assignment_partial_removed(self, mock_settings_load):
        """When we have a single character registered with member audit AND one character not registered, we should remove users"""
        mock_settings_load.return_value = Settings(compliant_user_group=self.group)
        ownership_1 = self._associate_character(self.user, self.character_1)
        self._associate_character(self.user, self.character_2)
        Character.objects.create(character_ownership=ownership_1)
        self.group.user_set.add(self.user)
        update_all_user_assignments()
        self.assertEquals(len(self.user.groups.values()), 0)

    @patch(MODELS_PATH + ".Settings.load")
    def test_update_user_assignment_all_added(self, mock_settings_load):
        """When we have all characters registered with member audit, we should add users"""
        mock_settings_load.return_value = Settings(compliant_user_group=self.group)
        self.assertTrue(Settings.load().compliant_user_group == self.group)
        ownership_1 = self._associate_character(self.user, self.character_1)
        ownership_2 = self._associate_character(self.user, self.character_2)
        Character.objects.create(character_ownership=ownership_1)
        Character.objects.create(character_ownership=ownership_2)
        update_all_user_assignments()
        self.assertEquals(self.user.groups.first(), self.group)

    @patch(TASKS_PATH + ".update_user_assignment")
    def test_update_all_user_assignments_noop(self, mock_update_user_assignment):
        Settings.objects.create(compliant_user_group=None)
        self.assertTrue(Settings.load().compliant_user_group is None)
        update_all_user_assignments()
        self.assertFalse(mock_update_user_assignment.called)
