from unittest.mock import Mock, patch


from allianceauth.eveonline.evelinks import dotlan, evewho


from django.test import TestCase

from .testdata.esi_client_stub import load_test_data
from ..helpers import eve_xml_to_html


class TestHTMLConversion(TestCase):
    def test_convert_eve_xml_alliance(self):
        """can convert an alliance link in CCP XML to HTML"""
        with patch(
            "eveuniverse.models.EveEntity.objects.resolve_name",
            Mock(return_value="An Alliance"),
        ):
            result = eve_xml_to_html(
                load_test_data()
                .get("Mail")
                .get("get_characters_character_id_mail_mail_id")
                .get("2")
                .get("body")
            )
            self.assertTrue(result.find(dotlan.alliance_url("An Alliance")) != -1)

    def test_convert_eve_xml_character(self):
        """can convert a character link in CCP XML to HTML"""
        result = eve_xml_to_html(
            load_test_data()
            .get("Mail")
            .get("get_characters_character_id_mail_mail_id")
            .get("2")
            .get("body")
        )
        self.assertTrue(result.find(evewho.character_url(1001)) != -1)

    def test_convert_eve_xml_corporation(self):
        """can convert a corporation link in CCP XML to HTML"""
        with patch(
            "eveuniverse.models.EveEntity.objects.resolve_name",
            Mock(return_value="A Corporation"),
        ):
            result = eve_xml_to_html(
                load_test_data()
                .get("Mail")
                .get("get_characters_character_id_mail_mail_id")
                .get("2")
                .get("body")
            )
            self.assertTrue(result.find(dotlan.alliance_url("A Corporation")) != -1)

    def test_convert_eve_xml_solar_system(self):
        """can convert a solar system link in CCP XML to HTML"""
        with patch(
            "eveuniverse.models.EveEntity.objects.resolve_name",
            Mock(return_value="Polaris"),
        ):
            result = eve_xml_to_html(
                load_test_data()
                .get("Mail")
                .get("get_characters_character_id_mail_mail_id")
                .get("2")
                .get("body")
            )
            self.assertTrue(result.find(dotlan.solar_system_url("Polaris")) != -1)
