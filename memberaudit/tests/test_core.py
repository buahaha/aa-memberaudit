import datetime as dt
from email.utils import format_datetime
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils.timezone import now

from ..core import EsiErrorManager, EsiErrorStatus

MODULE_PATH = "memberaudit.core"


@patch(MODULE_PATH + ".ESI_ERROR_LIMIT", 25)
class TestEsiErrorStatus(TestCase):
    def test_create_1(self):
        until = now() + dt.timedelta(seconds=30)
        obj = EsiErrorStatus(remain=80, until=until)
        self.assertEqual(obj.remain, 80)
        self.assertAlmostEqual(obj.reset, 30, delta=1)
        self.assertGreaterEqual(obj.until, until)
        self.assertFalse(obj.is_exceeded)
        self.assertTrue(obj.is_valid)

    def test_create_2(self):
        until = now() + dt.timedelta(seconds=30)
        obj = EsiErrorStatus(remain="20", until=until)
        self.assertEqual(obj.remain, 20)
        self.assertAlmostEqual(obj.reset, 30, delta=1)
        self.assertGreaterEqual(obj.until, until)
        self.assertTrue(obj.is_exceeded)
        self.assertTrue(obj.is_valid)

    def test_str(self):
        until = dt.datetime(2020, 11, 20, 19, 15)
        obj = EsiErrorStatus(remain=80, until=until)

        self.assertEqual(
            str(obj), "ESI error status: remain = 80, until = '2020-11-20T19:15:00'"
        )

    def test_is_not_valid(self):
        until = now() - dt.timedelta(seconds=5)
        obj = EsiErrorStatus(remain=80, until=until)
        self.assertFalse(obj.is_valid)

    def test_create_wrong_type_until(self):
        with self.assertRaises(TypeError):
            EsiErrorStatus(remain="80", until="str")

    def test_json_serialization(self):
        until = now() + dt.timedelta(seconds=30)

        obj_1 = EsiErrorStatus(remain=80, until=until)
        obj_2 = EsiErrorStatus.from_json(obj_1.asjson())

        self.assertEqual(obj_1.remain, obj_2.remain)
        self.assertEqual(obj_1.until, obj_2.until)

    def test_from_json_2(self):
        with self.assertRaises(ValueError):
            EsiErrorStatus.from_json("")

    def test_from_headers_1(self):
        obj = EsiErrorStatus.from_headers(
            {
                "X-Esi-Error-Limit-Remain": "40",
                "X-Esi-Error-Limit-Reset": "30",
                "Date": format_datetime(now()),
            }
        )
        self.assertEqual(obj.remain, 40)
        self.assertAlmostEqual(obj.reset, 30, delta=2)

    def test_from_headers_2(self):
        """when Date header is missing, then use current time"""
        obj = EsiErrorStatus.from_headers(
            {
                "X-Esi-Error-Limit-Remain": "40",
                "X-Esi-Error-Limit-Reset": "30",
            }
        )
        self.assertEqual(obj.remain, 40)
        self.assertAlmostEqual(obj.reset, 30, delta=2)

    def test_from_headers_3(self):
        """when error headers are missing, then through exception"""
        with self.assertRaises(TypeError):
            EsiErrorStatus.from_headers(dict())


