import datetime as dt
import json
from unittest.mock import Mock, patch

import requests

from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import HttpRequest
from django.test import TestCase
from django.utils import translation
from django.utils.html import mark_safe
from django.utils.timezone import now

from ..utils import (
    clean_setting,
    messages_plus,
    chunks,
    timeuntil_str,
    NoSocketsTestCase,
    SocketAccessError,
    app_labels,
    add_no_wrap_html,
    yesno_str,
    create_bs_button_html,
    create_bs_glyph_html,
    create_link_html,
    add_bs_label_html,
    get_site_base_url,
    JSONDateTimeDecoder,
    JSONDateTimeEncoder,
    generate_invalid_pk,
    datetime_round_hour,
    humanize_value,
    ObjectCacheMixin,
)
from ..utils import set_test_logger

_this_package = __package__.partition(".")[0]
MODULE_PATH = "{}.utils".format(_this_package)
CURRENT_PATH = "{}.tests.test_utils".format(_this_package)
logger = set_test_logger(MODULE_PATH, __file__)


class TestMessagePlus(TestCase):
    @patch(MODULE_PATH + ".messages", spec=True)
    def test_valid_call(self, mock_messages):
        messages_plus.debug(Mock(spec=HttpRequest), "Test Message")
        self.assertTrue(mock_messages.debug.called)
        call_args_list = mock_messages.debug.call_args_list
        args, kwargs = call_args_list[0]
        self.assertEqual(
            args[1],
            '<span class="glyphicon glyphicon-eye-open" '
            'aria-hidden="true"></span>&nbsp;&nbsp;'
            "Test Message",
        )

    def test_invalid_level(self):
        with self.assertRaises(ValueError):
            messages_plus._add_messages_icon(987, "Test Message")

    @patch(MODULE_PATH + ".messages")
    def test_all_levels(self, mock_messages):
        text = "Test Message"
        messages_plus.error(Mock(spec=HttpRequest), text)
        self.assertTrue(mock_messages.error.called)

        messages_plus.debug(Mock(spec=HttpRequest), text)
        self.assertTrue(mock_messages.debug.called)

        messages_plus.info(Mock(spec=HttpRequest), text)
        self.assertTrue(mock_messages.info.called)

        messages_plus.success(Mock(spec=HttpRequest), text)
        self.assertTrue(mock_messages.success.called)

        messages_plus.warning(Mock(spec=HttpRequest), text)
        self.assertTrue(mock_messages.warning.called)


class TestChunks(TestCase):
    def test_chunks(self):
        a0 = [1, 2, 3, 4, 5, 6]
        a1 = list(chunks(a0, 2))
        self.assertListEqual(a1, [[1, 2], [3, 4], [5, 6]])


