from __future__ import annotations

import asyncio
import inspect
import unittest
from unittest.mock import patch

import requests

from app.capabilities.get_base_basic_data import handler


class _Progress:
    def running(self, *_args):
        pass

    def success(self, *_args):
        pass

    def error(self, *_args):
        pass


class _Client:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get_json(self, path, *, params=None, label=None):
        self.calls.append((path, params or {}, label))
        response = self.responses[path]
        if isinstance(response, Exception):
            raise response
        return response


def _area_response(area_id="12"):
    return {
        "code": 200,
        "data": {
            "rows": [
                {
                    "id": int(area_id),
                    "area_name": "测试基地",
                    "met_num": "CURRENT_WEATHER_ONLY",
                    "ricestage_num": "CURRENT_RICE_ONLY",
                    "insects_num": "INSECT-1",
                    "suggest_num": "12",
                }
            ],
            "total": 1,
        },
    }


def _normal_responses(area_id="12"):
    coverage = {"status": "NORMAL", "gaps": []}
    return {
        "/area/page": _area_response(area_id),
        "/screen/getAreaMet": {
            "code": 200,
            "data": {
                "xticks": ["2026-07-14", "2026-07-15"],
                "temp": [{"name": "平均", "data": [21.1, 31.2]}],
                "hum": [],
                "coverage": coverage,
            },
        },
        "/pengbo/getInsect": {"xticks": [], "ehm": [], "dzjym": [], "hefs": []},
        "/aipp/area-device-presets": {
            "code": 200,
            "data": {
                "presets": [{"preset": "1", "crop": "早稻"}],
                "coverage": coverage,
            },
        },
        "/aipp/area-rice-stage": {
            "code": 200,
            "data": {
                "xticks": ["2026-07-14", "2026-07-15"],
                "stage": [{"name": "分蘖期", "data": [0.8, 0.9]}],
                "rows": [],
                "coverage": coverage,
            },
        },
        "/screen/v2/getSuggestRice": {"sugF": [], "sugD": [], "sugI": []},
    }


