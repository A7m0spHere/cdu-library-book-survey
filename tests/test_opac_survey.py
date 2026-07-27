from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SPEC = importlib.util.spec_from_file_location(
    "opac_survey",
    ROOT / "scripts" / "opac_survey.py",
)
assert SPEC and SPEC.loader
opac = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = opac
SPEC.loader.exec_module(opac)


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name: str) -> dict:
    return json.loads(fixture_text(name))


def sample_config() -> dict:
    return {
        "profile": {
            "school": "成都大学",
            "major": "计算机科学与技术",
            "stage": "本科二年级",
            "goal": "学习数据结构",
            "purpose": "课程学习",
            "network": "未知",
            "output_depth": "normal",
        },
        "keywords": ["数据结构"],
        "include_shelf_locations": False,
    }


def metadata(title: str) -> dict:
    return {
        "detail_url": f"http://example.invalid/{title}",
        "fields": {"题名": title, "学科主题": "数据结构"},
        "repeated_fields": {},
    }


def holding(barcode: str = "CDU000001", status: str = "可借") -> dict:
    return {
        "call_no": "TP311.12/1",
        "barcode": barcode,
        "volume": "",
        "location": "中文图书借阅区",
        "status": status,
    }


def sample_survey() -> dict:
    verified_at = "2026-07-27T10:00:00+08:00"
    holdings_provenance = opac.provenance(
        "live",
        verified_at,
        opac.LABEL_HOLDINGS_LIVE,
    )
    return {
        "schema_version": "1.0",
        "profile": sample_config()["profile"],
        "keyword_totals": {"数据结构": 1},
        "records": [
            {
                "marcRecNo": "MARC001",
                "title": "数据结构基础",
                "author": "测试作者",
                "publisher": "示例出版社",
                "pubYear": "2024",
                "callNo": "TP311.12/1",
                "matched_keywords": ["数据结构"],
                **metadata("数据结构基础"),
                "metadata_provenance": opac.provenance(
                    "live",
                    verified_at,
                    "[书目已实时获取]",
                ),
                "holdings_provenance": holdings_provenance,
                "holdings": opac.annotate_holdings(
                    [holding()],
                    holdings_provenance,
                ),
            }
        ],
        "source_log": {
            "collected_at": verified_at,
            "opac_base": opac.BASE,
            "navigation_base": opac.NAV_BASE,
            "keywords": ["数据结构"],
            "cache_enabled": True,
            "cache_write_errors": [],
            "cache_ttl_days": {
                "search": 30,
                "metadata": 30,
                "holdings": 3,
                "location": 30,
            },
            "cache_hits": {
                "search": 0,
                "metadata": 0,
                "holdings": 0,
                "location": 0,
            },
            "provenance_counts": {
                "search": {"live": 1, "cache": 0, "unverified": 0},
                "metadata": {"live": 1, "cache": 0, "unverified": 0},
                "holdings": {"live": 1, "cache": 0, "unverified": 0},
                "location": {"live": 0, "cache": 0, "unverified": 0},
            },
            "request_policy": {
                "delay_seconds": 0.8,
                "max_retries": 2,
                "retry_backoff_seconds": 1.0,
                "timeout_seconds": 25.0,
                "max_records": 50,
                "max_location_requests": 30,
            },
            "request_events": [],
            "failures": [],
            "records_discovered": 1,
            "records_processed": 1,
            "records_truncated": False,
            "location_live_requests": 0,
        },
        "labels": [opac.LABEL_HOLDINGS_LIVE],
    }


