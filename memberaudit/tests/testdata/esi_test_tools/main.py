"""
Tools for building unit tests with django-esi
"""

from collections import namedtuple
from typing import Any, List

from bravado.exception import HTTPNotFound

from django.utils.dateparse import parse_datetime


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


EsiEndpoint_T = namedtuple(
    "EsiEndpoint", ["category", "method", "primary_key", "needs_token"]
)


def EsiEndpoint(
    category: str, method: str, primary_key: str, needs_token: bool = False
) -> EsiEndpoint_T:
    return EsiEndpoint_T(category, method, primary_key, needs_token)


class _BravadoResponseStub:
    def __init__(self, status_code, *args, **kwargs):
        self.status_code = status_code


class _EsiRoute:
    def __init__(
        self,
        endpoint: EsiEndpoint_T,
        testdata: dict,
    ) -> None:
        self._category = endpoint.category
        self._method = endpoint.method
        self._primary_key = endpoint.primary_key
        self._needs_token = endpoint.needs_token
        self._testdata = testdata

    def call(self, **kwargs):
        pk_value = None
        if self._primary_key not in kwargs:
            raise ValueError(
                f"{self._category}.{self._method}: Missing primary key: "
                f"{self._primary_key}"
            )
        if self._needs_token:
            if "token" not in kwargs:
                raise ValueError(
                    f"{self._category}.{self._method} "
                    f"with pk = {self._primary_key}: Missing token"
                )
            elif not isinstance(kwargs.get("token"), str):
                raise TypeError(
                    f"{self._category}.{self._method} "
                    f"with pk = {self._primary_key}: Token is not a string"
                )
        try:
            pk_value = str(kwargs[self._primary_key])
            result = self._convert_values(
                self._testdata[self._category][self._method][pk_value]
            )

        except KeyError:
            raise HTTPNotFound(
                _BravadoResponseStub(404),
                f"{self._category}.{self._method}: No test data for "
                f"{self._primary_key} = {pk_value}",
            ) from None

        return BravadoOperationStub(result)

    @staticmethod
    def _convert_values(data) -> Any:
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str):
                    try:
                        dt = parse_datetime(v)
                        if dt:
                            data[k] = dt
                    except ValueError:
                        pass

        return data


class EsiClientStub:
    def __init__(self, testdata: dict, endpoints: List[EsiEndpoint_T]) -> None:
        self._testdata = testdata
        for endpoint in endpoints:
            self._validate_endpoint(endpoint)
            self._add_endpoint(endpoint)

    def _validate_endpoint(self, endpoint: EsiEndpoint_T):
        try:
            _ = self._testdata[endpoint.category][endpoint.method]
        except KeyError:
            raise ValueError(f"No data provided for {endpoint}")

    def _add_endpoint(self, endpoint: EsiEndpoint):
        if not hasattr(self, endpoint.category):
            setattr(self, endpoint.category, type(endpoint.category, (object,), dict()))
        my_category = getattr(self, endpoint.category)
        if not hasattr(my_category, endpoint.method):
            setattr(
                my_category,
                endpoint.method,
                _EsiRoute(endpoint, self._testdata).call,
            )
        else:
            raise ValueError(f"Endpoint for {endpoint} already defined!")