class TestEsiErrorManager(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.esi_errors = EsiErrorManager()

    def test_get_1(self):
        """When there is an error status, then return it"""
        until = now() + dt.timedelta(seconds=30)
        error_status = EsiErrorStatus(remain=50, until=until)
        cache.set(
            key=EsiErrorManager.ESI_ERRORS_CACHE_KEY,
            value=error_status.asjson(),
            timeout=50,
        )
        status = self.esi_errors.get()
        self.assertEqual(status.remain, 50)
        self.assertAlmostEqual(status.reset, 30, delta=2)

    def test_get_2(self):
        """When there is no error status, then return None"""
        status = self.esi_errors.get()
        self.assertIsNone(status)

    @patch(MODULE_PATH + ".cache.get")
    def test_get_3(self, mock_cache_get):
        """When fetching from cache fails, then return None"""
        mock_cache_get.side_effect = RuntimeError
        status = self.esi_errors.get()
        self.assertIsNone(status)

    def test_set_normal_1(self):
        """Can set error status"""
        status, is_updated = self.esi_errors.update(
            {
                "X-Esi-Error-Limit-Remain": "40",
                "X-Esi-Error-Limit-Reset": "30",
                "Date": format_datetime(now()),
            }
        )
        self.assertTrue(is_updated)
        self.assertEqual(status.remain, 40)
        self.assertAlmostEqual(status.reset, 30, delta=2)
        status_2 = self.esi_errors.get()
        self.assertEqual(status.remain, status_2.remain)
        self.assertEqual(status.until, status_2.until)

    @patch(MODULE_PATH + ".cache.set")
    def test_set_errors_1(self, mock_cache_set):
        """when updating cache fails, then return None"""
        mock_cache_set.side_effect = RuntimeError
        status, is_updated = self.esi_errors.update(
            {
                "X-Esi-Error-Limit-Remain": "40",
                "X-Esi-Error-Limit-Reset": "30",
                "Date": format_datetime(now()),
            }
        )
        self.assertIsNone(status)
        self.assertFalse(is_updated)

    def test_set_errors_3(self):
        """when headers are missing, then return None"""
        status, is_updated = self.esi_errors.update(dict())
        self.assertIsNone(status)
        self.assertFalse(is_updated)

    def test_set_normal_2(self):
        """
        when incoming esi error is for next window
        then make update
        """
        current_time = now()
        window_1 = current_time + dt.timedelta(seconds=30)
        window_2 = current_time + dt.timedelta(seconds=90)
        status, is_updated = self.esi_errors.update(
            {
                "X-Esi-Error-Limit-Remain": "30",
                "X-Esi-Error-Limit-Reset": "30",
                "Date": format_datetime(window_1),
            }
        )
        self.assertEqual(status.remain, 30)
        self.assertTrue(is_updated)

        status, is_updated = self.esi_errors.update(
            {
                "X-Esi-Error-Limit-Remain": "99",
                "X-Esi-Error-Limit-Reset": "90",
                "Date": format_datetime(window_2),
            }
        )
        self.assertEqual(status.remain, 99)
        self.assertTrue(is_updated)

    def test_set_normal_4(self):
        """when incoming esi error is for previous window, then ignore it"""
        current_time = now()
        window_1 = current_time + dt.timedelta(seconds=30)
        window_2 = current_time + dt.timedelta(seconds=90)
        status, is_updated = self.esi_errors.update(
            {
                "X-Esi-Error-Limit-Remain": "99",
                "X-Esi-Error-Limit-Reset": "90",
                "Date": format_datetime(window_2),
            }
        )
        self.assertEqual(status.remain, 99)
        self.assertTrue(is_updated)

        status, is_updated = self.esi_errors.update(
            {
                "X-Esi-Error-Limit-Remain": "30",
                "X-Esi-Error-Limit-Reset": "30",
                "Date": format_datetime(window_1),
            }
        )
        self.assertEqual(status.remain, 99)
        self.assertFalse(is_updated)

    def test_set_normal_5(self):
        """
        when incoming esi error is for current window, and shows higher remain
        then ignore it
        """
        current_time = now()
        window_1 = current_time + dt.timedelta(seconds=30)
        status, is_updated = self.esi_errors.update(
            {
                "X-Esi-Error-Limit-Remain": "30",
                "X-Esi-Error-Limit-Reset": "30",
                "Date": format_datetime(window_1),
            }
        )
        self.assertEqual(status.remain, 30)
        self.assertTrue(is_updated)

        status, is_updated = self.esi_errors.update(
            {
                "X-Esi-Error-Limit-Remain": "31",
                "X-Esi-Error-Limit-Reset": "30",
                "Date": format_datetime(window_1),
            }
        )
        self.assertEqual(status.remain, 30)
        self.assertFalse(is_updated)

    def test_set_normal_6(self):
        """
        when incoming esi error has a deviation for up to 5 secs
        then recognize it as same window
        """