class TestCleanSetting(TestCase):
    @patch(MODULE_PATH + ".settings")
    def test_default_if_not_set(self, mock_settings):
        mock_settings.TEST_SETTING_DUMMY = Mock(spec=None)
        result = clean_setting(
            "TEST_SETTING_DUMMY",
            False,
        )
        self.assertEqual(result, False)

    @patch(MODULE_PATH + ".settings")
    def test_default_if_not_set_for_none(self, mock_settings):
        mock_settings.TEST_SETTING_DUMMY = Mock(spec=None)
        result = clean_setting("TEST_SETTING_DUMMY", None, required_type=int)
        self.assertEqual(result, None)

    @patch(MODULE_PATH + ".settings")
    def test_true_stays_true(self, mock_settings):
        mock_settings.TEST_SETTING_DUMMY = True
        result = clean_setting(
            "TEST_SETTING_DUMMY",
            False,
        )
        self.assertEqual(result, True)

    @patch(MODULE_PATH + ".settings")
    def test_false_stays_false(self, mock_settings):
        mock_settings.TEST_SETTING_DUMMY = False
        result = clean_setting("TEST_SETTING_DUMMY", False)
        self.assertEqual(result, False)

    @patch(MODULE_PATH + ".settings")
    def test_default_for_invalid_type_bool(self, mock_settings):
        mock_settings.TEST_SETTING_DUMMY = "invalid type"
        result = clean_setting("TEST_SETTING_DUMMY", False)
        self.assertEqual(result, False)

    @patch(MODULE_PATH + ".settings")
    def test_default_for_invalid_type_int(self, mock_settings):
        mock_settings.TEST_SETTING_DUMMY = "invalid type"
        result = clean_setting("TEST_SETTING_DUMMY", 50)
        self.assertEqual(result, 50)

    @patch(MODULE_PATH + ".settings")
    def test_none_allowed_for_type_int(self, mock_settings):
        mock_settings.TEST_SETTING_DUMMY = None
        result = clean_setting("TEST_SETTING_DUMMY", 50)
        self.assertIsNone(result)

    @patch(MODULE_PATH + ".settings")
    def test_default_if_below_minimum_1(self, mock_settings):
        """when setting is below minimum and default is > minium, then use minimum"""
        mock_settings.TEST_SETTING_DUMMY = -5
        result = clean_setting("TEST_SETTING_DUMMY", default_value=50)
        self.assertEqual(result, 0)

    @patch(MODULE_PATH + ".settings")
    def test_default_if_below_minimum_2(self, mock_settings):
        """when setting is below minimum, then use minimum"""
        mock_settings.TEST_SETTING_DUMMY = -50
        result = clean_setting("TEST_SETTING_DUMMY", default_value=50, min_value=-10)
        self.assertEqual(result, -10)

    @patch(MODULE_PATH + ".settings")
    def test_default_if_below_minimum_3(self, mock_settings):
        """when default is None and setting is below minimum, then use minimum"""
        mock_settings.TEST_SETTING_DUMMY = 10
        result = clean_setting(
            "TEST_SETTING_DUMMY", default_value=None, required_type=int, min_value=30
        )
        self.assertEqual(result, 30)

    @patch(MODULE_PATH + ".settings")
    def test_setting_if_above_maximum(self, mock_settings):
        """when setting is above maximum, then use maximum"""
        mock_settings.TEST_SETTING_DUMMY = 100
        result = clean_setting("TEST_SETTING_DUMMY", default_value=10, max_value=50)
        self.assertEqual(result, 50)

    @patch(MODULE_PATH + ".settings")
    def test_default_below_minimum(self, mock_settings):
        """when default is below minimum, then raise exception"""
        mock_settings.TEST_SETTING_DUMMY = 10
        with self.assertRaises(ValueError):
            clean_setting("TEST_SETTING_DUMMY", default_value=10, min_value=50)

    @patch(MODULE_PATH + ".settings")
    def test_default_above_maximum(self, mock_settings):
        """when default is below minimum, then raise exception"""
        mock_settings.TEST_SETTING_DUMMY = 10
        with self.assertRaises(ValueError):
            clean_setting("TEST_SETTING_DUMMY", default_value=100, max_value=50)

    @patch(MODULE_PATH + ".settings")
    def test_default_is_none_needs_required_type(self, mock_settings):
        mock_settings.TEST_SETTING_DUMMY = "invalid type"
        with self.assertRaises(ValueError):
            clean_setting("TEST_SETTING_DUMMY", default_value=None)

    @patch(MODULE_PATH + ".settings")
    def test_when_value_in_choices_return_it(self, mock_settings):
        mock_settings.TEST_SETTING_DUMMY = "bravo"
        result = clean_setting(
            "TEST_SETTING_DUMMY", default_value="alpha", choices=["alpha", "bravo"]
        )
        self.assertEqual(result, "bravo")

    @patch(MODULE_PATH + ".settings")
    def test_when_value_not_in_choices_return_default(self, mock_settings):
        mock_settings.TEST_SETTING_DUMMY = "charlie"
        result = clean_setting(
            "TEST_SETTING_DUMMY", default_value="alpha", choices=["alpha", "bravo"]
        )
        self.assertEqual(result, "alpha")


class TestTimeUntil(TestCase):
    def test_timeuntil(self):
        duration = dt.timedelta(days=365 + 30 * 4 + 5, seconds=3600 * 14 + 60 * 33 + 10)
        expected = "1y 4mt 5d 14h 33m 10s"
        self.assertEqual(timeuntil_str(duration), expected)

        duration = dt.timedelta(days=2, seconds=3600 * 14 + 60 * 33 + 10)
        expected = "2d 14h 33m 10s"
        self.assertEqual(timeuntil_str(duration), expected)

        duration = dt.timedelta(days=2, seconds=3600 * 14 + 60 * 33 + 10)
        expected = "2d 14h 33m 10s"
        self.assertEqual(timeuntil_str(duration), expected)

        duration = dt.timedelta(days=0, seconds=60 * 33 + 10)
        expected = "0h 33m 10s"
        self.assertEqual(timeuntil_str(duration), expected)

        duration = dt.timedelta(days=0, seconds=10)
        expected = "0h 0m 10s"
        self.assertEqual(timeuntil_str(duration), expected)

        duration = dt.timedelta(days=-10, seconds=-20)
        expected = ""
        self.assertEqual(timeuntil_str(duration), expected)


