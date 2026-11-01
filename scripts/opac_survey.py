#!/usr/bin/env python3
"""
Collect Chengdu University OPAC search results, details, holdings, and shelf
navigation data. The script is agent-neutral and uses only Python standard
library modules.

Input JSON:
{
  "profile": {"major": "专业名称", "stage": "年级或阶段", "goal": "学习或研究目标"},
  "keywords": ["关键词1", "关键词2"],
  "max_results_per_keyword": 50,
  "use_cache": true,
  "refresh": false
}

Transport security (issue #2): all remote pages are treated as untrusted
external input. The script enforces a URL allowlist (host + scheme + port),
prefers HTTPS with explicit logged HTTP fallback, validates every redirect
hop, and reads response bodies with a hard byte limit.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

BASE = "http://libopac.cdu.edu.cn/opac/"
NAV_BASE = "http://120.94.216.7:8080/navigationservice/bookcode/"
USER_AGENT = "Mozilla/5.0 (compatible; cdu-library-book-survey/1.0)"

# ---------------------------------------------------------------------------
# Transport security policy (issue #2).
#
# Remote OPAC pages are untrusted external input; the transport layer enforces:
#   1. a host allowlist with explicit schemes and ports (no other host --
#      including localhost or intranet addresses -- can ever be contacted);
#   2. HTTPS-first for the OPAC domain, with HTTP allowed only as an explicit,
#      logged downgrade because TLS support cannot be confirmed off-campus;
#   3. per-hop redirect validation: allowlisted hosts only, never an
#      HTTPS -> HTTP downgrade, and a bounded redirect count;
#   4. bounded response reads (no unbounded resp.read()).
# The navigation service is a raw CERNET IP without TLS; it serves public
# barcode navigation only. The script never sends accounts, cookies, or any
# personal data to either endpoint.
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT = 25  # seconds per socket operation
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
READ_CHUNK_SIZE = 64 * 1024

ALLOWED_HOSTS: dict[str, dict[str, Any]] = {
    "libopac.cdu.edu.cn": {"schemes": ("https", "http"), "ports": (80, 443), "https_first": True},
    "120.94.216.7": {"schemes": ("http",), "ports": (8080,), "https_first": False},
}


class TransportError(RuntimeError):
    """Base class for transport-policy violations."""


class HostNotAllowedError(TransportError):
    """Target host or port is not on the allowlist."""


class SchemeNotAllowedError(TransportError):
    """URL scheme is not allowed for the target host."""


class RedirectBlockedError(TransportError):
    """A redirect hop was rejected by policy."""


class ResponseTooLargeError(TransportError):
    """Response body exceeded the configured byte limit."""


class TransportUnavailableError(TransportError):
    """Network, TLS, or HTTP failure; callers should degrade gracefully."""


def validate_url(url: str, policy: dict[str, dict[str, Any]] | None = None) -> tuple[str, str, int]:
    """Return (scheme, host, port) for url, or raise a TransportError."""
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if parts.username or parts.password:
        raise HostNotAllowedError(f"Userinfo in URL is not allowed: {url!r}")
    rule = (policy if policy is not None else ALLOWED_HOSTS).get(host)
    if rule is None:
        raise HostNotAllowedError(f"Host not on the allowlist: {host!r} (url: {url!r})")
    if scheme not in rule["schemes"]:
        raise SchemeNotAllowedError(f"Scheme {scheme!r} is not allowed for host {host!r}")
    port = parts.port or (443 if scheme == "https" else 80)
    if port not in rule["ports"]:
        raise HostNotAllowedError(f"Port {port} is not allowed for host {host!r}")
    return scheme, host, port


class _PolicyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that validates every hop against the transport policy."""

    def __init__(self, max_redirects: int, policy: dict[str, dict[str, Any]] | None = None) -> None:
        super().__init__()
        self.max_redirects = max_redirects
        self.policy = policy if policy is not None else ALLOWED_HOSTS
        self.hops = 0

    def redirect_request(
        self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> urllib.request.Request | None:
        self.hops += 1
        try:
            if self.hops > self.max_redirects:
                raise RedirectBlockedError(
                    f"More than {self.max_redirects} redirects for {req.full_url!r}"
                )
            try:
                scheme, _host, _port = validate_url(newurl, self.policy)
                current_scheme = urllib.parse.urlsplit(req.full_url).scheme.lower()
                if current_scheme == "https" and scheme != "https":
                    raise RedirectBlockedError(f"HTTPS -> {scheme} downgrade blocked: {newurl!r}")
            except RedirectBlockedError:
                raise
            except TransportError as exc:
                raise RedirectBlockedError(f"Redirect to {newurl!r} rejected: {exc}") from exc
        finally:
            fp.close()
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Transport:
    """HTTPS-first HTTP client enforcing the URL allowlist and bounded reads."""

    def __init__(
        self,
        policy: dict[str, dict[str, Any]] | None = None,
        timeout: float = REQUEST_TIMEOUT,
        max_bytes: int = MAX_RESPONSE_BYTES,
        max_redirects: int = MAX_REDIRECTS,
    ) -> None:
        self.policy = policy if policy is not None else ALLOWED_HOSTS
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.pinned_scheme: dict[str, str] = {}
        self.downgrades: list[dict[str, str]] = []

    def _candidate_urls(self, url: str) -> list[tuple[str, str]]:
        """Ordered (reason, url) attempts applying the HTTPS-first policy."""
        scheme, host, _port = validate_url(url, self.policy)
        rule = self.policy[host]
        if scheme == "https" or not rule.get("https_first"):
            return [("request", url)]
        if self.pinned_scheme.get(host) == "http":
            return [("request", url)]
        parts = urllib.parse.urlsplit(url)
        https_netloc = f"{host}:{parts.port}" if parts.port is not None else host
        https_url = urllib.parse.urlunsplit(("https", https_netloc, parts.path, parts.query, parts.fragment))
        return [("https_probe", https_url), ("http_fallback", url)]

    def request(self, url: str, data: bytes | None = None, content_type: str | None = None) -> bytes:
        attempts = self._candidate_urls(url)
        last_error: TransportUnavailableError | None = None
        for reason, attempt_url in attempts:
            try:
                return self._single_request(attempt_url, data, content_type)
            except TransportUnavailableError as exc:
                last_error = exc
                if reason == "https_probe":
                    self._record_downgrade(attempt_url, str(exc))
                    continue
                raise
        raise last_error  # pragma: no cover - the loop always returns or raises

    def _record_downgrade(self, https_url: str, reason: str) -> None:
        host = urllib.parse.urlsplit(https_url).hostname or ""
        self.pinned_scheme[host] = "http"
        if not any(entry.get("host") == host for entry in self.downgrades):
            self.downgrades.append({"host": host, "from": "https", "to": "http", "reason": reason[:200]})

    def _single_request(self, url: str, data: bytes | None, content_type: str | None) -> bytes:
        validate_url(url, self.policy)
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": urllib.parse.urljoin(BASE, "search_adv.php#/index"),
        }
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, headers=headers)
        opener = urllib.request.build_opener(_PolicyRedirectHandler(self.max_redirects, self.policy))
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                return self._bounded_read(resp)
        except urllib.error.HTTPError as exc:
            exc.close()
            if 300 <= exc.code < 400:
                # The redirect machinery refused to follow (loop guard or cap).
                raise RedirectBlockedError(
                    f"Redirect for {url!r} was rejected: HTTP {exc.code} {exc.reason}"
                ) from exc
            raise TransportUnavailableError(f"HTTP {exc.code} {exc.reason} for {url!r}") from exc
        except OSError as exc:  # URLError, socket.timeout, ssl.SSLError, ...
            raise TransportUnavailableError(f"{type(exc).__name__} for {url!r}: {exc}") from exc

    def _bounded_read(self, resp: Any) -> bytes:
        length = resp.headers.get("Content-Length")
        if length and length.strip().isdigit() and int(length) > self.max_bytes:
            raise ResponseTooLargeError(
                f"Content-Length {length} exceeds the {self.max_bytes}-byte limit"
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = resp.read(READ_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > self.max_bytes:
                raise ResponseTooLargeError(f"Response body exceeds {self.max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)


TRANSPORT = Transport()

CACHE_TTL = {
    "search": 30 * 24 * 3600,
    "metadata": 30 * 24 * 3600,
    "location": 30 * 24 * 3600,
    "status": 3 * 24 * 3600,
}


def now_ts() -> int:
    return int(time.time())


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def clean(value: str | None) -> str:
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


@dataclass
class Cache:
    root: Path
    enabled: bool = True
    refresh: bool = False

    def path(self, namespace: str, key: str) -> Path:
        return self.root / namespace / f"{safe_key(key)}.json"

    def get(self, namespace: str, key: str, ttl: int) -> tuple[Any | None, bool]:
        if not self.enabled or self.refresh:
            return None, False
        path = self.path(namespace, key)
        if not path.exists():
            return None, False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            cached_at = int(payload.get("cached_at", 0))
            if now_ts() - cached_at > ttl:
                return None, False
            return payload.get("data"), True
        except Exception:
            return None, False

    def set(self, namespace: str, key: str, data: Any) -> None:
        if not self.enabled:
            return
        path = self.path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"cached_at": now_ts(), "cached_at_iso": iso_now(), "data": data}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class DLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_dt = False
        self.in_dd = False
        self.current_dt: list[str] = []
        self.current_dd: list[str] = []
        self.pending_key: str | None = None
        self.fields: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "dt":
            self.in_dt = True
            self.current_dt = []
        elif tag == "dd":
            self.in_dd = True
            self.current_dd = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "dt":
            self.in_dt = False
            self.pending_key = clean("".join(self.current_dt)).rstrip(":：")
        elif tag == "dd":
            self.in_dd = False
            if self.pending_key:
                self.fields.append((self.pending_key, clean("".join(self.current_dd))))
            self.pending_key = None

    def handle_data(self, data: str) -> None:
        if self.in_dt:
            self.current_dt.append(data)
        elif self.in_dd:
            self.current_dd.append(data)


def request(url: str, data: bytes | None = None, content_type: str | None = None) -> bytes:
    """Fetch url through the hardened transport (allowlist, bounded reads)."""
    return TRANSPORT.request(url, data, content_type)


def post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = urllib.parse.urljoin(BASE, path)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    raw = request(url, body, "application/json")
    return json.loads(raw.decode("utf-8", "replace"))


def get_text(url: str) -> str:
    raw = request(url)
    return raw.decode("utf-8", "replace")


def search_keyword(keyword: str, page_size: int, cache: Cache) -> tuple[dict[str, Any], bool]:
    cache_key = json.dumps({"keyword": keyword, "page_size": page_size}, ensure_ascii=False)
    cached, hit = cache.get("search", cache_key, CACHE_TTL["search"])
    if hit:
        return cached, True
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
    data = post_json("ajax_search_adv.php", payload)
    cache.set("search", cache_key, data)
    return data, False


def parse_holdings(page: str) -> list[dict[str, str]]:
    rows = re.findall(r'<tr[^>]*class="whitetext"[^>]*>(.*?)</tr>', page, flags=re.S | re.I)
    holdings: list[dict[str, str]] = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S | re.I)
        if len(cells) < 5:
            continue
        vals = [clean(cell).replace("（图书定位）", "").strip() for cell in cells[:5]]
        holdings.append(
            {
                "call_no": vals[0],
                "barcode": vals[1],
                "volume": vals[2],
                "location": vals[3],
                "status": vals[4],
            }
        )
    return holdings


def detail_record(marc_no: str, cache: Cache) -> tuple[dict[str, Any], bool]:
    cached, hit = cache.get("metadata", marc_no, CACHE_TTL["metadata"])
    if hit:
        return cached, True
    url = urllib.parse.urljoin(BASE, "item.php?marc_no=" + urllib.parse.quote(marc_no))
    page = get_text(url)
    parser = DLParser()
    parser.feed(page)
    fields: dict[str, str] = {}
    repeated: dict[str, list[str]] = {}
    for key, value in parser.fields:
        if key in fields:
            repeated.setdefault(key, [fields[key]]).append(value)
        else:
            fields[key] = value
    data = {
        "detail_url": url,
        "fields": fields,
        "repeated_fields": repeated,
        "holdings": parse_holdings(page),
    }
    cache.set("metadata", marc_no, data)
    return data, False


def shelf_location(barcode: str, cache: Cache) -> tuple[dict[str, str], bool]:
    cached, hit = cache.get("location", barcode, CACHE_TTL["location"])
    if hit:
        return cached, True
    url = NAV_BASE + urllib.parse.quote(barcode)
    page = get_text(url)
    lmsg = re.search(r'<div id="lmsg">(.*?)</div>', page, flags=re.S | re.I)
    shelf = re.search(
        r'<td class="td1">架位号:</td>\s*<td class="td2">(.*?)</td>',
        page,
        flags=re.S | re.I,
    )
    title = re.search(
        r'<td class="td1">书名:</td>\s*<td class="td2">(.*?)</td>',
        page,
        flags=re.S | re.I,
    )
    data = {
        "barcode": barcode,
        "navigation_url": url,
        "navigation_location": clean(lmsg.group(1)) if lmsg else "",
        "shelf_code": clean(shelf.group(1)) if shelf else "",
        "navigation_title": clean(title.group(1)) if title else "",
    }
    cache.set("location", barcode, data)
    return data, False


def collect(config: dict[str, Any], cache: Cache) -> dict[str, Any]:
    keywords = config.get("keywords") or []
    if not keywords:
        raise SystemExit("Input JSON must contain a non-empty 'keywords' list.")
    page_size = int(config.get("max_results_per_keyword", 50))
    include_locations = bool(config.get("include_shelf_locations", True))

    source_log: dict[str, Any] = {
        "collected_at": iso_now(),
        "opac_base": BASE,
        "navigation_base": NAV_BASE,
        "keywords": keywords,
        "cache_enabled": cache.enabled,
        "cache_hits": {"search": 0, "metadata": 0, "location": 0},
        "failures": [],
    }
    keyword_totals: dict[str, int] = {}
    records_by_marc: dict[str, dict[str, Any]] = {}

    for keyword in keywords:
        try:
            result, from_cache = search_keyword(keyword, page_size, cache)
            source_log["cache_hits"]["search"] += int(from_cache)
            keyword_totals[keyword] = int(result.get("total", 0) or 0)
            for item in result.get("content", []):
                marc = item.get("marcRecNo")
                if not marc:
                    continue
                record = records_by_marc.setdefault(marc, dict(item))
                record.setdefault("matched_keywords", []).append(keyword)
                record["search_cached"] = record.get("search_cached", False) or from_cache
        except Exception as exc:
            source_log["failures"].append({"step": "search", "keyword": keyword, "error": str(exc)})

    for marc, record in list(records_by_marc.items()):
        try:
            detail, from_cache = detail_record(marc, cache)
            source_log["cache_hits"]["metadata"] += int(from_cache)
            record.update(detail)
            record["detail_cached"] = from_cache
        except Exception as exc:
            record["detail_error"] = str(exc)
            source_log["failures"].append({"step": "detail", "marc_no": marc, "error": str(exc)})
            continue

        if include_locations:
            for holding in record.get("holdings", []):
                barcode = holding.get("barcode")
                if not barcode:
                    continue
                try:
                    nav, from_cache = shelf_location(barcode, cache)
                    source_log["cache_hits"]["location"] += int(from_cache)
                    holding["navigation"] = nav
                    holding["location_cached"] = from_cache
                except Exception as exc:
                    holding["navigation_error"] = str(exc)
                    source_log["failures"].append(
                        {"step": "location", "barcode": barcode, "error": str(exc)}
                    )

    records = list(records_by_marc.values())
    records.sort(key=lambda r: (str(r.get("pubYear", "")), len(r.get("matched_keywords", []))), reverse=True)
    # Snapshot after collection so downgrade records made during fetching are included.
    source_log["transport"] = {
        "max_response_bytes": TRANSPORT.max_bytes,
        "max_redirects": TRANSPORT.max_redirects,
        "allowed_hosts": sorted(TRANSPORT.policy),
        "downgrades": list(TRANSPORT.downgrades),
    }
    return {
        "profile": config.get("profile", {}),
        "keyword_totals": keyword_totals,
        "records": records,
        "source_log": source_log,
        "labels": labels_for_result(source_log),
    }


def labels_for_result(source_log: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    if sum(source_log.get("cache_hits", {}).values()) > 0:
        labels.append("[缓存数据]")
    if source_log.get("transport", {}).get("downgrades"):
        labels.append("[HTTP降级]")
    if source_log.get("failures"):
        labels.append("[未实时核验]")
    return labels


def flatten_record(record: dict[str, Any]) -> dict[str, str]:
    fields = record.get("fields", {})
    holdings = record.get("holdings", [])
    statuses = sorted({h.get("status", "") for h in holdings if h.get("status")})
    locations = sorted({h.get("location", "") for h in holdings if h.get("location")})
    navs = [
        h.get("navigation", {}).get("navigation_location", "")
        for h in holdings
        if h.get("navigation", {}).get("navigation_location")
    ]
    return {
        "title": record.get("title", ""),
        "author": record.get("author", ""),
        "publisher": record.get("publisher", ""),
        "year": record.get("pubYear", ""),
        "call_no": record.get("callNo", ""),
        "matched_keywords": "; ".join(record.get("matched_keywords", [])),
        "holdings_count": str(len(holdings)),
        "locations": "; ".join(locations),
        "statuses": "; ".join(statuses),
        "navigation_locations": "; ".join(navs[:5]),
        "subject": fields.get("学科主题", ""),
        "abstract": fields.get("提要文摘附注", ""),
        "detail_url": record.get("detail_url", ""),
    }


def write_json(data: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(data: dict[str, Any], path: Path) -> None:
    rows = [flatten_record(record) for record in data.get("records", [])]
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
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
    for i, record in enumerate(data.get("records", []), 1):
        row = flatten_record(record)
        lines += [
            f"### {i}. {row['title']}",
            "",
            f"- Author: {row['author']}",
            f"- Publisher/year: {row['publisher']} {row['year']}",
            f"- Call number: {row['call_no']}",
            f"- Holdings: {row['holdings_count']} | {row['statuses']}",
            f"- Locations: {row['locations']}",
        ]
        if row["navigation_locations"]:
            lines.append(f"- Navigation: {row['navigation_locations']}")
        if row["subject"]:
            lines.append(f"- Subject: {row['subject']}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect Chengdu University OPAC survey data.")
    parser.add_argument("--input", required=True, help="Input JSON request.")
    parser.add_argument("--output", required=True, help="Output path.")
    parser.add_argument("--format", choices=["json", "csv", "md"], default="json")
    parser.add_argument("--cache-dir", default=str(Path(__file__).resolve().parents[1] / "cache"))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)

    config = json.loads(Path(args.input).read_text(encoding="utf-8"))
    cache = Cache(Path(args.cache_dir), enabled=not args.no_cache and config.get("use_cache", True), refresh=args.refresh)
    data = collect(config, cache)

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
