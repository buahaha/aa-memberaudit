from unittest.mock import Mock, patch

from django.contrib.auth.models import Group
from django.test import TestCase

from allianceauth.eveonline.evelinks import dotlan, evewho
from allianceauth.tests.auth_utils import AuthUtils

from .testdata.esi_client_stub import load_test_data
from .testdata.load_entities import load_entities
from ..helpers import eve_xml_to_html, users_with_permission


class TestHTMLConversion(TestCase):
    def test_convert_eve_xml_alliance(self):
        """can convert an alliance link in CCP XML to HTML"""
        with patch(
            "eveuniverse.models.EveEntity.objects.resolve_name",
            Mock(return_value="An Alliance"),
        ):
            result = eve_xml_to_html(
                load_test_data()
                .get("Mail")
                .get("get_characters_character_id_mail_mail_id")
                .get("2")
                .get("body")
            )
            self.assertTrue(result.find(dotlan.alliance_url("An Alliance")) != -1)

    def test_convert_eve_xml_character(self):
        """can convert a character link in CCP XML to HTML"""
        result = eve_xml_to_html(
            load_test_data()
            .get("Mail")
            .get("get_characters_character_id_mail_mail_id")
            .get("2")
            .get("body")
        )
        self.assertTrue(result.find(evewho.character_url(1001)) != -1)

    def test_convert_eve_xml_corporation(self):
        """can convert a corporation link in CCP XML to HTML"""
        with patch(
            "eveuniverse.models.EveEntity.objects.resolve_name",
            Mock(return_value="A Corporation"),
        ):
            result = eve_xml_to_html(
                load_test_data()
                .get("Mail")
                .get("get_characters_character_id_mail_mail_id")
                .get("2")
                .get("body")
            )
            self.assertTrue(result.find(dotlan.alliance_url("A Corporation")) != -1)

    def test_convert_eve_xml_solar_system(self):
        """can convert a solar system link in CCP XML to HTML"""
        with patch(
            "eveuniverse.models.EveEntity.objects.resolve_name",
            Mock(return_value="Polaris"),
        ):
            result = eve_xml_to_html(
                load_test_data()
                .get("Mail")
                .get("get_characters_character_id_mail_mail_id")
                .get("2")
                .get("body")
            )
            self.assertTrue(result.find(dotlan.solar_system_url("Polaris")) != -1)


class TestUsersWithPermissionQS(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_entities()
        cls.permission = AuthUtils.get_permission_by_name("memberaudit.basic_access")
        cls.group, _ = Group.objects.get_or_create(name="Test Group")
        AuthUtils.add_permissions_to_groups([cls.permission], [cls.group])
        cls.state = AuthUtils.create_state(name="Test State", priority=75)
        cls.state.permissions.add(cls.permission)

    def setUp(self) -> None:
        self.user_1 = AuthUtils.create_user("Bruce Wayne")
        self.user_2 = AuthUtils.create_user("Lex Luther")

    @classmethod
    def user_with_permission_pks(cls) -> set:
        return set(users_with_permission(cls.permission).values_list("pk", flat=True))

    def test_user_permission(self):
        """direct user permissions"""
        AuthUtils.add_permissions_to_user([self.permission], self.user_1)
        self.assertSetEqual(self.user_with_permission_pks(), {self.user_1.pk})

    def test_group_permission(self):
        """group permissions"""
        self.user_1.groups.add(self.group)
        self.assertSetEqual(self.user_with_permission_pks(), {self.user_1.pk})

    def test_state_permission(self):
        """state permissions"""
        AuthUtils.assign_state(self.user_1, self.state, disconnect_signals=True)
        self.assertSetEqual(self.user_with_permission_pks(), {self.user_1.pk})

    def test_distinct_qs(self):
        """only return one user object, despiste multiple matches"""
        AuthUtils.add_permissions_to_user([self.permission], self.user_1)
        self.user_1.groups.add(self.group)
        AuthUtils.assign_state(self.user_1, self.state, disconnect_signals=True)
        self.assertSetEqual(self.user_with_permission_pks(), {self.user_1.pk})