class GetBaseBasicDataTests(unittest.TestCase):
    def _run(self, client, *, area_id="12", area_name=""):
        with (
            patch.object(handler, "RiceApiClient", return_value=client),
            patch.object(handler.ProgressWriter, "from_context", return_value=_Progress()),
            patch.object(handler, "_build_access_token_from_context", return_value=("token", "user")),
            patch.object(handler, "_append_result_log"),
            patch.object(handler, "_append_api_call_log"),
        ):
            return asyncio.run(
                handler.handle(
                    {
                        "action": "overview",
                        "area_id": area_id,
                        "area_name": area_name,
                        "start_date": "2026-07-14",
                        "end_date": "2026-07-15",
                    },
                    {"user_id": "user"},
                )
            )

    def test_area_mode_uses_binding_history_endpoints_and_half_open_range(self):
        client = _Client(_normal_responses())

        result = self._run(client)

        calls = {path: params for path, params, _label in client.calls}
        self.assertEqual(
            calls["/screen/getAreaMet"],
            {
                "areaId": "12",
                "startTime": "2026-07-14 00:00:00",
                "endTime": "2026-07-16 00:00:00",
                "includeBindingMeta": False,
            },
        )
        self.assertEqual(calls["/aipp/area-device-presets"], {"areaId": "12", "date": "2026-07-15"})
        self.assertEqual(calls["/aipp/area-rice-stage"]["areaId"], "12")
        self.assertEqual(calls["/aipp/area-rice-stage"]["endTime"], "2026-07-16 00:00:00")
        self.assertEqual(calls["/aipp/area-rice-stage"]["preset"], "1")
        self.assertFalse(any(path in {"/screen/getMet", "/aipp/getRiceStage", "/aipp/getDevicePresets"} for path in calls))
        self.assertEqual(result["query_mode"], "area")
        self.assertEqual(result["module_statuses"]["weather"], "NORMAL")
        self.assertEqual(result["device_refs"]["met_num"], "CURRENT_WEATHER_ONLY")

    def test_area_name_is_resolved_to_id_before_history_queries(self):
        client = _Client(_normal_responses())

        self._run(client, area_id="", area_name="测试基地")

        calls = {path: params for path, params, _label in client.calls}
        self.assertEqual(calls["/screen/getAreaMet"]["areaId"], "12")
        self.assertEqual(calls["/aipp/area-rice-stage"]["areaId"], "12")

    def test_partial_coverage_keeps_available_weather_data(self):
        responses = _normal_responses()
        responses["/screen/getAreaMet"]["data"]["coverage"] = {
            "status": "PARTIAL_COVERAGE",
            "gaps": [{"start": "2026-07-14", "end": "2026-07-15"}],
        }
        client = _Client(responses)

        result = self._run(client)

        self.assertEqual(result["module_statuses"]["weather"], "PARTIAL_COVERAGE")
        self.assertTrue(result["met_overview"]["temp"])
        self.assertTrue(any("PARTIAL_COVERAGE" in warning for warning in result["warnings"]))

    def test_needs_review_does_not_fallback_and_keeps_weather(self):
        responses = _normal_responses(area_id="11")
        responses["/aipp/area-device-presets"] = {
            "code": 50001,
            "msg": "生育期设备绑定需要人工确认",
            "data": {"errorCode": "RICE_STAGE_BINDING_NEEDS_MANUAL_REVIEW"},
        }
        client = _Client(responses)

        result = self._run(client, area_id="11")

        paths = [path for path, _params, _label in client.calls]
        self.assertNotIn("/aipp/area-rice-stage", paths)
        self.assertEqual(result["module_statuses"]["rice_stage"], "NEEDS_REVIEW")
        self.assertEqual(result["rice_stage_overview"]["stage"], [])
        self.assertTrue(result["met_overview"]["temp"])
        self.assertTrue(any("NEEDS_REVIEW" in warning for warning in result["warnings"]))

    def test_one_module_transport_failure_does_not_drop_other_modules(self):
        responses = _normal_responses()
        responses["/screen/getAreaMet"] = requests.ConnectionError("offline")
        client = _Client(responses)

        result = self._run(client)

        self.assertEqual(result["module_statuses"]["weather"], "ERROR")
        self.assertTrue(result["rice_stage_overview"]["stage"])

    def test_not_configured_returns_empty_module_with_explicit_status(self):
        responses = _normal_responses()
        responses["/screen/getAreaMet"] = {
            "code": 200,
            "data": {"xticks": [], "temp": [], "hum": [], "coverage": {"status": "NOT_CONFIGURED"}},
        }
        client = _Client(responses)

        result = self._run(client)

        self.assertEqual(result["module_statuses"]["weather"], "NOT_CONFIGURED")
        self.assertEqual(result["met_overview"]["temp"], [])
        self.assertTrue(any("NOT_CONFIGURED" in warning for warning in result["warnings"]))

    def test_data_inconsistent_stops_weather_only(self):
        responses = _normal_responses()
        responses["/screen/getAreaMet"] = {
            "code": 50001,
            "msg": "天气设备绑定履历异常",
            "data": {"errorCode": "BINDING_DATA_INCONSISTENT"},
        }
        client = _Client(responses)

        result = self._run(client)

        self.assertEqual(result["module_statuses"]["weather"], "DATA_INCONSISTENT")
        self.assertEqual(result["met_overview"]["temp"], [])
        self.assertTrue(result["rice_stage_overview"]["stage"])

    def test_business_error_code_is_preserved_and_mapped(self):
        payload = {"code": 50001, "msg": "冲突", "data": {"errorCode": "BINDING_DATA_INCONSISTENT"}}

        with self.assertRaises(handler.CapabilityExecutionError) as context:
            handler._unwrap_api_payload(payload, path="/screen/getAreaMet")

        self.assertEqual(context.exception.code, "BINDING_DATA_INCONSISTENT")
        self.assertEqual(handler._status_from_error_code(context.exception.code), "DATA_INCONSISTENT")

    def test_source_has_no_base_history_device_fallback(self):
        source = inspect.getsource(handler)

        for forbidden in (
            '"/screen/getMet"',
            '"/screen/getMetMore"',
            '"/aipp/getRiceStage"',
            '"/aipp/getDevicePresets"',
            '"/aipp/screenshots"',
            "monitor_num",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
