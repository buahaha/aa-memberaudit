from django.http import HttpResponse
from django.test import TestCase, RequestFactory

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.tests.auth_utils import AuthUtils

from ..decorators import fetch_character_if_allowed
from ..models import Character
from ..utils import generate_invalid_pk


DUMMY_URL = "http://www.example.com"


class TestFetchOwnerIfAllowed(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.factory = RequestFactory()
        cls.user = AuthUtils.create_user("Bruce Wanye")
        cls.auth_character = AuthUtils.add_main_character_2(
            cls.user, "Bruce Wayne", 1001
        )
        CharacterOwnership.objects.create(
            user=cls.user, character=cls.auth_character, owner_hash="123456"
        )

    def setUp(self) -> None:
        self.character = Character.objects.create(
            character_ownership=self.auth_character.character_ownership
        )

    def test_passthrough_when_fetch_owner_if_allowed(self):
        @fetch_character_if_allowed()
        def dummy(request, character_pk, character):
            self.assertEqual(character, self.character)
            self.assertIn("character_ownership", character._state.fields_cache)
            return HttpResponse("ok")

        request = self.factory.get(DUMMY_URL)
        request.user = self.user
        response = dummy(request, self.character.pk)
        self.assertEqual(response.status_code, 200)

    def test_returns_404_when_owner_not_found(self):
        @fetch_character_if_allowed()
        def dummy(request, character_pk, character):
            self.assertTrue(False)

        request = self.factory.get(DUMMY_URL)
        request.user = self.user
        response = dummy(request, generate_invalid_pk(Character))
        self.assertEqual(response.status_code, 404)

    def test_returns_403_when_user_has_not_access(self):
        @fetch_character_if_allowed()
        def dummy(request, character_pk, character):
            self.assertTrue(False)

        user_2 = AuthUtils.create_user("Lex Luthor")
        request = self.factory.get(DUMMY_URL)
        request.user = user_2
        response = dummy(request, self.character.pk)
        self.assertEqual(response.status_code, 403)

    """
    TODO: create test case with CharacterDetails
    def test_can_specify_list_for_select_related(self):
        @fetch_character_if_allowed("skills")
        def dummy(request, character_pk, character):
            self.assertEqual(character, self.character)
            self.assertIn("skills", character._state.fields_cache)
            return HttpResponse("ok")

        OwnerSkills.objects.create(character=self.character, total_sp=10000000)
        request = self.factory.get(DUMMY_URL)
        request.user = self.user
        dummy(request, self.character.pk)
    """
