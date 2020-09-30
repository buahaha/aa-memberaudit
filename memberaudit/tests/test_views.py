import json
from unittest.mock import patch, Mock

from bravado.exception import HTTPNotFound

from django.http import JsonResponse
from django.test import TestCase, RequestFactory
from django.utils.timezone import now
from django.urls import reverse

from eveuniverse.models import EveSolarSystem, EveType, EveEntity

from .testdata.load_eveuniverse import load_eveuniverse
from .testdata.load_entities import load_entities

from . import create_memberaudit_character
from ..models import Skill, WalletJournalEntry, Mail, MailRecipient, MailingList
from ..views import (
    launcher,
    character_main,
    character_location_data,
    character_mail_headers_data,
    character_mail_data,
    character_skills_data,
    character_wallet_journal_data,
)

MODULE_PATH = "memberaudit.views"


def json_response_to_python(response: JsonResponse) -> object:
    return json.loads(response.content.decode("utf-8"))


class TestViews(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.factory = RequestFactory()
        load_eveuniverse()
        load_entities()
        cls.character = create_memberaudit_character(1001)
        cls.user = cls.character.character_ownership.user

    def test_can_open_launcher_view(self):
        request = self.factory.get(reverse("memberaudit:launcher"))
        request.user = self.user
        response = launcher(request)
        self.assertEqual(response.status_code, 200)

    def test_can_open_character_main_view(self):
        request = self.factory.get(
            reverse("memberaudit:character_main", args=[self.character.pk])
        )
        request.user = self.user
        response = character_main(request, self.character.pk)
        self.assertEqual(response.status_code, 200)

    def test_character_skills_data(self):
        Skill.objects.create(
            character=self.character,
            eve_type=EveType.objects.get(id=24311),
            active_skill_level=1,
            skillpoints_in_skill=1000,
            trained_skill_level=1,
        )
        request = self.factory.get(
            reverse("memberaudit:character_skills_data", args=[self.character.pk])
        )
        request.user = self.user
        response = character_skills_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["group"], "Spaceship Command")
        self.assertEqual(row["skill"], "Amarr Carrier")
        self.assertEqual(row["level"], 1)

    def test_character_wallet_journal_data(self):
        WalletJournalEntry.objects.create(
            character=self.character,
            entry_id=1,
            amount=1000000,
            balance=10000000,
            context_id_type=WalletJournalEntry.CONTEXT_ID_TYPE_UNDEFINED,
            date=now(),
            description="dummy",
            first_party=EveEntity.objects.get(id=1001),
            second_party=EveEntity.objects.get(id=1002),
        )
        request = self.factory.get(
            reverse(
                "memberaudit:character_wallet_journal_data", args=[self.character.pk]
            )
        )
        request.user = self.user
        response = character_wallet_journal_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["amount"], "1000000.00")
        self.assertEqual(row["balance"], "10000000.00")

    def test_character_mail_headers_data(self):
        mailing_list = MailingList.objects.create(
            character=self.character, list_id=5, name="Mailing List"
        )
        mail = Mail.objects.create(
            character=self.character,
            mail_id=99,
            from_entity=EveEntity.objects.get(id=1002),
            subject="Dummy",
            body="This is the body",
            timestamp=now(),
        )
        MailRecipient.objects.create(
            mail=mail, eve_entity=EveEntity.objects.get(id=1001)
        )
        MailRecipient.objects.create(mail=mail, mailing_list=mailing_list)
        request = self.factory.get(
            reverse("memberaudit:character_mail_headers_data", args=[self.character.pk])
        )
        request.user = self.user
        response = character_mail_headers_data(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["mail_id"], 99)
        self.assertEqual(row["from"], "Clark Kent")
        self.assertEqual(row["to"], "Bruce Wayne, Mailing List")

    def test_character_mail_data(self):
        mailing_list = MailingList.objects.create(
            character=self.character, list_id=5, name="Mailing List"
        )
        mail = Mail.objects.create(
            character=self.character,
            mail_id=99,
            from_entity=EveEntity.objects.get(id=1002),
            subject="Dummy",
            body="This is the body",
            timestamp=now(),
        )
        MailRecipient.objects.create(
            mail=mail, eve_entity=EveEntity.objects.get(id=1001)
        )
        MailRecipient.objects.create(mail=mail, mailing_list=mailing_list)
        request = self.factory.get(
            reverse(
                "memberaudit:character_mail_data", args=[self.character.pk, mail.pk]
            )
        )
        request.user = self.user
        response = character_mail_data(request, self.character.pk, mail.pk)
        self.assertEqual(response.status_code, 200)
        data = json_response_to_python(response)
        self.assertEqual(data["mail_id"], 99)
        self.assertEqual(data["from"], "Clark Kent")
        self.assertEqual(data["to"], "Bruce Wayne, Mailing List")
        self.assertEqual(data["body"], "This is the body")


@patch(MODULE_PATH + ".Character.fetch_location")
class TestCharacterLocationData(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.factory = RequestFactory()
        load_eveuniverse()
        load_entities()
        cls.character = create_memberaudit_character(1001)
        cls.user = cls.character.character_ownership.user
        cls.abune = EveSolarSystem.objects.get(id=30004984)

    def test_normal(self, mock_fetch_location):
        mock_fetch_location.return_value = (self.abune, None)

        request = self.factory.get(
            reverse("memberaudit:character_location_data", args=[self.character.pk])
        )
        request.user = self.user
        orig_view = character_location_data.__wrapped__
        response = orig_view(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Abune", response.content.decode("utf8"))

    def test_http_error(self, mock_fetch_location):
        mock_fetch_location.side_effect = HTTPNotFound(
            Mock(**{"response.status_code": 404})
        )

        request = self.factory.get(
            reverse("memberaudit:character_location_data", args=[self.character.pk])
        )
        request.user = self.user
        orig_view = character_location_data.__wrapped__
        response = orig_view(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Network error", response.content.decode("utf8"))

    def test_unexpected_error(self, mock_fetch_location):
        mock_fetch_location.side_effect = RuntimeError

        request = self.factory.get(
            reverse("memberaudit:character_location_data", args=[self.character.pk])
        )
        request.user = self.user
        orig_view = character_location_data.__wrapped__
        response = orig_view(request, self.character.pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Unexpected error", response.content.decode("utf8"))
