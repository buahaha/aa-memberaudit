from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite

from . import create_user_from_evecharacter
from ..admin import SkillSetAdmin, SkillSetShipTypeFilter
from ..models import SkillSet, EveShipType
from .testdata.load_eveuniverse import load_eveuniverse
from .testdata.load_entities import load_entities

MODULE_PATH = "memberaudit.admin"


class MockRequest(object):
    def __init__(self, user=None):
        self.user = user


class TestSkillSetAdmin(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = RequestFactory()
        cls.modeladmin = SkillSetAdmin(model=SkillSet, admin_site=AdminSite())
        load_eveuniverse()
        load_entities()
        cls.user, _ = create_user_from_evecharacter(1001)

    @patch(MODULE_PATH + ".tasks.update_characters_skill_checks")
    def test_save_model(self, mock_update_characters_skill_checks):
        ship = SkillSet.objects.create(name="Dummy")
        request = MockRequest(self.user)
        form = self.modeladmin.get_form(request)
        self.modeladmin.save_model(request, ship, form, True)

        self.assertTrue(mock_update_characters_skill_checks.delay.called)

    @patch(MODULE_PATH + ".tasks.update_characters_skill_checks")
    def test_delete_model(self, mock_update_characters_skill_checks):
        ship = SkillSet.objects.create(name="Dummy")
        request = MockRequest(self.user)
        self.modeladmin.delete_model(request, ship)

        self.assertTrue(mock_update_characters_skill_checks.delay.called)

    def test_ship_type_filter(self):
        class SkillSetAdminTest(SkillSetAdmin):
            list_filter = (SkillSetShipTypeFilter,)

        my_modeladmin = SkillSetAdminTest(SkillSet, AdminSite())

        ss_1 = SkillSet.objects.create(name="Set 1")
        ss_2 = SkillSet.objects.create(
            name="Set 2", ship_type=EveShipType.objects.get(id=603)
        )

        # Make sure the lookups are correct
        request = self.factory.get("/")
        request.user = self.user
        changelist = my_modeladmin.get_changelist_instance(request)
        filters = changelist.get_filters(request)
        filterspec = filters[0][0]
        expected = [("yes", "yes"), ("no", "no")]
        self.assertEqual(filterspec.lookup_choices, expected)

        # Make sure the correct queryset is returned
        request = self.factory.get("/", {"is_ship_type": "yes"})
        request.user = self.user
        changelist = my_modeladmin.get_changelist_instance(request)
        queryset = changelist.get_queryset(request)
        expected = {ss_2}
        self.assertSetEqual(set(queryset), expected)

        # Make sure the correct queryset is returned
        request = self.factory.get("/", {"is_ship_type": "no"})
        request.user = self.user
        changelist = my_modeladmin.get_changelist_instance(request)
        queryset = changelist.get_queryset(request)
        expected = {ss_1}
        self.assertSetEqual(set(queryset), expected)