class TestNoSocketsTestCase(NoSocketsTestCase):
    def test_raises_exception_on_attempted_network_access(self):

        with self.assertRaises(SocketAccessError):
            requests.get("https://www.google.com")


class TestAppLabel(TestCase):
    def test_returns_set_of_app_labels(self):
        labels = app_labels()
        for label in ["authentication", "groupmanagement", "eveonline"]:
            self.assertIn(label, labels)


class TestHtmlHelper(TestCase):
    def test_add_no_wrap_html(self):
        expected = '<span style="white-space: nowrap;">Dummy</span>'
        self.assertEqual(add_no_wrap_html("Dummy"), expected)

    def test_yesno_str(self):
        with translation.override("en"):
            self.assertEqual(yesno_str(True), "yes")
            self.assertEqual(yesno_str(False), "no")
            self.assertEqual(yesno_str(None), "no")
            self.assertEqual(yesno_str(123), "no")
            self.assertEqual(yesno_str("xxxx"), "no")

    def test_add_bs_label_html(self):
        expected = '<div class="label label-danger">Dummy</div>'
        self.assertEqual(add_bs_label_html("Dummy", "danger"), expected)

    def test_create_link_html_default(self):
        expected = (
            '<a href="https://www.example.com" target="_blank">' "Example Link</a>"
        )
        self.assertEqual(
            create_link_html("https://www.example.com", "Example Link"), expected
        )

    def test_create_link_html(self):
        expected = '<a href="https://www.example.com">Example Link</a>'
        self.assertEqual(
            create_link_html("https://www.example.com", "Example Link", False), expected
        )
        expected = (
            '<a href="https://www.example.com">' "<strong>Example Link</strong></a>"
        )
        self.assertEqual(
            create_link_html(
                "https://www.example.com",
                mark_safe("<strong>Example Link</strong>"),
                False,
            ),
            expected,
        )

    def test_create_bs_glyph_html(self):
        expected = '<span class="glyphicon glyphicon-example"></span>'
        self.assertEqual(create_bs_glyph_html("example"), expected)

    def test_create_bs_button_html_default(self):
        expected = (
            '<a href="https://www.example.com" class="btn btn-info">'
            '<span class="glyphicon glyphicon-example"></span></a>'
        )
        self.assertEqual(
            create_bs_button_html("https://www.example.com", "example", "info"),
            expected,
        )

    def test_create_bs_button_html_disabled(self):
        expected = (
            '<a href="https://www.example.com" class="btn btn-info"'
            ' disabled="disabled">'
            '<span class="glyphicon glyphicon-example"></span></a>'
        )
        self.assertEqual(
            create_bs_button_html("https://www.example.com", "example", "info", True),
            expected,
        )


class TestGetSiteBaseUrl(NoSocketsTestCase):
    @patch(
        MODULE_PATH + ".settings.ESI_SSO_CALLBACK_URL",
        "https://www.mysite.com/sso/callback",
    )
    def test_return_url_if_url_defined_and_valid(self):
        expected = "https://www.mysite.com"
        self.assertEqual(get_site_base_url(), expected)

    @patch(
        MODULE_PATH + ".settings.ESI_SSO_CALLBACK_URL",
        "https://www.mysite.com/not-valid/",
    )
    def test_return_dummy_if_url_defined_but_not_valid(self):
        expected = ""
        self.assertEqual(get_site_base_url(), expected)

    @patch(MODULE_PATH + ".settings")
    def test_return_dummy_if_url_not_defined(self, mock_settings):
        delattr(mock_settings, "ESI_SSO_CALLBACK_URL")
        expected = ""
        self.assertEqual(get_site_base_url(), expected)


