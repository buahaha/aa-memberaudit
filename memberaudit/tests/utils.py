"""Test utilities"""

from datetime import datetime, timedelta
import random
import string

from django.contrib.auth.models import User

from esi.models import Scope, Token

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter
from allianceauth.tests.auth_utils import AuthUtils


def _dt_eveformat(dt: object) -> str:
    """converts a datetime to a string in eve format
    e.g. '2019-06-25T19:04:44'
    """
    dt2 = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    return dt2.isoformat()


def _generate_token(
    character_id: int,
    character_name: str,
    access_token: str = "access_token",
    refresh_token: str = "refresh_token",
    scopes: list = None,
    timestamp_dt: object = None,
    expires_in: int = 1200,
) -> dict:

    if timestamp_dt is None:
        timestamp_dt = datetime.utcnow()
    if scopes is None:
        scopes = [
            "esi-mail.read_mail.v1",
            "esi-wallet.read_character_wallet.v1",
            "esi-universe.read_structures.v1",
        ]
    token = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "refresh_token": refresh_token,
        "timestamp": int(timestamp_dt.timestamp()),
        "CharacterID": character_id,
        "CharacterName": character_name,
        "ExpiresOn": _dt_eveformat(timestamp_dt + timedelta(seconds=expires_in)),
        "Scopes": " ".join(list(scopes)),
        "TokenType": "Character",
        "CharacterOwnerHash": _get_random_string(28),
        "IntellectualProperty": "EVE",
    }
    return token


def _store_as_Token(token: dict, user: object) -> object:
    """Stores a generated token dict as Token object for given user

    returns Token object
    """
    obj = Token.objects.create(
        access_token=token["access_token"],
        refresh_token=token["refresh_token"],
        user=user,
        character_id=token["CharacterID"],
        character_name=token["CharacterName"],
        token_type=token["TokenType"],
        character_owner_hash=token["CharacterOwnerHash"],
    )
    for scope_name in token["Scopes"].split(" "):
        scope, _ = Scope.objects.get_or_create(name=scope_name)
        obj.scopes.add(scope)

    return obj


def add_new_token(user: User, character: EveCharacter, scopes: list) -> Token:
    """generates a new Token for the given character and adds it to the user"""
    return _store_as_Token(
        _generate_token(
            character_id=character.character_id,
            character_name=character.character_name,
            scopes=scopes,
        ),
        user,
    )


def add_character_to_user(
    user: User,
    character: EveCharacter,
    is_main: bool = False,
    scopes: list = None,
) -> CharacterOwnership:
    if not scopes:
        scopes = "publicData"

    add_new_token(user, character, scopes)

    if is_main:
        user.profile.main_character = character
        user.profile.save()
        user.save()

    return CharacterOwnership.objects.get(user=user, character=character)


def add_character_to_user_2(
    user: User,
    character_id,
    character_name,
    corporation_id,
    corporation_name,
    alliance_id=None,
    alliance_name=None,
    disconnect_signals=False,
) -> EveCharacter:
    defaults = {
        "character_name": str(character_name),
        "corporation_id": int(corporation_id),
        "corporation_name": str(corporation_name),
    }
    if alliance_id:
        defaults["alliance_id"] = int(alliance_id)
        defaults["alliance_name"] = str(alliance_name)

    if disconnect_signals:
        AuthUtils.disconnect_signals()
    character = EveCharacter.objects.update_or_create(
        character_id=character_id, defaults=defaults
    )
    CharacterOwnership.objects.create(
        character=character, owner_hash=f"{character_id}_{character_name}", user=user
    )
    if disconnect_signals:
        AuthUtils.connect_signals()

    return character


def _get_random_string(char_count):
    return "".join(
        random.choice(string.ascii_uppercase + string.digits) for _ in range(char_count)
    )


def get_invalid_object_pk(MyModel) -> int:
    return max(MyModel.objects.values_list("pk", flat=True)) + 1


def queryset_pks(queryset) -> set:
    """shortcut that returns the pks of the given queryset as set.
    Useful for comparing test results.
    """
    return set(queryset.values_list("pk", flat=True))
