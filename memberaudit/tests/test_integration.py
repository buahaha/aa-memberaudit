from django.urls import reverse

from django_webtest import WebTest
from eveuniverse.models import EveType

from ..models import CharacterAsset, Location
from .testdata.load_eveuniverse import load_eveuniverse
from .testdata.load_entities import load_entities
from .testdata.load_locations import load_locations
from . import create_memberaudit_character


class TestUI(WebTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        load_locations()
        cls.character = create_memberaudit_character(1001)
        cls.user = cls.character.character_ownership.user
        cls.jita_44 = Location.objects.get(id=60003760)

    def test_launcher_to_character_viewer(self):
        """
        when character of user is shown in launcher
        then user can click on character link to open character viewer
        """
        self.app.set_user(self.user)
        launcher = self.app.get(reverse("memberaudit:launcher"))
        self.assertEqual(launcher.status_code, 200)

        # user clicks on character link
        character_viewer = launcher.click(
            href=reverse("memberaudit:character_viewer", args=[self.character.pk]),
            index=0,  # follow the first matching link
        )
        self.assertEqual(character_viewer.status_code, 200)

    def test_character_viewer_asset_container(self):
        """
        when user has assets which contain other assets
        then he can open that asset container in the character viewer
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
