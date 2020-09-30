import inspect
import json
import os

from .esi_test_tools import EsiClientStub, EsiEndpoint

_currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
_FILENAME_ESI_TESTDATA = "esi_testdata.json"


def _load_test_data():
    with open(f"{_currentdir}/{_FILENAME_ESI_TESTDATA}", "r", encoding="utf-8") as f:
        return json.load(f)


esi_client_stub = EsiClientStub(
    _load_test_data(),
    [
        EsiEndpoint(
            "Character",
            "get_characters_character_id_corporationhistory",
            "character_id",
        ),
        EsiEndpoint(
            "Character",
            "get_characters_character_id",
            "character_id",
        ),
        EsiEndpoint(
            "Location",
            "get_characters_character_id_location",
            "character_id",
            needs_token=True,
        ),
        EsiEndpoint(
            "Mail", "get_characters_character_id_mail", "character_id", needs_token=True
        ),
        EsiEndpoint(
            "Mail",
            "get_characters_character_id_mail_lists",
            "character_id",
            needs_token=True,
        ),
        EsiEndpoint(
            "Mail",
            "get_characters_character_id_mail_mail_id",
            "mail_id",
            needs_token=True,
        ),
        EsiEndpoint(
            "Skills",
            "get_characters_character_id_skills",
            "character_id",
            needs_token=True,
        ),
        EsiEndpoint(
            "Wallet",
            "get_characters_character_id_wallet",
            "character_id",
            needs_token=True,
        ),
        EsiEndpoint(
            "Wallet",
            "get_characters_character_id_wallet_journal",
            "character_id",
            needs_token=True,
        ),
    ],
)
