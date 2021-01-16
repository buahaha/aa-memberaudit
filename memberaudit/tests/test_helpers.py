from unittest.mock import patch

import requests_mock

from django.contrib.auth.models import Group
from django.test import TestCase


from allianceauth.tests.auth_utils import AuthUtils

from .testdata.load_entities import load_entities
from ..helpers import (
    users_with_permission,
    fetch_esi_status,
    EsiStatus,
    EsiOffline,
    EsiErrorLimitExceeded,
)
from ..utils import NoSocketsTestCase


MODULE_PATH = "memberaudit.helpers"


class TestUsersWithPermissionQS(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_entities()
        cls.permission = AuthUtils.get_permission_by_name("memberaudit.basic_access")
        cls.group, _ = Group.objects.get_or_create(name="Test Group")
        AuthUtils.add_permissions_to_groups([cls.permission], [cls.group])
        cls.state = AuthUtils.create_state(name="Test State", priority=75)
        cls.state.permissions.add(cls.permission)

    def setUp(self) -> None:
        self.user_1 = AuthUtils.create_user("Bruce Wayne")
        self.user_2 = AuthUtils.create_user("Lex Luther")

    @classmethod
    def user_with_permission_pks(cls) -> set:
        return set(users_with_permission(cls.permission).values_list("pk", flat=True))

    def test_user_permission(self):
        """direct user permissions"""
        AuthUtils.add_permissions_to_user([self.permission], self.user_1)
        self.assertSetEqual(self.user_with_permission_pks(), {self.user_1.pk})

    def test_group_permission(self):
        """group permissions"""
        self.user_1.groups.add(self.group)
        self.assertSetEqual(self.user_with_permission_pks(), {self.user_1.pk})

    def test_state_permission(self):
        """state permissions"""
        AuthUtils.assign_state(self.user_1, self.state, disconnect_signals=True)
        self.assertSetEqual(self.user_with_permission_pks(), {self.user_1.pk})

    def test_distinct_qs(self):
        """only return one user object, despiste multiple matches"""
        AuthUtils.add_permissions_to_user([self.permission], self.user_1)
        self.user_1.groups.add(self.group)
        AuthUtils.assign_state(self.user_1, self.state, disconnect_signals=True)
        self.assertSetEqual(self.user_with_permission_pks(), {self.user_1.pk})


class TestEsiStatusExceptions(TestCase):
    def test_offline(self):
        try:
            raise EsiErrorLimitExceeded(45)
        except Exception as ex:
            self.assertIsInstance(ex, EsiErrorLimitExceeded)
            self.assertEqual(ex.retry_in, 45)
            self.assertIn("ESI error limit has been exceeded", ex.message)


class TestEsiStatus(TestCase):
    def test_create_1(self):
        obj = EsiStatus(True)
        self.assertTrue(obj.is_online)
        self.assertIsNone(obj.error_limit_remain)
        self.assertIsNone(obj.error_limit_reset)

    def test_create_2(self):
        obj = EsiStatus(False, 1)
        self.assertFalse(obj.is_online)
        self.assertIsNone(obj.error_limit_remain)
        self.assertIsNone(obj.error_limit_reset)

    def test_create_3(self):
        obj = EsiStatus(True, None, 1)
        self.assertTrue(obj.is_online)
        self.assertIsNone(obj.error_limit_remain)
        self.assertIsNone(obj.error_limit_reset)

    def test_create_4(self):
        obj = EsiStatus(True, 10, 20)
        self.assertTrue(obj.is_online)
        self.assertEqual(obj.error_limit_remain, 10)
        self.assertEqual(obj.error_limit_reset, 20)

    def test_create_5(self):
        obj = EsiStatus(True, "10", "20")
        self.assertTrue(obj.is_online)
        self.assertEqual(obj.error_limit_remain, 10)
        self.assertEqual(obj.error_limit_reset, 20)

    @patch(MODULE_PATH + ".MEMBERAUDIT_ESI_ERROR_LIMIT_THRESHOLD", 25)
    def test_is_error_limit_exceeded_1(self):
        obj = EsiStatus(True, error_limit_remain=30, error_limit_reset=20)
        self.assertFalse(obj.is_error_limit_exceeded)

    @patch(MODULE_PATH + ".MEMBERAUDIT_ESI_ERROR_LIMIT_THRESHOLD", 25)
    def test_is_error_limit_exceeded_2(self):
        obj = EsiStatus(True, error_limit_remain=10, error_limit_reset=20)
        self.assertTrue(obj.is_error_limit_exceeded)

    @patch(MODULE_PATH + ".MEMBERAUDIT_ESI_ERROR_LIMIT_THRESHOLD", 25)
    def test_is_error_limit_exceeded_3(self):
        obj = EsiStatus(True, error_limit_remain=10)
        self.assertFalse(obj.is_error_limit_exceeded)

    @patch(MODULE_PATH + ".EsiStatus.MAX_JITTER", 20)
    def test_error_limit_reset_w_jitter_1(self):
        obj = EsiStatus(True, error_limit_remain=30, error_limit_reset=20)
        result = obj.error_limit_reset_w_jitter()
        for _ in range(1000):
            self.assertGreaterEqual(result, 21)
            self.assertLessEqual(result, 41)

    @patch(MODULE_PATH + ".EsiStatus.MAX_JITTER", 20)
    def test_error_limit_reset_w_jitter_2(self):
        obj = EsiStatus(True, error_limit_remain=30, error_limit_reset=20)
        result = obj.error_limit_reset_w_jitter(10)
        for _ in range(1000):
            self.assertGreaterEqual(result, 11)
            self.assertLessEqual(result, 31)

    def test_raise_for_status_1(self):
        """When no error condition is met, do nothing"""
        obj = EsiStatus(True, error_limit_remain=99, error_limit_reset=20)
        try:
            obj.raise_for_status()
        except Exception:
            self.fail("raise_for_status() raised Exception unexpectedly!")

    @patch(MODULE_PATH + ".MEMBERAUDIT_ESI_ERROR_LIMIT_THRESHOLD", 25)
    def test_raise_for_status_2(self):
        """When ESI is offline, then raise exception"""
        obj = EsiStatus(False, error_limit_remain=99, error_limit_reset=20)
        with self.assertRaises(EsiOffline):
            obj.raise_for_status()

    @patch(MODULE_PATH + ".MEMBERAUDIT_ESI_ERROR_LIMIT_THRESHOLD", 25)
    def test_raise_for_status_3(self):
        """When ESI error limit is exceeded, then raise exception"""
        obj = EsiStatus(True, error_limit_remain=15, error_limit_reset=20)
        with self.assertRaises(EsiErrorLimitExceeded):
            obj.raise_for_status()


@requests_mock.Mocker()
class TestFetchEsiStatus(TestCase):
    def test_normal(self, requests_mocker):
        """When ESI is online and header is complete, then report status accordingly"""
        requests_mocker.register_uri(
            "GET",
            url="https://esi.evetech.net/latest/status/",
            headers={
                "X-Esi-Error-Limit-Remain": "40",
                "X-Esi-Error-Limit-Reset": "30",
            },
            json={
                "players": 12345,
                "server_version": "1132976",
                "start_time": "2017-01-02T12:34:56Z",
            },
        )
        status = fetch_esi_status()
        self.assertTrue(status.is_online)
        self.assertEqual(status.error_limit_remain, 40)
        self.assertEqual(status.error_limit_reset, 30)

    def test_esi_offline(self, requests_mocker):
        """When ESI is offline and header is complete, then report status accordingly"""
        requests_mocker.register_uri(
            "GET",
            url="https://esi.evetech.net/latest/status/",
            headers={
                "X-Esi-Error-Limit-Remain": "40",
                "X-Esi-Error-Limit-Reset": "30",
            },
            status_code=404,  # HTTPNotFound
        )
        status = fetch_esi_status()
        self.assertFalse(status.is_online)
        self.assertEqual(status.error_limit_remain, 40)
        self.assertEqual(status.error_limit_reset, 30)

    def test_esi_vip(self, requests_mocker):
        """When ESI is offline and header is complete, then report status accordingly"""
        requests_mocker.register_uri(
            "GET",
            url="https://esi.evetech.net/latest/status/",
            headers={
                "X-Esi-Error-Limit-Remain": "40",
                "X-Esi-Error-Limit-Reset": "30",
            },
            json={
                "vip": True,
                "players": 12345,
                "server_version": "1132976",
                "start_time": "2017-01-02T12:34:56Z",
            },
        )
        status = fetch_esi_status()
        self.assertFalse(status.is_online)
        self.assertEqual(status.error_limit_remain, 40)
        self.assertEqual(status.error_limit_reset, 30)

    def test_esi_invalid_json(self, requests_mocker):
        """When ESI response JSON can not be parse, then report as offline"""
        requests_mocker.register_uri(
            "GET",
            url="https://esi.evetech.net/latest/status/",
            headers={
                "X-Esi-Error-Limit-Remain": "40",
                "X-Esi-Error-Limit-Reset": "30",
            },
            text="this is not json",
        )
        status = fetch_esi_status()
        self.assertFalse(status.is_online)
        self.assertEqual(status.error_limit_remain, 40)
        self.assertEqual(status.error_limit_reset, 30)

    def test_headers_missing(self, requests_mocker):
        """When header is incomplete, then report error limits with None"""
        requests_mocker.register_uri(
            "GET",
            url="https://esi.evetech.net/latest/status/",
            headers={
                "X-Esi-Error-Limit-Remain": "40",
            },
            json={
                "players": 12345,
                "server_version": "1132976",
                "start_time": "2017-01-02T12:34:56Z",
            },
        )
        status = fetch_esi_status()
        self.assertTrue(status.is_online)
        self.assertIsNone(status.error_limit_remain)
        self.assertIsNone(status.error_limit_reset)

    @patch(MODULE_PATH + ".sleep", lambda x: None)
    def test_retry_on_specific_http_errors_1(self, requests_mocker):
        """When specific HTTP code occurred, then retry until HTTP OK is received"""

        counter = 0

        def response_callback(request, context) -> str:
            nonlocal counter
            counter += 1
            if counter == 2:
                context.status_code = 200
                return {
                    "players": 12345,
                    "server_version": "1132976",
                    "start_time": "2017-01-02T12:34:56Z",
                }
            else:
                context.status_code = 504
                return "[]"

        requests_mocker.register_uri(
            "GET",
            url="https://esi.evetech.net/latest/status/",
            headers={
                "X-Esi-Error-Limit-Remain": "40",
                "X-Esi-Error-Limit-Reset": "30",
            },
            json=response_callback,
        )
        fetch_esi_status()
        self.assertEqual(requests_mocker.call_count, 2)

    @patch(MODULE_PATH + ".sleep", lambda x: None)
    def test_retry_on_specific_http_errors_2(self, requests_mocker):
        """When specific HTTP code occurred, then retry up to maximum retries"""
        requests_mocker.register_uri(
            "GET",
            url="https://esi.evetech.net/latest/status/",
            headers={
                "X-Esi-Error-Limit-Remain": "40",
                "X-Esi-Error-Limit-Reset": "30",
            },
            status_code=504,
        )
        status = fetch_esi_status()
        self.assertEqual(requests_mocker.call_count, 4)
        self.assertFalse(status.is_online)

    @patch(MODULE_PATH + ".sleep", lambda x: None)
    def test_retry_on_specific_http_errors_3(self, requests_mocker):
        """When specific HTTP code occurred, then retry up to maximum retries"""
        requests_mocker.register_uri(
            "GET",
            url="https://esi.evetech.net/latest/status/",
            headers={
                "X-Esi-Error-Limit-Remain": "40",
                "X-Esi-Error-Limit-Reset": "30",
            },
            status_code=502,
        )
        status = fetch_esi_status()
        self.assertEqual(requests_mocker.call_count, 4)
        self.assertFalse(status.is_online)

    @patch(MODULE_PATH + ".sleep", lambda x: None)
    def test_retry_on_specific_http_errors_4(self, requests_mocker):
        """Do not repeat on other HTTP errors"""
        requests_mocker.register_uri(
            "GET",
            url="https://esi.evetech.net/latest/status/",
            headers={
                "X-Esi-Error-Limit-Remain": "40",
                "X-Esi-Error-Limit-Reset": "30",
            },
            status_code=404,
        )
        status = fetch_esi_status()
        self.assertEqual(requests_mocker.call_count, 1)
        self.assertFalse(status.is_online)
