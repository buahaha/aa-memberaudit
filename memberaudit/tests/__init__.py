from typing import Tuple

from django.contrib.auth.models import User

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter
from allianceauth.tests.auth_utils import AuthUtils

from ..models import Character
from .utils import add_character_to_user


def create_user_from_evecharacter(character_id: int) -> Tuple[User, CharacterOwnership]:
    auth_character = EveCharacter.objects.get(character_id=character_id)
    user = AuthUtils.create_user(auth_character.character_name)
    AuthUtils.add_permission_to_user_by_name("memberaudit.basic_access", user)
    character_ownership = add_character_to_user(
        user, auth_character, is_main=True, scopes=Character.get_esi_scopes()
    )
    return user, character_ownership


def create_memberaudit_character(character_id: int) -> Character:
    _, character_ownership = create_user_from_evecharacter(character_id)
    return Character.objects.create(character_ownership=character_ownership)
