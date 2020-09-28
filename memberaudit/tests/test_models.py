from django.contrib.auth.models import User
from django.test import TestCase

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.tests.auth_utils import AuthUtils

from ..models import Owner


class TestOwnerUserHasAccess(TestCase):
    @classmethod
    def setUp(self) -> None:
        self.user = AuthUtils.create_user("Bruce Wanye")
        self.auth_character = AuthUtils.add_main_character_2(
            self.user, "Bruce Wayne", 1001
        )
        character_ownership = CharacterOwnership.objects.create(
            user=self.user, character=self.auth_character, owner_hash="123456"
        )
        self.owner = Owner.objects.create(character_ownership=character_ownership)

    def test_user_owning_character_has_access(self):
        self.assertTrue(self.owner.user_has_access(self.user))

    def test_other_user_has_no_access(self):
        user_2 = AuthUtils.create_user("Lex Luthor")
        self.assertFalse(self.owner.user_has_access(user_2))

    def test_user_with_permission_unrestricted_has_access(self):
        user_3 = AuthUtils.create_user("Peter Parker")
        AuthUtils.add_permission_to_user_by_name(
            "memberaudit.unrestricted_access", user_3
        )
        user_3 = User.objects.get(pk=user_3.pk)
        self.assertTrue(self.owner.user_has_access(user_3))