class ParserTests(unittest.TestCase):
    def test_dl_parser_and_duplicate_fields(self) -> None:
        parsed = opac.parse_metadata(
            fixture_text("item_normal.html"),
            "http://example.invalid/item",
        )

        self.assertEqual(parsed["fields"]["题名"], "数据结构基础")
        self.assertEqual(parsed["fields"]["学科主题"], "数据结构")
        self.assertEqual(
            parsed["repeated_fields"]["学科主题"],
            ["数据结构", "算法"],
        )

    def test_holdings_parser_extracts_normal_rows(self) -> None:
        holdings = opac.parse_holdings(fixture_text("item_normal.html"))

        self.assertEqual(len(holdings), 2)
        self.assertEqual(holdings[0]["barcode"], "CDU000001")
        self.assertEqual(holdings[0]["location"], "十陵校区中文图书借阅区")
        self.assertEqual(holdings[1]["status"], "借出")

    def test_no_holdings_is_a_verified_empty_list(self) -> None:
        page = fixture_text("item_no_holdings.html")
        holdings = opac.parse_holdings(page)

        self.assertEqual(holdings, [])
        self.assertTrue(opac.holdings_response_verified(page, holdings))

    def test_unknown_holdings_markup_is_not_treated_as_verified_empty(self) -> None:
        page = "<html><dl><dt>题名</dt><dd>结构未知</dd></dl></html>"

        self.assertEqual(opac.parse_holdings(page), [])
        self.assertFalse(opac.holdings_response_verified(page, []))

    def test_slight_markup_changes_and_nested_fields_are_supported(self) -> None:
        page = fixture_text("item_changed_markup.html")
        parsed = opac.parse_metadata(page, "http://example.invalid/changed")
        holdings = opac.parse_holdings(page)

        self.assertEqual(parsed["fields"]["题名"], "轻微结构变化示例")
        self.assertEqual(
            parsed["repeated_fields"]["学科主题"],
            ["软件工程", "程序设计"],
        )
        self.assertEqual(len(holdings), 2)
        self.assertEqual(holdings[0]["status"], "馆内阅览")
        self.assertEqual(holdings[1]["barcode"], "CDU000009")

    def test_shelf_parser_handles_normal_and_error_pages(self) -> None:
        normal = opac.parse_shelf_location(
            fixture_text("shelf_normal.html"),
            "CDU000001",
            "http://example.invalid/shelf",
        )
        error = opac.parse_shelf_location(
            fixture_text("shelf_error.html"),
            "CDU000404",
            "http://example.invalid/missing",
        )

        self.assertEqual(normal["shelf_code"], "A12-2-4")
        self.assertIn("3 楼", normal["navigation_location"])
        self.assertEqual(normal["navigation_title"], "数据结构基础")
        self.assertEqual(error["shelf_code"], "")
        self.assertIn("暂未找到", error["navigation_location"])


class ConfigurationTests(unittest.TestCase):
    def test_runtime_validation_matches_schema_enums_and_keyword_limits(self) -> None:
        opac.validate_config(sample_config())

        invalid_network = sample_config()
        invalid_network["profile"]["network"] = "测试网络"
        with self.assertRaises(SystemExit):
            opac.validate_config(invalid_network)

        duplicate_keywords = sample_config()
        duplicate_keywords["keywords"] = ["数据结构", "数据结构"]
        with self.assertRaises(SystemExit):
            opac.validate_config(duplicate_keywords)


class CacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.cache = opac.Cache(Path(self.tempdir.name))

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_metadata_is_valid_for_30_days_but_holdings_expire_after_3(self) -> None:
        base = 2_000_000_000
        four_days_ago = base - 4 * 24 * 3600
        self.cache.set("metadata", "M1", metadata("缓存书目"), cached_at=four_days_ago)
        self.cache.set("holdings", "M1", [holding()], cached_at=four_days_ago)

        with mock.patch.object(opac, "now_ts", return_value=base):
            metadata_lookup = self.cache.get(
                "metadata",
                "M1",
                opac.CACHE_TTL["metadata"],
            )
            holdings_lookup = self.cache.get(
                "holdings",
                "M1",
                opac.CACHE_TTL["holdings"],
            )

        self.assertTrue(metadata_lookup.hit)
        self.assertFalse(holdings_lookup.hit)

    def test_search_metadata_and_location_expire_after_30_days(self) -> None:
        base = 2_000_000_000
        twenty_nine_days_ago = base - 29 * 24 * 3600
        thirty_one_days_ago = base - 31 * 24 * 3600
        values = {
            "search": {"content": []},
            "metadata": metadata("缓存书目"),
            "location": {"navigation_location": "3 楼示例架位"},
        }
        for namespace, value in values.items():
            self.cache.set(namespace, "fresh", value, cached_at=twenty_nine_days_ago)
            self.cache.set(namespace, "stale", value, cached_at=thirty_one_days_ago)

        with mock.patch.object(opac, "now_ts", return_value=base):
            for namespace in values:
                with self.subTest(namespace=namespace):
                    self.assertTrue(
                        self.cache.get(
                            namespace,
                            "fresh",
                            opac.CACHE_TTL[namespace],
                        ).hit
                    )
                    self.assertFalse(
                        self.cache.get(
                            namespace,
                            "stale",
                            opac.CACHE_TTL[namespace],
                        ).hit
                    )

    def test_corrupt_cache_and_utf8_bom_are_handled_safely(self) -> None:
        corrupt = self.cache.path("metadata", "broken")
        corrupt.parent.mkdir(parents=True)
        corrupt.write_text("{not-json", encoding="utf-8")
        self.assertFalse(
            self.cache.get("metadata", "broken", opac.CACHE_TTL["metadata"]).hit
        )

        valid = self.cache.path("metadata", "bom")
        payload = {
            "cached_at": opac.now_ts(),
            "data": metadata("BOM 缓存"),
        }
        valid.write_text(
            "\ufeff" + json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        self.assertTrue(
            self.cache.get("metadata", "bom", opac.CACHE_TTL["metadata"]).hit
        )

    def test_wrong_cache_payload_types_trigger_live_refresh(self) -> None:
        self.cache.set("metadata", "M1", ["not", "metadata"])
        self.cache.set("holdings", "M1", {"status": "not a list"})
        client = mock.Mock()
        client.get_text.return_value = fixture_text("item_normal.html")

        result = opac.detail_record("M1", self.cache, client)

        client.get_text.assert_called_once()
        self.assertEqual(result.metadata_provenance["source"], "live")
        self.assertEqual(result.holdings_provenance["source"], "live")
        self.assertEqual(len(result.data["holdings"]), 2)

    def test_cache_write_is_atomic_and_leaves_no_temp_file(self) -> None:
        self.cache.set("metadata", "M1", metadata("原子写入"))
        cache_dir = self.cache.path("metadata", "M1").parent

        self.assertTrue(self.cache.path("metadata", "M1").exists())
        self.assertEqual(list(cache_dir.glob("*.tmp")), [])

    def test_cache_write_failure_is_recorded_and_temp_file_is_removed(self) -> None:
        with mock.patch.object(opac.os, "replace", side_effect=OSError("disk full")):
            self.cache.set("metadata", "M1", metadata("写入失败"))

        cache_dir = self.cache.path("metadata", "M1").parent
        self.assertFalse(self.cache.path("metadata", "M1").exists())
        self.assertEqual(list(cache_dir.glob("*.tmp")), [])
        self.assertEqual(self.cache.write_errors[0]["namespace"], "metadata")
        self.assertIn("disk full", self.cache.write_errors[0]["error"])

    def test_stale_legacy_embedded_holdings_are_ignored(self) -> None:
        base = 2_000_000_000
        legacy = {**metadata("旧缓存"), "holdings": [holding(status="可借")]}
        self.cache.set(
            "metadata",
            "M1",
            legacy,
            cached_at=base - 4 * 24 * 3600,
        )
        client = mock.Mock()
        client.get_text.side_effect = urllib.error.URLError("offline")

        with mock.patch.object(opac, "now_ts", return_value=base):
            result = opac.detail_record("M1", self.cache, client)

        self.assertEqual(result.metadata_provenance["source"], "cache")
        self.assertEqual(result.holdings_provenance["source"], "unverified")
        self.assertEqual(result.data["holdings"], [])
        self.assertIn(opac.LABEL_HOLDINGS_UNVERIFIED, result.holdings_provenance["label"])

    def test_fresh_legacy_holdings_keep_original_timestamp_when_migrated(self) -> None:
        base = 2_000_000_000
        cached_at = base - 2 * 24 * 3600
        legacy = {**metadata("可迁移缓存"), "holdings": [holding()]}
        self.cache.set("metadata", "M1", legacy, cached_at=cached_at)
        client = mock.Mock()

        with mock.patch.object(opac, "now_ts", return_value=base):
            result = opac.detail_record("M1", self.cache, client)
            migrated = self.cache.get(
                "holdings",
                "M1",
                opac.CACHE_TTL["holdings"],
            )
            cleaned_metadata = self.cache.get(
                "metadata",
                "M1",
                opac.CACHE_TTL["metadata"],
            )

        client.get_text.assert_not_called()
        self.assertEqual(result.holdings_provenance["source"], "cache")
        self.assertEqual(migrated.cached_at, cached_at)
        self.assertNotIn("holdings", cleaned_metadata.data)
        self.assertEqual(result.data["holdings"][0]["status_source"], "cache")

    def test_failed_legacy_migration_preserves_original_cache_data(self) -> None:
        base = 2_000_000_000
        cached_at = base - 2 * 24 * 3600
        legacy = {**metadata("迁移失败缓存"), "holdings": [holding()]}
        self.cache.set("metadata", "M1", legacy, cached_at=cached_at)
        original_path = self.cache.path("metadata", "M1")
        client = mock.Mock()
        client.get_text.side_effect = urllib.error.URLError("offline")

        with mock.patch.object(opac, "now_ts", return_value=base):
            with mock.patch.object(
                opac.os,
                "replace",
                side_effect=OSError("read only"),
            ):
                result = opac.detail_record("M1", self.cache, client)

        persisted = json.loads(original_path.read_text(encoding="utf-8"))
        self.assertIn("holdings", persisted["data"])
        self.assertEqual(result.metadata_provenance["source"], "cache")
        self.assertEqual(result.holdings_provenance["source"], "unverified")
        self.assertGreaterEqual(len(self.cache.write_errors), 1)

    def test_cached_holdings_are_unverified_even_without_request_failure(self) -> None:
        cached_at = opac.now_ts() - 60
        self.cache.set("metadata", "M1", metadata("缓存书目"), cached_at=cached_at)
        self.cache.set("holdings", "M1", [holding()], cached_at=cached_at)
        client = mock.Mock()

        result = opac.detail_record("M1", self.cache, client)

        client.get_text.assert_not_called()
        self.assertEqual(result.holdings_provenance["source"], "cache")
        self.assertIn(
            opac.LABEL_HOLDINGS_CACHE,
            result.holdings_provenance["label"],
        )
        self.assertIn(
            opac.LABEL_HOLDINGS_UNVERIFIED,
            result.holdings_provenance["label"],
        )
        self.assertEqual(
            result.data["holdings"][0]["status_verified_at"],
            opac.iso_from_ts(cached_at),
        )

    def test_explicit_empty_holdings_response_is_live_verified_and_cached(self) -> None:
        client = mock.Mock()
        client.get_text.return_value = fixture_text("item_no_holdings.html")

        result = opac.detail_record("M1", self.cache, client)
        cached = self.cache.get("holdings", "M1", opac.CACHE_TTL["holdings"])

        self.assertEqual(result.holdings_provenance["source"], "live")
        self.assertEqual(result.data["holdings"], [])
        self.assertTrue(cached.hit)
        self.assertEqual(cached.data, [])

    def test_unknown_live_holdings_markup_remains_unverified(self) -> None:
        client = mock.Mock()
        client.get_text.return_value = (
            "<html><dl><dt>题名</dt><dd>结构未知</dd></dl></html>"
        )

        result = opac.detail_record("M1", self.cache, client)
        cached = self.cache.get("holdings", "M1", opac.CACHE_TTL["holdings"])

        self.assertEqual(result.metadata_provenance["source"], "live")
        self.assertEqual(result.holdings_provenance["source"], "unverified")
        self.assertIsNotNone(result.error)
        self.assertFalse(cached.hit)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class RequestTests(unittest.TestCase):
    def test_retry_uses_bounded_backoff_for_temporary_http_statuses(self) -> None:
        for status in (429, 502, 503, 504):
            with self.subTest(status=status):
                clock = FakeClock()
                attempts = [
                    urllib.error.HTTPError(
                        "http://example.invalid",
                        status,
                        "temporary",
                        {},
                        None,
                    ),
                    FakeResponse(b"ok"),
                ]

                def opener(*_args: object, **_kwargs: object) -> FakeResponse:
                    value = attempts.pop(0)
                    if isinstance(value, Exception):
                        raise value
                    return value

                client = opac.RequestClient(
                    delay=0.8,
                    max_retries=2,
                    backoff=1.0,
                    opener=opener,
                    sleeper=clock.sleep,
                    monotonic=clock.monotonic,
                )

                self.assertEqual(client.request("http://example.invalid"), b"ok")
                self.assertEqual(clock.sleeps, [1.0])
                self.assertEqual(client.events[0]["event"], "request_retry")
                self.assertEqual(client.events[0]["error"], f"HTTP {status}")

    def test_non_retryable_http_error_is_not_retried(self) -> None:
        calls: list[str] = []

        def opener(*_args: object, **_kwargs: object) -> FakeResponse:
            calls.append("request")
            raise urllib.error.HTTPError(
                "http://example.invalid",
                404,
                "not found",
                {},
                None,
            )

        client = opac.RequestClient(delay=0.2, max_retries=2, opener=opener)

        with self.assertRaises(urllib.error.HTTPError) as raised:
            client.request("http://example.invalid")
        raised.exception.close()

        self.assertEqual(len(calls), 1)
        self.assertFalse(client.events[-1]["retryable"])

    def test_temporary_network_failure_stops_after_max_retries(self) -> None:
        clock = FakeClock()
        opener = mock.Mock(side_effect=urllib.error.URLError("offline"))
        client = opac.RequestClient(
            delay=0.2,
            max_retries=2,
            backoff=1.0,
            opener=opener,
            sleeper=clock.sleep,
            monotonic=clock.monotonic,
        )

        with self.assertRaises(urllib.error.URLError):
            client.request("http://example.invalid")

        self.assertEqual(opener.call_count, 3)
        self.assertEqual(clock.sleeps, [1.0, 2.0])
        self.assertEqual(client.events[-1]["event"], "request_failed")

    def test_minimum_delay_is_applied_between_successful_requests(self) -> None:
        clock = FakeClock()
        opener = mock.Mock(
            side_effect=[FakeResponse(b"first"), FakeResponse(b"second")]
        )
        client = opac.RequestClient(
            delay=0.8,
            max_retries=0,
            opener=opener,
            sleeper=clock.sleep,
            monotonic=clock.monotonic,
        )

        client.request("http://example.invalid/1")
        client.request("http://example.invalid/2")

        self.assertEqual(clock.sleeps, [0.8])


class CollectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.cache = opac.Cache(Path(self.tempdir.name))
        search_key = json.dumps(
            {"keyword": "数据结构", "page_size": 50},
            ensure_ascii=False,
        )
        self.cache.set("search", search_key, fixture_json("search_response.json"))

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_single_record_network_failure_keeps_partial_results_and_source_log(self) -> None:
        self.cache.set("metadata", "MARC001", metadata("数据结构基础"))
        self.cache.set("holdings", "MARC001", [holding()])
        client = mock.Mock()
        client.events = []
        client.delay = 0.8
        client.max_retries = 2
        client.backoff = 1.0
        client.timeout = 25.0
        client.get_text.side_effect = urllib.error.URLError("offline")

        result = opac.collect(sample_config(), self.cache, client)

        self.assertEqual(len(result["records"]), 2)
        failed = next(record for record in result["records"] if record["marcRecNo"] == "MARC002")
        self.assertEqual(failed["holdings_provenance"]["source"], "unverified")
        self.assertTrue(result["source_log"]["failures"])
        self.assertIn(opac.LABEL_PARTIAL, result["labels"])
        self.assertIn(opac.LABEL_HOLDINGS_CACHE, result["labels"])
        self.assertIn(opac.LABEL_HOLDINGS_UNVERIFIED, result["labels"])

    def test_max_records_truncates_detail_work_without_losing_search_totals(self) -> None:
        for marc in ("MARC001", "MARC002"):
            self.cache.set("metadata", marc, metadata(marc))
            self.cache.set("holdings", marc, [])
        client = mock.Mock()
        client.events = []
        client.delay = 0.8
        client.max_retries = 2
        client.backoff = 1.0
        client.timeout = 25.0

        result = opac.collect(
            sample_config(),
            self.cache,
            client,
            max_records=1,
        )

        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["keyword_totals"]["数据结构"], 2)
        self.assertTrue(result["source_log"]["records_truncated"])
        self.assertIn(opac.LABEL_PARTIAL, result["labels"])
        client.get_text.assert_not_called()

    def test_location_request_limit_marks_remaining_holdings_unverified(self) -> None:
        config = sample_config()
        config["include_shelf_locations"] = True
        self.cache.set("metadata", "MARC001", metadata("数据结构基础"))
        self.cache.set(
            "holdings",
            "MARC001",
            [holding("CDU000001"), holding("CDU000002")],
        )
        self.cache.set("metadata", "MARC002", metadata("算法导论示例"))
        self.cache.set("holdings", "MARC002", [])
        client = mock.Mock()
        client.events = []
        client.delay = 0.8
        client.max_retries = 2
        client.backoff = 1.0
        client.timeout = 25.0
        client.get_text.return_value = fixture_text("shelf_normal.html")

        result = opac.collect(
            config,
            self.cache,
            client,
            max_location_requests=1,
        )

        first_record = next(
            record for record in result["records"] if record["marcRecNo"] == "MARC001"
        )
        self.assertEqual(client.get_text.call_count, 1)
        self.assertEqual(
            first_record["holdings"][0]["navigation_provenance"]["source"],
            "live",
        )
        self.assertEqual(
            first_record["holdings"][1]["navigation_provenance"]["source"],
            "unverified",
        )
        self.assertEqual(result["source_log"]["location_live_requests"], 1)


