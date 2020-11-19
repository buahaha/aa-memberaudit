from unittest.mock import patch

from bravado.exception import HTTPNotFound

from django.core.cache import cache
from django.test import TestCase

from ..core import EsiErrors
from .testdata.esi_test_tools import BravadoResponseStub

MODULE_PATH = "memberaudit.core"


class TestEsiErrors(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.esi_errors = EsiErrors()

    def test_get_1a(self):
        """When there is an error status, then return it"""
        cache.set(key=EsiErrors.ESI_ERRORS_CACHE_KEY, value=50, timeout=50)
        status = self.esi_errors.get()
        self.assertEqual(status.remain, 50)
        self.assertAlmostEqual(status.reset, 50, delta=5)
        self.assertFalse(status.is_exceeded)

    def test_get_1b(self):
        """When there is an error status, then return it (now exceeded)"""
        cache.set(key=EsiErrors.ESI_ERRORS_CACHE_KEY, value=10, timeout=50)
        status = self.esi_errors.get()
        self.assertEqual(status.remain, 10)
        self.assertAlmostEqual(status.reset, 50, delta=5)
        self.assertTrue(status.is_exceeded)

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

    def test_set_1(self):
        """Can set error status"""
        self.esi_errors.set(40, 30)
        status = self.esi_errors.get()
        self.assertEqual(status.remain, 40)
        self.assertAlmostEqual(status.reset, 30, delta=5)

    @patch(MODULE_PATH + ".cache.set")
    def test_set_2(self, mock_cache_set):
        """when setting the cache fails, then do nothing"""
        mock_cache_set.side_effect = RuntimeError
        self.esi_errors.set(40, 30)
        status = self.esi_errors.get()
        self.assertIsNone(status)

    def test_set_from_bravado_exception_1(self):
        """Can set error status from HTTPError type exception
        and also returns result as EsiStatus object
        """
        http_error = HTTPNotFound(
            response=BravadoResponseStub(
                404,
                "Test exception",
                headers={
                    "X-Esi-Error-Limit-Remain": "40",
                    "X-Esi-Error-Limit-Reset": "30",
                },
            )
        )
        status_1 = self.esi_errors.set_from_bravado_exception(http_error)
        status_2 = self.esi_errors.get()
        self.assertEqual(status_1.remain, 40)
        self.assertAlmostEqual(status_1.reset, 30, delta=5)
        self.assertEqual(status_2.remain, 40)
        self.assertAlmostEqual(status_2.reset, 30, delta=5)

    def test_set_from_bravado_exception_2(self):
        """Can handle HTTPError type exception without error headers
        and also returns None
        """
        http_error = HTTPNotFound(response=BravadoResponseStub(404, "Test exception"))
        result = self.esi_errors.set_from_bravado_exception(http_error)
        status = self.esi_errors.get()
        self.assertIsNone(status)
        self.assertIsNone(result)
