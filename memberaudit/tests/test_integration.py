from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse

from django_webtest import WebTest
from eveuniverse.models import EveType

from ..models import CharacterAsset, Location
from .testdata.esi_client_stub import esi_client_stub
from .testdata.load_eveuniverse import load_eveuniverse
from .testdata.load_entities import load_entities
from .testdata.load_locations import load_locations
from . import (
    create_memberaudit_character,
    add_auth_character_to_user,
    create_user_from_evecharacter,
    add_memberaudit_character_to_user,
)

MODELS_PATH = "memberaudit.models"


class TestUILauncher(WebTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        load_locations()

    def setUp(self) -> None:
        self.user, _ = create_user_from_evecharacter(1002)

    def test_open_character_viewer(self):
        """
        given user has character registered
        when clicking on respective character link
        then user is forwarded to character viewer
        """
        # setup
        character = add_memberaudit_character_to_user(self.user, 1001)

        # login & open launcher page
        self.app.set_user(self.user)
        launcher = self.app.get(reverse("memberaudit:launcher"))
        self.assertEqual(launcher.status_code, 200)

        # user clicks on character link
        character_viewer = launcher.click(
            href=reverse("memberaudit:character_viewer", args=[character.pk]),
            index=0,  # follow the first matching link
        )
        self.assertEqual(character_viewer.status_code, 200)

    @patch(MODELS_PATH + ".is_esi_online", lambda: True)
    @patch(MODELS_PATH + ".esi")
    @override_settings(CELERY_ALWAYS_EAGER=True)
    def test_add_character(self, mock_esi):
        """
        when clicking on "register"
        then user can add a new character
        """
        mock_esi.client = esi_client_stub
        # user as another auth character
        character_ownership_1001 = add_auth_character_to_user(self.user, 1001)

        # login & open launcher page
        self.app.set_user(self.user)
        launcher = self.app.get(reverse("memberaudit:launcher"))
        self.assertEqual(launcher.status_code, 200)

        # user clicks on register link
        select_token = launcher.click(
            href=reverse("memberaudit:add_character"),
            index=1,  # follow the 2nd matching link
        )
        self.assertEqual(select_token.status_code, 200)

        # user selects auth character 1001
        token = self.user.token_set.get(character_id=1001)
        my_form = None
        for form in select_token.forms.values():
            try:
                if int(form["_token"].value) == token.pk:
                    my_form = form
                    break
            except AssertionError:
                pass

        self.assertIsNotNone(my_form)
        launcher = my_form.submit().follow()
        self.assertEqual(launcher.status_code, 200)

        # check update went through
        character_1001 = character_ownership_1001.memberaudit_character
        self.assertTrue(character_1001.is_update_status_ok())

        # check added character is now visible in launcher
        character_1001_links = [
            x["href"]
            for x in launcher.html.find_all("a", href=True)
            if x["href"] == f"/memberaudit/character_viewer/{character_1001.pk}/"
        ]
        self.assertGreater(len(character_1001_links), 0)


class TestUICharacterViewer(WebTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        load_locations()
        cls.character = create_memberaudit_character(1001)
        cls.user = cls.character.character_ownership.user
        cls.jita_44 = Location.objects.get(id=60003760)

    def test_character_viewer_asset_container(self):
        """
        given user has a registered character with assets which contain other assets
        when user clicks on an asset container
        then the contents of that asset container are shown
        """
        # setup data
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

        # open character viewer
        self.app.set_user(self.user)
        character_viewer = self.app.get(
            reverse("memberaudit:character_viewer", args=[self.character.pk])
        )
        self.assertEqual(character_viewer.status_code, 200)

        # open asset container
        asset_container = self.app.get(
            reverse(
                "memberaudit:character_asset_container",
                args=[self.character.pk, parent_asset.pk],
            )
        )
        self.assertEqual(asset_container.status_code, 200)