class OutputTests(unittest.TestCase):
    def test_json_csv_and_markdown_include_status_provenance(self) -> None:
        survey = sample_survey()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_path = root / "survey.json"
            csv_path = root / "survey.csv"
            markdown_path = root / "survey.md"

            opac.write_json(survey, json_path)
            opac.write_csv(survey, csv_path)
            opac.write_markdown(survey, markdown_path)

            json_data = json.loads(json_path.read_text(encoding="utf-8"))
            with csv_path.open(encoding="utf-8-sig", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))
            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertEqual(
            json_data["records"][0]["holdings"][0]["status_source"],
            "live",
        )
        self.assertEqual(csv_rows[0]["status_source"], "live")
        self.assertIn("status_source", csv_rows[0])
        self.assertIn("verified_at=2026-07-27", markdown)
        self.assertIn(opac.LABEL_HOLDINGS_LIVE, markdown)

    def test_cli_accepts_utf8_bom_input(self) -> None:
        request = sample_config()
        survey = sample_survey()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            output_path = root / "survey.json"
            request_path.write_text(
                "\ufeff" + json.dumps(request, ensure_ascii=False),
                encoding="utf-8",
            )
            with mock.patch.object(opac, "collect", return_value=survey):
                exit_code = opac.main(
                    [
                        "--input",
                        str(request_path),
                        "--output",
                        str(output_path),
                        "--no-cache",
                        "--delay",
                        "0.2",
                    ]
                )

            output = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(output["schema_version"], "1.0")


if __name__ == "__main__":
    unittest.main()