class TestJsonSerializer(NoSocketsTestCase):
    def test_encode_decode(self):
        my_dict = {"alpha": "hello", "bravo": now()}
        my_json = json.dumps(my_dict, cls=JSONDateTimeEncoder)
        my_dict_new = json.loads(my_json, cls=JSONDateTimeDecoder)
        self.assertDictEqual(my_dict, my_dict_new)


class TestGenerateInvalidPk(NoSocketsTestCase):
    def test_normal(self):
        User.objects.all().delete()
        User.objects.create(username="John Doe", password="dummy")
        invalid_pk = generate_invalid_pk(User)
        with self.assertRaises(User.DoesNotExist):
            User.objects.get(pk=invalid_pk)


class TestDatetimeRoundHour(TestCase):
    def test_round_down(self):
        obj = dt.datetime(2020, 12, 18, 22, 19)
        self.assertEqual(datetime_round_hour(obj), dt.datetime(2020, 12, 18, 22, 0))

    def test_round_up(self):
        obj = dt.datetime(2020, 12, 18, 22, 44)
        self.assertEqual(datetime_round_hour(obj), dt.datetime(2020, 12, 18, 23, 0))

    def test_before_midnight(self):
        obj = dt.datetime(2020, 12, 18, 23, 44)
        self.assertEqual(datetime_round_hour(obj), dt.datetime(2020, 12, 19, 0, 0))

    def test_after_midnight(self):
        obj = dt.datetime(2020, 12, 19, 00, 14)
        self.assertEqual(datetime_round_hour(obj), dt.datetime(2020, 12, 19, 0, 0))


class TestFormatIskValue(NoSocketsTestCase):
    def test_defaults(self):
        self.assertEqual(humanize_value(0.9), "0.90")
        self.assertEqual(humanize_value(1), "1.00")
        self.assertEqual(humanize_value(1.1), "1.10")
        self.assertEqual(humanize_value(1000), "1.00k")
        self.assertEqual(humanize_value(1100), "1.10k")
        self.assertEqual(humanize_value(551100), "551.10k")
        self.assertEqual(humanize_value(1000000), "1.00m")
        self.assertEqual(humanize_value(1000000000), "1.00b")
        self.assertEqual(humanize_value(1000000000000), "1.00t")

    def test_precision(self):
        self.assertEqual(humanize_value(12340000000, 1), "12.3b")


fake_objects = dict()


class FakeManager(ObjectCacheMixin):
    def create(self, name):
        pk = len(fake_objects) + 1
        fake_objects[pk] = self.model(pk, name)
        return fake_objects[pk]

    def get(self, pk):
        return fake_objects[pk]

    def select_related(self, query):
        return self

    @property
    def model(self):
        return FakeModel


class _FakeMeta:
    def __init__(self, app_label, model_name) -> None:
        self.app_label = app_label
        self.model_name = model_name


class FakeModel:
    def __init__(self, pk, name) -> None:
        self.pk = pk
        self.name = name

    _meta = _FakeMeta("dummy", "fakemodel")
    objects = FakeManager()


@patch(
    CURRENT_PATH + ".FakeManager._fetch_object_for_cache",
    wraps=FakeModel.objects._fetch_object_for_cache,
)
class TestObjectCacheMixin(TestCase):
    def setUp(self) -> None:
        self.obj = FakeModel.objects.create(name="My Fake Model")
        cache.clear()

    def test_get_cached_1(self, mock_fetch_object_for_cache):
        """when cache is empty, load from DB"""
        obj = FakeModel.objects.get_cached(pk=self.obj.pk)

        self.assertEqual(obj.name, "My Fake Model")
        self.assertEqual(mock_fetch_object_for_cache.call_count, 1)

    def test_get_cached_2(self, mock_fetch_object_for_cache):
        """when cache is not empty, load from cache"""
        obj = FakeModel.objects.get_cached(pk=self.obj.pk)

        obj = FakeModel.objects.get_cached(pk=self.obj.pk)

        self.assertEqual(obj.name, "My Fake Model")
        self.assertEqual(mock_fetch_object_for_cache.call_count, 1)

    def test_get_cached_3(self, mock_fetch_object_for_cache):
        """when cache is empty, load from DB"""
        obj = FakeModel.objects.get_cached(pk=self.obj.pk, select_related="dummy")

        self.assertEqual(obj.name, "My Fake Model")
        self.assertEqual(mock_fetch_object_for_cache.call_count, 1)
