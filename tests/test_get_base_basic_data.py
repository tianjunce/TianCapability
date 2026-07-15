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
                "rows": [
                    {
                        "date": "2026-07-15",
                        "metrics": [
                            {"key": "airTemperature", "mean": 31.2, "max": 33.0, "min": 29.0},
                            {"key": "airHumidity", "mean": 80.0, "max": 85.0, "min": 75.0},
                        ],
                    },
                    {
                        "date": "2026-07-14",
                        "metrics": [
                            {"key": "airTemperature", "mean": 21.1, "max": 22.0, "min": 20.0},
                            {"key": "airHumidity", "mean": 90.9, "max": 94.2, "min": 83.2},
                        ],
                    },
                ],
                "coverage": coverage,
            },
        },
        "/pengbo/getInsect": {"xticks": [], "ehm": [], "dzjym": [], "hefs": []},
        "/aipp/area-device-presets": {
            "code": 200,
            "data": {
                "presets": [
                    {"preset": "1", "crop": "早稻"},
                    {"preset": "2", "crop": "早稻"},
                ],
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
        self.assertEqual(result["met_overview"]["data_status"], "NORMAL")
        met_axis = result["time_axes"][result["met_overview"]["axis_ref"]]
        self.assertEqual(met_axis["start"], "2026-07-14")
        self.assertEqual(met_axis["end"], "2026-07-15")
        self.assertEqual(met_axis["count"], 2)
        self.assertEqual(result["rice_stage_overview"]["preset"], "1")
        self.assertEqual(result["rice_stage_overview"]["preset_selection"], "FIRST_AVAILABLE")
        self.assertEqual(
            result["rice_stage_overview"]["available_presets"],
            [{"preset": "1", "crop": "早稻"}, {"preset": "2", "crop": "早稻"}],
        )

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

    def test_weather_rows_metrics_are_sorted_and_preserve_nulls(self):
        warnings = []
        overview = handler._build_met_overview(
            {
                "rows": [
                    {
                        "date": "2026-06-26",
                        "metrics": [
                            {"key": "airTemperature", "max": None, "mean": 20.0, "min": 18.0},
                            {"key": "airHumidity", "max": 95.0, "mean": None, "min": 80.0},
                        ],
                    },
                    {
                        "date": "2026-06-25",
                        "metrics": [
                            {"key": "airTemperature", "max": 22.0, "mean": 19.2, "min": 17.0},
                            {"key": "airHumidity", "max": 94.2, "mean": 90.9, "min": 83.2},
                        ],
                    },
                ],
                "coverage": {"status": "NORMAL", "gaps": []},
            },
            binding_status="NORMAL",
            warnings=warnings,
        )

        self.assertEqual(overview["xticks"], ["2026-06-25", "2026-06-26"])
        self.assertEqual(overview["temp"][0], {"name": "最高温度", "data": [22.0, None]})
        self.assertEqual(overview["temp"][1], {"name": "平均温度", "data": [19.2, 20.0]})
        self.assertEqual(overview["temp"][2], {"name": "最低温度", "data": [17.0, 18.0]})
        self.assertEqual(overview["hum"][0], {"name": "最高湿度", "data": [94.2, 95.0]})
        self.assertEqual(overview["hum"][1], {"name": "平均湿度", "data": [90.9, None]})
        self.assertEqual(overview["hum"][2], {"name": "最低湿度", "data": [83.2, 80.0]})
        self.assertTrue(
            all(len(item["data"]) == len(overview["xticks"]) for item in [*overview["temp"], *overview["hum"]])
        )
        self.assertEqual(overview["coverage"], {"status": "NORMAL", "gaps": []})
        self.assertEqual(overview["data_status"], "NORMAL")
        self.assertEqual(overview["latest_data_date"], "2026-06-26")
        self.assertEqual(overview["data_date_count"], 2)
        self.assertEqual(overview["empty_date_count"], 0)
        self.assertEqual(warnings, [])

    def test_weather_partial_data_has_independent_status_and_warning(self):
        warnings = []
        overview = handler._build_met_overview(
            {
                "rows": [
                    {"date": "2026-06-28", "metrics": []},
                    {"date": "2026-06-29", "metrics": [{"key": "airTemperature", "mean": 25.0}]},
                ],
                "coverage": {"status": "NORMAL", "gaps": []},
            },
            binding_status="NORMAL",
            warnings=warnings,
        )

        self.assertEqual(overview["binding_status"], "NORMAL")
        self.assertEqual(overview["coverage"]["status"], "NORMAL")
        self.assertEqual(overview["data_status"], "PARTIAL_DATA")
        self.assertEqual(overview["data_date_count"], 1)
        self.assertEqual(overview["empty_date_count"], 1)
        self.assertEqual(overview["latest_data_date"], "2026-06-29")
        self.assertTrue(any("部分日期没有有效温湿度数据" in item for item in warnings))
        self.assertTrue(any("airHumidity" in item for item in overview["schema_warnings"]))

    def test_weather_all_empty_is_no_data_even_when_binding_is_normal(self):
        overview = handler._build_met_overview(
            {
                "rows": [
                    {
                        "date": "2026-06-30",
                        "metrics": [
                            {"key": "airTemperature", "max": None, "mean": None, "min": None},
                            {"key": "airHumidity", "max": None, "mean": None, "min": None},
                        ],
                    }
                ],
                "coverage": {"status": "NORMAL", "gaps": []},
            },
            binding_status="NORMAL",
        )

        self.assertEqual(overview["binding_status"], "NORMAL")
        self.assertEqual(overview["coverage"]["status"], "NORMAL")
        self.assertEqual(overview["data_status"], "NO_DATA")
        self.assertEqual(overview["latest_data_date"], "")
        self.assertEqual(overview["data_date_count"], 0)
        self.assertEqual(overview["empty_date_count"], 1)

    def test_legacy_weather_shape_remains_compatible(self):
        legacy = {
            "xticks": ["2026-07-14", "2026-07-15"],
            "temp": [{"name": "平均温度", "data": [21.1, None]}],
            "hum": [{"name": "平均湿度", "data": [80.0, 81.0]}],
            "coverage": {"status": "NORMAL", "gaps": []},
        }

        overview = handler._build_met_overview(legacy, binding_status="NORMAL")

        self.assertEqual(overview["xticks"], legacy["xticks"])
        self.assertEqual(overview["temp"], legacy["temp"])
        self.assertEqual(overview["hum"], legacy["hum"])
        self.assertEqual(overview["data_status"], "NORMAL")

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
