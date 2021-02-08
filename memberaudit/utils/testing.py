import datetime as dt
import logging
import os
import socket

from django.db import models
from django.test import TestCase

from django.contrib.auth.models import User

from esi.models import Scope, Token

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter
from allianceauth.tests.auth_utils import AuthUtils

from .datetime import dt_eveformat
from .helpers import random_string


def generate_invalid_pk(MyModel: models.Model) -> int:
    """return an invalid PK for the given Django model"""
    pk_max = MyModel.objects.aggregate(models.Max("pk"))["pk__max"]
    return pk_max + 1 if pk_max else 1


class SocketAccessError(Exception):
    """Error raised when a test script accesses the network"""


class NoSocketsTestCase(TestCase):
    """Variation of Django's TestCase class that prevents any network use."""

    @classmethod
    def setUpClass(cls):
        cls.socket_original = socket.socket
        socket.socket = cls.guard
        return super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        socket.socket = cls.socket_original
        return super().tearDownClass()

    @staticmethod
    def guard(*args, **kwargs):
        raise SocketAccessError("Attempted to access network")


def set_test_logger(logger_name: str, name: str) -> object:
    """set logger for current test module

    Args:
    - logger: current logger object
    - name: name of current module, e.g. __file__

    Returns:
    - amended logger
    """

    # reconfigure logger so we get logging from tested module
    f_format = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(module)s:%(funcName)s - %(message)s"
    )
    f_handler = logging.FileHandler("{}.log".format(os.path.splitext(name)[0]), "w+")
    f_handler.setFormatter(f_format)
    my_logger = logging.getLogger(logger_name)
    my_logger.level = logging.DEBUG
    my_logger.addHandler(f_handler)
    my_logger.propagate = False
    return my_logger


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
    """Generates a token for the given Eve character and makes the given user it's owner"""
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
    """Creates a new EVE character and makes the given user the owner"""
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


def _generate_token(
    character_id: int,
    character_name: str,
    access_token: str = "access_token",
    refresh_token: str = "refresh_token",
    scopes: list = None,
    timestamp_dt: object = None,
    expires_in: int = 1200,
) -> dict:
    """Generates the input to create a new SSO test token"""
    if timestamp_dt is None:
        timestamp_dt = dt.datetime.utcnow()
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
        "ExpiresOn": dt_eveformat(timestamp_dt + dt.timedelta(seconds=expires_in)),
        "Scopes": " ".join(list(scopes)),
        "TokenType": "Character",
        "CharacterOwnerHash": random_string(28),
        "IntellectualProperty": "EVE",
    }
    return token


def _store_as_Token(token: dict, user: object) -> Token:
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


def queryset_pks(queryset) -> set:
    """shortcut that returns the pks of the given queryset as set.
    Useful for comparing test results.
    """
    return set(queryset.values_list("pk", flat=True))


class BravadoResponseStub:
    """Stub for IncomingResponse in bravado, e.g. for HTTPError exceptions"""

    def __init__(
        self, status_code, reason="", text="", headers=None, raw_bytes=None
    ) -> None:
        self.reason = reason
        self.status_code = status_code
        self.text = text
        self.headers = headers if headers else dict()
        self.raw_bytes = raw_bytes

    def __str__(self):
        return "{0} {1}".format(self.status_code, self.reason)


class BravadoOperationStub:
    """Stub to simulate the operation object return from bravado via django-esi"""

    class RequestConfig:
        def __init__(self, also_return_response):
            self.also_return_response = also_return_response

    class ResponseStub:
        def __init__(self, headers):
            self.headers = headers

    def __init__(self, data, headers: dict = None, also_return_response: bool = False):
        self._data = data
        self._headers = headers if headers else {"x-pages": 1}
        self.request_config = BravadoOperationStub.RequestConfig(also_return_response)

    def result(self, **kwargs):
        if self.request_config.also_return_response:
            return [self._data, self.ResponseStub(self._headers)]
        else:
            return self._data

    def results(self, **kwargs):
        return self.result(**kwargs)
