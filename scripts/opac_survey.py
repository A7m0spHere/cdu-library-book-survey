#!/usr/bin/env python3
"""
Collect Chengdu University OPAC search results, bibliographic metadata,
holdings status, and shelf navigation evidence.

The collector is agent-neutral and intentionally uses only Python standard
library modules. Recommendation ranking and academic judgment remain the
responsibility of the calling Agent and the rules under references/.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

BASE = "http://libopac.cdu.edu.cn/opac/"
NAV_BASE = "http://120.94.216.7:8080/navigationservice/bookcode/"
USER_AGENT = "Mozilla/5.0 (compatible; cdu-library-book-survey/1.1)"

DEFAULT_REQUEST_DELAY = 0.8
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF = 1.0
DEFAULT_TIMEOUT = 25.0
DEFAULT_MAX_RECORDS = 50
DEFAULT_MAX_LOCATION_REQUESTS = 30
MAX_PAGE_SIZE = 100
RETRYABLE_HTTP_STATUS = {429, 502, 503, 504}

CACHE_TTL = {
    "search": 30 * 24 * 3600,
    "metadata": 30 * 24 * 3600,
    "holdings": 3 * 24 * 3600,
    "location": 30 * 24 * 3600,
}

LABEL_SEARCH_CACHE = "[检索结果来自缓存]"
LABEL_METADATA_CACHE = "[书目来自缓存]"
LABEL_HOLDINGS_CACHE = "[馆藏状态来自缓存]"
LABEL_LOCATION_CACHE = "[架位信息来自缓存]"
LABEL_HOLDINGS_LIVE = "[馆藏状态已实时核验]"
LABEL_HOLDINGS_UNVERIFIED = "[馆藏状态未实时核验]"
LABEL_PARTIAL = "[部分结果不完整]"
LABEL_LOCATION_LIVE = "[架位信息已实时获取]"
LABEL_LOCATION_UNVERIFIED = "[架位信息未核验]"


def now_ts() -> int:
    return int(time.time())


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def iso_from_ts(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).astimezone().isoformat(timespec="seconds")


def clean(value: Optional[str]) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<script.*?</script>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<style.*?</style>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def safe_key(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
    slug = re.sub(r"[^0-9A-Za-z._-]+", "_", value)[:40].strip("_")
    return f"{slug}_{digest}" if slug else digest


@dataclass(frozen=True)
class CacheLookup:
    data: Optional[Any]
    hit: bool
    cached_at: Optional[int] = None
    cached_at_iso: Optional[str] = None

    @property
    def age_seconds(self) -> Optional[int]:
        if self.cached_at is None:
            return None
        return max(0, now_ts() - self.cached_at)


@dataclass
class Cache:
    root: Path
    enabled: bool = True
    refresh: bool = False
    write_errors: list[dict[str, str]] = field(default_factory=list)

    def path(self, namespace: str, key: str) -> Path:
        return self.root / namespace / f"{safe_key(key)}.json"

    def get(self, namespace: str, key: str, ttl: int) -> CacheLookup:
        if not self.enabled or self.refresh:
            return CacheLookup(None, False)
        path = self.path(namespace, key)
        if not path.exists():
            return CacheLookup(None, False)
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                return CacheLookup(None, False)
            cached_at = int(payload.get("cached_at", 0))
            current_time = now_ts()
            if (
                cached_at <= 0
                or cached_at > current_time + 300
                or current_time - cached_at > ttl
            ):
                return CacheLookup(None, False, cached_at or None)
            cached_at_iso = iso_from_ts(cached_at)
            return CacheLookup(payload.get("data"), True, cached_at, cached_at_iso)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return CacheLookup(None, False)

    def set(
        self,
        namespace: str,
        key: str,
        data: Any,
        *,
        cached_at: Optional[int] = None,
    ) -> str:
        timestamp = cached_at if cached_at is not None else now_ts()
        cached_at_iso = iso_from_ts(timestamp)
        if not self.enabled:
            return cached_at_iso

        path = self.path(namespace, key)
        temporary_path: Optional[Path] = None
        file_descriptor = -1
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "cache_version": 2,
                "namespace": namespace,
                "cached_at": timestamp,
                "cached_at_iso": cached_at_iso,
                "data": data,
            }
            encoded = json.dumps(payload, ensure_ascii=False, indent=2)
            file_descriptor, temporary_name = tempfile.mkstemp(
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            handle = os.fdopen(file_descriptor, "w", encoding="utf-8")
            file_descriptor = -1
            with handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        except (OSError, TypeError, ValueError) as error:
            self.write_errors.append(
                {
                    "namespace": namespace,
                    "key": safe_key(key),
                    "error": str(error),
                }
            )
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
        return cached_at_iso


class RequestClient:
    def __init__(
        self,
        *,
        delay: float = DEFAULT_REQUEST_DELAY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff: float = DEFAULT_RETRY_BACKOFF,
        timeout: float = DEFAULT_TIMEOUT,
        opener: Optional[Callable[..., Any]] = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        events: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self.delay = max(0.0, delay)
        self.max_retries = max(0, max_retries)
        self.backoff = max(0.0, backoff)
        self.timeout = timeout
        self.opener = opener or urllib.request.urlopen
        self.sleeper = sleeper
        self.monotonic = monotonic
        self.events = events if events is not None else []
        self._last_request_at: Optional[float] = None

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            remaining = self.delay - (self.monotonic() - self._last_request_at)
            if remaining > 0:
                self.sleeper(remaining)
        self._last_request_at = self.monotonic()

    @staticmethod
    def _retry_after(error: urllib.error.HTTPError) -> Optional[float]:
        value = error.headers.get("Retry-After") if error.headers else None
        try:
            return max(0.0, float(value)) if value is not None else None
        except (TypeError, ValueError):
            return None

    def request(
        self,
        url: str,
        data: Optional[bytes] = None,
        content_type: Optional[str] = None,
    ) -> bytes:
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": urllib.parse.urljoin(BASE, "search_adv.php#/index"),
        }
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=data, headers=headers)

        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                retryable = error.code in RETRYABLE_HTTP_STATUS
                if not retryable or attempt >= self.max_retries:
                    self.events.append(
                        {
                            "event": "request_failed",
                            "url": url,
                            "attempt": attempt + 1,
                            "error": f"HTTP {error.code}",
                            "retryable": retryable,
                        }
                    )
                    error.close()
                    raise
                retry_after = self._retry_after(error)
                wait_seconds = max(
                    self.backoff * (2**attempt),
                    retry_after if retry_after is not None else 0.0,
                )
                self.events.append(
                    {
                        "event": "request_retry",
                        "url": url,
                        "attempt": attempt + 1,
                        "error": f"HTTP {error.code}",
                        "wait_seconds": wait_seconds,
                    }
                )
                error.close()
                self.sleeper(wait_seconds)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
                if attempt >= self.max_retries:
                    self.events.append(
                        {
                            "event": "request_failed",
                            "url": url,
                            "attempt": attempt + 1,
                            "error": str(error),
                            "retryable": True,
                        }
                    )
                    raise
                wait_seconds = self.backoff * (2**attempt)
                self.events.append(
                    {
                        "event": "request_retry",
                        "url": url,
                        "attempt": attempt + 1,
                        "error": str(error),
                        "wait_seconds": wait_seconds,
                    }
                )
                self.sleeper(wait_seconds)
        raise RuntimeError("request retry loop ended unexpectedly")

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = urllib.parse.urljoin(BASE, path)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        raw = self.request(url, body, "application/json")
        return json.loads(raw.decode("utf-8-sig", "replace"))

    def get_text(self, url: str) -> str:
        return self.request(url).decode("utf-8-sig", "replace")


class DLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_dt = False
        self.in_dd = False
        self.current_dt: list[str] = []
        self.current_dd: list[str] = []
        self.pending_key: Optional[str] = None
        self.fields: list[tuple[str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[Tuple[str, Optional[str]]],
    ) -> None:
        if tag.lower() == "dt":
            self.in_dt = True
            self.current_dt = []
        elif tag.lower() == "dd":
            self.in_dd = True
            self.current_dd = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "dt":
            self.in_dt = False
            self.pending_key = clean("".join(self.current_dt)).rstrip(":：")
        elif tag.lower() == "dd":
            self.in_dd = False
            if self.pending_key:
                self.fields.append((self.pending_key, clean("".join(self.current_dd))))
            self.pending_key = None

    def handle_data(self, data: str) -> None:
        if self.in_dt:
            self.current_dt.append(data)
        elif self.in_dd:
            self.current_dd.append(data)


class HoldingsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_holding_row = False
        self.in_cell = False
        self.current_cell: list[str] = []
        self.cells: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[Tuple[str, Optional[str]]],
    ) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "tr":
            classes = set(attributes.get("class", "").lower().split())
            self.in_holding_row = "whitetext" in classes or "data-holding" in classes
            self.cells = []
        elif tag.lower() == "td" and self.in_holding_row:
            self.in_cell = True
            self.current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "td" and self.in_cell:
            self.cells.append(clean("".join(self.current_cell)))
            self.in_cell = False
        elif tag.lower() == "tr" and self.in_holding_row:
            if self.cells:
                self.rows.append(self.cells)
            self.in_holding_row = False

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell.append(data)


def parse_metadata(page: str, detail_url: str) -> dict[str, Any]:
    parser = DLParser()
    parser.feed(page)
    fields: dict[str, str] = {}
    repeated: dict[str, list[str]] = {}
    for key, value in parser.fields:
        if key in fields:
            repeated.setdefault(key, [fields[key]]).append(value)
        else:
            fields[key] = value
    return {
        "detail_url": detail_url,
        "fields": fields,
        "repeated_fields": repeated,
    }


def parse_holdings(page: str) -> list[dict[str, str]]:
    parser = HoldingsParser()
    parser.feed(page)
    holdings: list[dict[str, str]] = []
    for cells in parser.rows:
        if len(cells) < 5:
            continue
        values = [value.replace("（图书定位）", "").strip() for value in cells[:5]]
        holdings.append(
            {
                "call_no": values[0],
                "barcode": values[1],
                "volume": values[2],
                "location": values[3],
                "status": values[4],
            }
        )
    return holdings


def holdings_response_verified(page: str, holdings: list[dict[str, str]]) -> bool:
    if holdings:
        return True
    normalized = clean(page).lower()
    empty_markers = (
        "暂无馆藏",
        "无馆藏信息",
        "没有馆藏",
        "馆藏信息为空",
    )
    return any(marker in normalized for marker in empty_markers)


def _table_value(page: str, label: str) -> str:
    pattern = (
        r'<td[^>]*class=["\'][^"\']*\btd1\b[^"\']*["\'][^>]*>\s*'
        + re.escape(label)
        + r"\s*</td>\s*"
        r'<td[^>]*class=["\'][^"\']*\btd2\b[^"\']*["\'][^>]*>(.*?)</td>'
    )
    match = re.search(pattern, page, flags=re.S | re.I)
    return clean(match.group(1)) if match else ""


def parse_shelf_location(page: str, barcode: str, url: str) -> dict[str, str]:
    message = re.search(
        r'<div[^>]*id=["\']lmsg["\'][^>]*>(.*?)</div>',
        page,
        flags=re.S | re.I,
    )
    return {
        "barcode": barcode,
        "navigation_url": url,
        "navigation_location": clean(message.group(1)) if message else "",
        "shelf_code": _table_value(page, "架位号:"),
        "navigation_title": _table_value(page, "书名:"),
    }


def provenance(source: str, verified_at: Optional[str], label: str) -> dict[str, Any]:
    return {
        "source": source,
        "cached": source == "cache",
        "verified_at": verified_at,
        "label": label,
    }


def holdings_label(source: str) -> str:
    if source == "live":
        return LABEL_HOLDINGS_LIVE
    if source == "cache":
        return f"{LABEL_HOLDINGS_CACHE} {LABEL_HOLDINGS_UNVERIFIED}"
    return LABEL_HOLDINGS_UNVERIFIED


def annotate_holdings(
    holdings: list[dict[str, str]],
    holdings_provenance: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            **holding,
            "status_source": holdings_provenance["source"],
            "status_cached": holdings_provenance["cached"],
            "status_verified_at": holdings_provenance["verified_at"],
            "status_label": holdings_provenance["label"],
        }
        for holding in holdings
    ]


@dataclass
class DetailResult:
    data: dict[str, Any]
    metadata_provenance: dict[str, Any]
    holdings_provenance: dict[str, Any]
    error: Optional[str] = None
    attempted_live: bool = False


@dataclass
class LocationResult:
    data: dict[str, str]
    provenance: dict[str, Any]
    error: Optional[str] = None
    attempted_live: bool = False


def _clean_legacy_metadata(
    marc_no: str,
    cache: Cache,
    metadata: CacheLookup,
    holdings: CacheLookup,
) -> tuple[Optional[dict[str, Any]], CacheLookup]:
    if not metadata.hit or not isinstance(metadata.data, dict):
        return None, holdings

    cleaned = dict(metadata.data)
    legacy_holdings = cleaned.pop("holdings", None)
    if legacy_holdings is None:
        return cleaned, holdings

    if (
        not holdings.hit
        and isinstance(legacy_holdings, list)
        and metadata.age_seconds is not None
        and metadata.age_seconds <= CACHE_TTL["holdings"]
    ):
        cache.set("holdings", marc_no, legacy_holdings, cached_at=metadata.cached_at)
        migrated_holdings = cache.get("holdings", marc_no, CACHE_TTL["holdings"])
        if not migrated_holdings.hit:
            return cleaned, holdings
        holdings = migrated_holdings
    cache.set("metadata", marc_no, cleaned, cached_at=metadata.cached_at)
    return cleaned, holdings


def search_keyword(
    keyword: str,
    page_size: int,
    cache: Cache,
    client: RequestClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cache_key = json.dumps({"keyword": keyword, "page_size": page_size}, ensure_ascii=False)
    cached = cache.get("search", cache_key, CACHE_TTL["search"])
    if cached.hit and isinstance(cached.data, dict):
        return cached.data, provenance("cache", cached.cached_at_iso, LABEL_SEARCH_CACHE)

    payload = {
        "searchWords": [{"fieldList": [{"fieldCode": "any", "fieldValue": keyword}]}],
        "filters": [],
        "unionFilters": [],
        "limiter": [],
        "sortField": "pubYear",
        "sortType": "desc",
        "locale": "zh_CN",
        "pageSize": page_size,
        "pageCount": 1,
        "first": True,
    }
    data = client.post_json("ajax_search_adv.php", payload)
    verified_at = cache.set("search", cache_key, data)
    return data, provenance("live", verified_at, "[检索结果已实时获取]")


def detail_record(marc_no: str, cache: Cache, client: RequestClient) -> DetailResult:
    detail_url = urllib.parse.urljoin(
        BASE,
        "item.php?marc_no=" + urllib.parse.quote(marc_no),
    )
    metadata_lookup = cache.get("metadata", marc_no, CACHE_TTL["metadata"])
    holdings_lookup = cache.get("holdings", marc_no, CACHE_TTL["holdings"])
    if metadata_lookup.hit and not isinstance(metadata_lookup.data, dict):
        metadata_lookup = CacheLookup(None, False)
    if holdings_lookup.hit and not isinstance(holdings_lookup.data, list):
        holdings_lookup = CacheLookup(None, False)
    metadata_data, holdings_lookup = _clean_legacy_metadata(
        marc_no,
        cache,
        metadata_lookup,
        holdings_lookup,
    )

    if metadata_lookup.hit and holdings_lookup.hit:
        holdings_data = holdings_lookup.data if isinstance(holdings_lookup.data, list) else []
        holdings_provenance = provenance(
            "cache",
            holdings_lookup.cached_at_iso,
            holdings_label("cache"),
        )
        return DetailResult(
            data={
                **(metadata_data or {"detail_url": detail_url, "fields": {}, "repeated_fields": {}}),
                "holdings": annotate_holdings(holdings_data, holdings_provenance),
            },
            metadata_provenance=provenance(
                "cache",
                metadata_lookup.cached_at_iso,
                LABEL_METADATA_CACHE,
            ),
            holdings_provenance=holdings_provenance,
        )

    try:
        page = client.get_text(detail_url)
    except Exception as error:
        metadata_provenance = (
            provenance("cache", metadata_lookup.cached_at_iso, LABEL_METADATA_CACHE)
            if metadata_lookup.hit
            else provenance("unverified", None, "[书目未核验]")
        )
        holdings_provenance = (
            provenance("cache", holdings_lookup.cached_at_iso, holdings_label("cache"))
            if holdings_lookup.hit
            else provenance("unverified", None, holdings_label("unverified"))
        )
        holdings_data = holdings_lookup.data if isinstance(holdings_lookup.data, list) else []
        return DetailResult(
            data={
                **(metadata_data or {"detail_url": detail_url, "fields": {}, "repeated_fields": {}}),
                "holdings": annotate_holdings(holdings_data, holdings_provenance),
            },
            metadata_provenance=metadata_provenance,
            holdings_provenance=holdings_provenance,
            error=str(error),
            attempted_live=True,
        )

    timestamp = now_ts()
    metadata_data = parse_metadata(page, detail_url)
    holdings_data = parse_holdings(page)
    verified_at = cache.set("metadata", marc_no, metadata_data, cached_at=timestamp)
    if not holdings_response_verified(page, holdings_data):
        holdings_provenance = provenance(
            "unverified",
            None,
            holdings_label("unverified"),
        )
        return DetailResult(
            data={
                **metadata_data,
                "holdings": [],
            },
            metadata_provenance=provenance("live", verified_at, "[书目已实时获取]"),
            holdings_provenance=holdings_provenance,
            error="holdings markup was not recognized and no empty-holdings marker was found",
            attempted_live=True,
        )
    cache.set("holdings", marc_no, holdings_data, cached_at=timestamp)
    holdings_provenance = provenance("live", verified_at, holdings_label("live"))
    return DetailResult(
        data={
            **metadata_data,
            "holdings": annotate_holdings(holdings_data, holdings_provenance),
        },
        metadata_provenance=provenance("live", verified_at, "[书目已实时获取]"),
        holdings_provenance=holdings_provenance,
        attempted_live=True,
    )


def shelf_location(
    barcode: str,
    cache: Cache,
    client: RequestClient,
    *,
    allow_live: bool = True,
) -> LocationResult:
    cached = cache.get("location", barcode, CACHE_TTL["location"])
    if cached.hit and isinstance(cached.data, dict):
        return LocationResult(
            data=cached.data,
            provenance=provenance("cache", cached.cached_at_iso, LABEL_LOCATION_CACHE),
        )
    if not allow_live:
        return LocationResult(
            data={},
            provenance=provenance("unverified", None, LABEL_LOCATION_UNVERIFIED),
            error="maximum shelf-location request count reached",
        )

    url = NAV_BASE + urllib.parse.quote(barcode)
    try:
        page = client.get_text(url)
        data = parse_shelf_location(page, barcode, url)
        verified_at = cache.set("location", barcode, data)
        return LocationResult(
            data=data,
            provenance=provenance("live", verified_at, LABEL_LOCATION_LIVE),
            attempted_live=True,
        )
    except Exception as error:
        return LocationResult(
            data={},
            provenance=provenance("unverified", None, LABEL_LOCATION_UNVERIFIED),
            error=str(error),
            attempted_live=True,
        )


def _increment_source(source_log: dict[str, Any], namespace: str, source: str) -> None:
    source_log["provenance_counts"][namespace][source] += 1
    if source == "cache":
        source_log["cache_hits"][namespace] += 1


def _record_failure(
    source_log: dict[str, Any],
    step: str,
    error: str,
    **context: Any,
) -> None:
    source_log["failures"].append({"step": step, **context, "error": error})


def collect(
    config: dict[str, Any],
    cache: Cache,
    client: Optional[RequestClient] = None,
    *,
    max_records: Optional[int] = None,
    max_location_requests: Optional[int] = None,
) -> dict[str, Any]:
    validate_config(config)
    keywords = config["keywords"]
    page_size = min(MAX_PAGE_SIZE, max(1, int(config.get("max_results_per_keyword", 50))))
    include_locations = bool(config.get("include_shelf_locations", True))
    record_limit = max_records if max_records is not None else int(
        config.get("max_records", DEFAULT_MAX_RECORDS)
    )
    location_limit = (
        max_location_requests
        if max_location_requests is not None
        else int(config.get("max_location_requests", DEFAULT_MAX_LOCATION_REQUESTS))
    )
    request_events: list[dict[str, Any]] = []
    client = client or RequestClient(
        delay=float(config.get("request_delay_seconds", DEFAULT_REQUEST_DELAY)),
        max_retries=int(config.get("max_retries", DEFAULT_MAX_RETRIES)),
        events=request_events,
    )
    if client.events is not request_events:
        request_events = client.events

    source_log: dict[str, Any] = {
        "collected_at": iso_now(),
        "opac_base": BASE,
        "navigation_base": NAV_BASE,
        "keywords": keywords,
        "cache_enabled": cache.enabled,
        "cache_write_errors": cache.write_errors,
        "cache_ttl_days": {"search": 30, "metadata": 30, "holdings": 3, "location": 30},
        "cache_hits": {"search": 0, "metadata": 0, "holdings": 0, "location": 0},
        "provenance_counts": {
            namespace: {"live": 0, "cache": 0, "unverified": 0}
            for namespace in ("search", "metadata", "holdings", "location")
        },
        "request_policy": {
            "delay_seconds": client.delay,
            "max_retries": client.max_retries,
            "retry_backoff_seconds": client.backoff,
            "timeout_seconds": client.timeout,
            "max_records": record_limit,
            "max_location_requests": location_limit,
        },
        "request_events": request_events,
        "failures": [],
    }
    keyword_totals: dict[str, int] = {}
    records_by_marc: dict[str, dict[str, Any]] = {}

    for keyword in keywords:
        try:
            result, search_provenance = search_keyword(keyword, page_size, cache, client)
            _increment_source(source_log, "search", search_provenance["source"])
            keyword_totals[keyword] = int(result.get("total", 0) or 0)
            for item in result.get("content", []):
                if not isinstance(item, dict):
                    continue
                marc = str(item.get("marcRecNo") or "").strip()
                if not marc:
                    continue
                record = records_by_marc.setdefault(marc, dict(item))
                record.setdefault("matched_keywords", []).append(keyword)
                record.setdefault("search_provenance", []).append(search_provenance)
        except Exception as error:
            _increment_source(source_log, "search", "unverified")
            _record_failure(source_log, "search", str(error), keyword=keyword)

    discovered_count = len(records_by_marc)
    selected_records = list(records_by_marc.items())[: max(0, record_limit)]
    source_log["records_discovered"] = discovered_count
    source_log["records_processed"] = len(selected_records)
    source_log["records_truncated"] = discovered_count > len(selected_records)

    location_live_requests = 0
    for marc, record in selected_records:
        result = detail_record(marc, cache, client)
        record.update(result.data)
        record["metadata_provenance"] = result.metadata_provenance
        record["holdings_provenance"] = result.holdings_provenance
        _increment_source(source_log, "metadata", result.metadata_provenance["source"])
        _increment_source(source_log, "holdings", result.holdings_provenance["source"])
        if result.error:
            record["detail_error"] = result.error
            _record_failure(source_log, "detail", result.error, marc_no=marc)

        if not include_locations:
            continue
        for holding in record.get("holdings", []):
            barcode = str(holding.get("barcode") or "").strip()
            if not barcode:
                continue
            location = shelf_location(
                barcode,
                cache,
                client,
                allow_live=location_live_requests < max(0, location_limit),
            )
            if location.attempted_live:
                location_live_requests += 1
            _increment_source(source_log, "location", location.provenance["source"])
            holding["navigation_provenance"] = location.provenance
            if location.data:
                holding["navigation"] = location.data
            if location.error:
                holding["navigation_error"] = location.error
                _record_failure(source_log, "location", location.error, barcode=barcode)

    records = [record for _, record in selected_records]
    records.sort(
        key=lambda record: (
            str(record.get("pubYear", "")),
            len(record.get("matched_keywords", [])),
        ),
        reverse=True,
    )
    source_log["location_live_requests"] = location_live_requests
    return {
        "schema_version": "1.0",
        "profile": config.get("profile", {}),
        "keyword_totals": keyword_totals,
        "records": records,
        "source_log": source_log,
        "labels": labels_for_result(source_log),
    }


def labels_for_result(source_log: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    counts = source_log.get("provenance_counts", {})
    if counts.get("search", {}).get("cache", 0):
        labels.append(LABEL_SEARCH_CACHE)
    if counts.get("metadata", {}).get("cache", 0):
        labels.append(LABEL_METADATA_CACHE)
    if counts.get("holdings", {}).get("cache", 0):
        labels.extend([LABEL_HOLDINGS_CACHE, LABEL_HOLDINGS_UNVERIFIED])
    if counts.get("location", {}).get("cache", 0):
        labels.append(LABEL_LOCATION_CACHE)
    if counts.get("holdings", {}).get("live", 0):
        labels.append(LABEL_HOLDINGS_LIVE)
    if counts.get("holdings", {}).get("unverified", 0) and LABEL_HOLDINGS_UNVERIFIED not in labels:
        labels.append(LABEL_HOLDINGS_UNVERIFIED)
    if source_log.get("failures") or source_log.get("records_truncated"):
        labels.append(LABEL_PARTIAL)
    return labels


def flatten_record(record: dict[str, Any]) -> dict[str, str]:
    fields = record.get("fields", {})
    holdings = record.get("holdings", [])
    statuses = sorted({holding.get("status", "") for holding in holdings if holding.get("status")})
    locations = sorted(
        {holding.get("location", "") for holding in holdings if holding.get("location")}
    )
    navigation_locations = [
        holding.get("navigation", {}).get("navigation_location", "")
        for holding in holdings
        if holding.get("navigation", {}).get("navigation_location")
    ]
    location_sources = sorted(
        {
            holding.get("navigation_provenance", {}).get("source", "")
            for holding in holdings
            if holding.get("navigation_provenance", {}).get("source")
        }
    )
    metadata_provenance = record.get("metadata_provenance", {})
    holdings_provenance = record.get("holdings_provenance", {})
    return {
        "title": str(record.get("title", "")),
        "author": str(record.get("author", "")),
        "publisher": str(record.get("publisher", "")),
        "year": str(record.get("pubYear", "")),
        "call_no": str(record.get("callNo", "")),
        "matched_keywords": "; ".join(record.get("matched_keywords", [])),
        "holdings_count": str(len(holdings)),
        "locations": "; ".join(locations),
        "statuses": "; ".join(statuses),
        "status_source": str(holdings_provenance.get("source", "unverified")),
        "status_verified_at": str(holdings_provenance.get("verified_at") or ""),
        "status_label": str(holdings_provenance.get("label", LABEL_HOLDINGS_UNVERIFIED)),
        "metadata_source": str(metadata_provenance.get("source", "unverified")),
        "navigation_locations": "; ".join(navigation_locations[:5]),
        "location_sources": "; ".join(location_sources),
        "subject": str(fields.get("学科主题", "")),
        "abstract": str(fields.get("提要文摘附注", "")),
        "detail_url": str(record.get("detail_url", "")),
    }


def write_json(data: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(data: dict[str, Any], path: Path) -> None:
    rows = [flatten_record(record) for record in data.get("records", [])]
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(data: dict[str, Any], path: Path) -> None:
    lines = ["# OPAC Survey Collection", ""]
    labels = " ".join(data.get("labels", []))
    if labels:
        lines += [f"Labels: {labels}", ""]
    lines += ["## Keyword Totals", ""]
    for keyword, total in data.get("keyword_totals", {}).items():
        lines.append(f"- {keyword}: {total}")
    lines += ["", "## Records", ""]
    for index, record in enumerate(data.get("records", []), 1):
        row = flatten_record(record)
        lines += [
            f"### {index}. {row['title']}",
            "",
            f"- Author: {row['author']}",
            f"- Publisher/year: {row['publisher']} {row['year']}",
            f"- Call number: {row['call_no']}",
            f"- Bibliographic source: {row['metadata_source']}",
            (
                f"- Holdings: {row['holdings_count']} | {row['statuses']} | "
                f"source={row['status_source']} | verified_at={row['status_verified_at'] or '未核验'}"
            ),
            f"- Status evidence: {row['status_label']}",
            f"- Locations: {row['locations']}",
        ]
        if row["navigation_locations"]:
            lines.append(
                f"- Navigation: {row['navigation_locations']} | source={row['location_sources']}"
            )
        if row["subject"]:
            lines.append(f"- Subject: {row['subject']}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def validate_config(config: dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise SystemExit("Input JSON must be an object.")
    allowed_keys = {
        "profile",
        "keywords",
        "max_results_per_keyword",
        "max_records",
        "max_location_requests",
        "include_shelf_locations",
        "use_cache",
        "refresh",
        "request_delay_seconds",
        "max_retries",
    }
    unknown_keys = sorted(set(config) - allowed_keys)
    if unknown_keys:
        raise SystemExit(f"Unknown input field(s): {', '.join(unknown_keys)}")
    profile = config.get("profile")
    if not isinstance(profile, dict):
        raise SystemExit("Input JSON must contain a 'profile' object.")
    allowed_profile_keys = {
        "school",
        "major",
        "stage",
        "goal",
        "purpose",
        "network",
        "output_depth",
    }
    unknown_profile_keys = sorted(set(profile) - allowed_profile_keys)
    if unknown_profile_keys:
        raise SystemExit(f"Unknown profile field(s): {', '.join(unknown_profile_keys)}")
    keywords = config.get("keywords")
    if not isinstance(keywords, list) or not keywords:
        raise SystemExit("Input JSON must contain a non-empty 'keywords' list.")
    if any(not isinstance(keyword, str) or not keyword.strip() for keyword in keywords):
        raise SystemExit("Every keyword must be a non-empty string.")
    if len(keywords) > 30:
        raise SystemExit("'keywords' must contain at most 30 entries.")
    if len(set(keywords)) != len(keywords):
        raise SystemExit("'keywords' entries must be unique.")
    for field, value in profile.items():
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"'profile.{field}' must be a non-empty string.")
    allowed_purposes = {"课程学习", "考研", "科研入门", "兴趣拓展", "职业技能"}
    if "purpose" in profile and profile["purpose"] not in allowed_purposes:
        raise SystemExit(
            "'profile.purpose' must be 课程学习, 考研, 科研入门, 兴趣拓展, or 职业技能."
        )
    allowed_networks = {"校园网", "学校 VPN", "校外未连接 VPN", "未知"}
    if "network" in profile and profile["network"] not in allowed_networks:
        raise SystemExit(
            "'profile.network' must be 校园网, 学校 VPN, 校外未连接 VPN, or 未知."
        )
    output_depth = (profile or {}).get("output_depth")
    if output_depth is not None and output_depth not in {"brief", "normal", "deep"}:
        raise SystemExit("'profile.output_depth' must be brief, normal, or deep.")
    numeric_ranges = {
        "max_results_per_keyword": (1, 100),
        "max_records": (1, 500),
        "max_location_requests": (0, 500),
        "max_retries": (0, 5),
    }
    for field, (minimum, maximum) in numeric_ranges.items():
        if field not in config:
            continue
        value = config[field]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise SystemExit(f"'{field}' must be an integer between {minimum} and {maximum}.")
    if "request_delay_seconds" in config:
        delay = config["request_delay_seconds"]
        if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not 0.2 <= delay <= 10:
            raise SystemExit("'request_delay_seconds' must be between 0.2 and 10.")
    for field in ("include_shelf_locations", "use_cache", "refresh"):
        if field in config and not isinstance(config[field], bool):
            raise SystemExit(f"'{field}' must be a boolean.")


def bounded_int(minimum: int, maximum: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        parsed = int(value)
        if not minimum <= parsed <= maximum:
            raise argparse.ArgumentTypeError(f"must be between {minimum} and {maximum}")
        return parsed

    return parse


def minimum_float(minimum: float) -> Callable[[str], float]:
    def parse(value: str) -> float:
        parsed = float(value)
        if parsed < minimum:
            raise argparse.ArgumentTypeError(f"must be at least {minimum}")
        return parsed

    return parse


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect Chengdu University OPAC evidence without making recommendations."
    )
    parser.add_argument("--input", required=True, help="Input JSON request.")
    parser.add_argument("--output", required=True, help="Output path.")
    parser.add_argument("--format", choices=["json", "csv", "md"], default="json")
    parser.add_argument(
        "--cache-dir",
        default=str(Path(__file__).resolve().parents[1] / "cache"),
    )
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--delay",
        type=minimum_float(0.2),
        default=None,
        help=f"Minimum seconds between OPAC requests (default: {DEFAULT_REQUEST_DELAY}).",
    )
    parser.add_argument(
        "--max-retries",
        type=bounded_int(0, 5),
        default=None,
        help=f"Retries for temporary failures (default: {DEFAULT_MAX_RETRIES}).",
    )
    parser.add_argument(
        "--max-records",
        type=bounded_int(1, 500),
        default=None,
        help=f"Maximum detail records per run (default: {DEFAULT_MAX_RECORDS}).",
    )
    parser.add_argument(
        "--max-location-requests",
        type=bounded_int(0, 500),
        default=None,
        help=(
            "Maximum live shelf-navigation requests per run "
            f"(default: {DEFAULT_MAX_LOCATION_REQUESTS})."
        ),
    )
    args = parser.parse_args(argv)

    config = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    validate_config(config)
    cache = Cache(
        Path(args.cache_dir),
        enabled=not args.no_cache and config.get("use_cache", True),
        refresh=args.refresh or config.get("refresh", False),
    )
    request_events: list[dict[str, Any]] = []
    client = RequestClient(
        delay=(
            args.delay
            if args.delay is not None
            else float(config.get("request_delay_seconds", DEFAULT_REQUEST_DELAY))
        ),
        max_retries=(
            args.max_retries
            if args.max_retries is not None
            else int(config.get("max_retries", DEFAULT_MAX_RETRIES))
        ),
        events=request_events,
    )
    data = collect(
        config,
        cache,
        client,
        max_records=args.max_records,
        max_location_requests=args.max_location_requests,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        write_json(data, output)
    elif args.format == "csv":
        write_csv(data, output)
    else:
        write_markdown(data, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
