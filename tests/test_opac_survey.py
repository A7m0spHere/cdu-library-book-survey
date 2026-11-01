#!/usr/bin/env python3
"""Regression tests for the hardened transport layer of opac_survey.py.

All tests run against a local mock HTTP server; no real network is touched.

Run from the repository root:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import email.message
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import opac_survey  # noqa: E402

SEARCH_PAYLOAD = {
    "total": 1,
    "content": [
        {
            "marcRecNo": "000123",
            "title": "Python编程：从入门到实践",
            "author": "[美] Eric Matthes 著",
            "publisher": "人民邮电出版社",
            "pubYear": "2020",
            "callNo": "TP311.561/42",
        }
    ],
}

DETAIL_HTML = """<html><body>
<dl>
<dt>题名/责任者:</dt><dd>Python编程：从入门到实践 / [美] Eric Matthes 著</dd>
<dt>学科主题:</dt><dd>软件工程-程序设计</dd>
<dt>提要文摘附注:</dt><dd>一本面向初学者的 Python 入门书。</dd>
</dl>
<table>
<tr class="whitetext"><td>TP311.561/42</td><td>31500001234</td><td></td>
<td>第三藏书室（图书定位）</td><td>可借</td></tr>
</table>
</body></html>"""

NAV_HTML = """<html><body>
<div id="lmsg">图书馆A栋3楼第三藏书室 3排A面2列5层</div>
<table>
<tr><td class="td1">架位号:</td><td class="td2">3A-2-5</td></tr>
<tr><td class="td1">书名:</td><td class="td2">Python编程：从入门到实践</td></tr>
</table>
</body></html>"""


class _MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # silence request logging
        pass

    def _respond(self, code: int, body: bytes, content_type: str = "text/html; charset=utf-8",
                 content_length: int | None = None, extra: list[tuple[str, str]] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length if content_length is not None else len(body)))
        for name, value in extra or []:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if self.path == "/opac/ajax_search_adv.php":
            self._respond(200, json.dumps(SEARCH_PAYLOAD, ensure_ascii=False).encode("utf-8"), "application/json")
        else:
            self._respond(404, b"not found")

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/opac/item.php":
            self._respond(200, DETAIL_HTML.encode("utf-8"))
        elif path.startswith("/nav/"):
            self._respond(200, NAV_HTML.encode("utf-8"))
        elif path == "/ok":
            self._respond(200, b"hello")
        elif path == "/moved":
            self._respond(302, b"", extra=[("Location", "/ok")])
        elif path == "/redirect/evil":
            self._respond(302, b"", extra=[("Location", "http://evil.example.com/")])
        elif path == "/loop":
            self._respond(302, b"", extra=[("Location", "/loop")])
        elif path == "/big":
            self._respond(200, b"x" * 20000)
        elif path == "/cl-huge":
            self._respond(200, b"tiny", content_length=999999999)
        else:
            self._respond(404, b"not found")


class TransportTestBase(unittest.TestCase):
    """Starts a local mock server and installs an isolated transport."""

    max_bytes = opac_survey.MAX_RESPONSE_BYTES
    https_first = True
    schemes = ("https", "http")

    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
        self.port = self.server.server_port
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        policy = {"127.0.0.1": {"schemes": self.schemes, "ports": (self.port,), "https_first": self.https_first}}
        self.transport = opac_survey.Transport(policy=policy, timeout=5, max_bytes=self.max_bytes)
        self._originals = (opac_survey.TRANSPORT, opac_survey.BASE, opac_survey.NAV_BASE)
        opac_survey.TRANSPORT = self.transport
        opac_survey.BASE = f"http://127.0.0.1:{self.port}/opac/"
        opac_survey.NAV_BASE = f"http://127.0.0.1:{self.port}/nav/"

    def tearDown(self) -> None:
        opac_survey.TRANSPORT, opac_survey.BASE, opac_survey.NAV_BASE = self._originals
        self.server.shutdown()
        self.server.server_close()

    def base(self, scheme: str = "http") -> str:
        return f"{scheme}://127.0.0.1:{self.port}"


class EndpointToEndToEndTest(TransportTestBase):
    https_first = False  # functional test: no TLS probing noise on the plain-HTTP mock

    def test_normal_search_detail_and_navigation(self) -> None:
        cache = opac_survey.Cache(Path(tempfile.mkdtemp()), enabled=False)
        config = {"keywords": ["python"], "include_shelf_locations": True, "use_cache": False}
        result = opac_survey.collect(config, cache)

        self.assertEqual(result["source_log"]["failures"], [])
        self.assertEqual(result["keyword_totals"], {"python": 1})
        record = result["records"][0]
        self.assertEqual(record["fields"]["学科主题"], "软件工程-程序设计")
        self.assertEqual(record["fields"]["提要文摘附注"], "一本面向初学者的 Python 入门书。")
        holding = record["holdings"][0]
        self.assertEqual(holding["call_no"], "TP311.561/42")
        self.assertEqual(holding["location"], "第三藏书室")
        self.assertEqual(holding["status"], "可借")
        self.assertEqual(holding["navigation"]["shelf_code"], "3A-2-5")
        self.assertEqual(holding["navigation"]["navigation_title"], "Python编程：从入门到实践")
        self.assertNotIn("[HTTP降级]", result["labels"])  # https_first disabled for this test

    def test_same_host_redirect_is_allowed(self) -> None:
        self.assertEqual(self.transport.request(f"{self.base()}/moved"), b"hello")


class TransportPolicyTest(TransportTestBase):
    def test_default_policy_blocks_localhost_and_arbitrary_hosts(self) -> None:
        for url in ("http://127.0.0.1:9/x", "http://localhost/x", "http://evil.example.com/x"):
            with self.assertRaises(opac_survey.HostNotAllowedError):
                opac_survey.Transport().request(url)

    def test_default_policy_blocks_nav_https(self) -> None:
        with self.assertRaises(opac_survey.SchemeNotAllowedError):
            opac_survey.Transport().request("https://120.94.216.7:8080/navigationservice/bookcode/1")

    def test_userinfo_in_url_is_rejected(self) -> None:
        with self.assertRaises(opac_survey.HostNotAllowedError):
            self.transport.request(f"http://user:pass@127.0.0.1:{self.port}/ok")

    def test_cross_site_redirect_is_blocked(self) -> None:
        with self.assertRaises(opac_survey.RedirectBlockedError):
            self.transport.request(f"{self.base()}/redirect/evil")

    def test_redirect_loop_is_capped(self) -> None:
        with self.assertRaises(opac_survey.RedirectBlockedError):
            self.transport.request(f"{self.base()}/loop")

    def test_https_to_http_redirect_is_blocked(self) -> None:
        handler = opac_survey._PolicyRedirectHandler(max_redirects=5, policy=self.transport.policy)
        req = urllib.request.Request(f"https://127.0.0.1:{self.port}/opac/x")
        headers = email.message.Message()
        headers["Location"] = f"http://127.0.0.1:{self.port}/ok"
        with self.assertRaises(opac_survey.RedirectBlockedError):
            handler.redirect_request(req, io.BytesIO(), 302, "Found", headers, f"http://127.0.0.1:{self.port}/ok")


class BoundedReadTest(TransportTestBase):
    max_bytes = 1024

    def test_oversized_body_is_rejected(self) -> None:
        with self.assertRaises(opac_survey.ResponseTooLargeError):
            self.transport.request(f"{self.base()}/big")

    def test_huge_content_length_is_rejected_before_read(self) -> None:
        with self.assertRaises(opac_survey.ResponseTooLargeError):
            self.transport.request(f"{self.base()}/cl-huge")


class HttpsFirstTest(TransportTestBase):
    """The mock server speaks plain HTTP, so the HTTPS probe must fail."""

    def test_tls_failure_downgrades_to_http_and_is_logged(self) -> None:
        self.assertEqual(self.transport.request(f"{self.base()}/ok"), b"hello")
        self.assertEqual(self.transport.pinned_scheme.get("127.0.0.1"), "http")
        self.assertEqual(len(self.transport.downgrades), 1)
        self.assertEqual(self.transport.downgrades[0]["host"], "127.0.0.1")
        # Once pinned, later requests skip the probe entirely.
        self.assertEqual(self.transport.downgrades[0]["from"], "https")
        self.assertEqual(self.transport.request(f"{self.base()}/ok"), b"hello")
        self.assertEqual(len(self.transport.downgrades), 1)

    def test_downgrade_label_reaches_source_log(self) -> None:
        cache = opac_survey.Cache(Path(tempfile.mkdtemp()), enabled=False)
        result = opac_survey.collect({"keywords": ["python"], "use_cache": False}, cache)
        self.assertIn("[HTTP降级]", result["labels"])
        self.assertTrue(result["source_log"]["transport"]["downgrades"])


class HttpsOnlyPolicyTest(TransportTestBase):
    schemes = ("https",)
    https_first = False

    def test_http_request_rejected_by_scheme_policy(self) -> None:
        with self.assertRaises(opac_survey.SchemeNotAllowedError):
            self.transport.request(f"{self.base()}/ok")

    def test_tls_failure_raises_transport_unavailable(self) -> None:
        with self.assertRaises(opac_survey.TransportUnavailableError):
            self.transport.request(f"https://127.0.0.1:{self.port}/ok")
        self.assertEqual(self.transport.downgrades, [])


class CacheFallbackTest(unittest.TestCase):
    def test_cache_serves_when_network_is_down(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = opac_survey.Cache(Path(tmp), enabled=True)
            key = json.dumps({"keyword": "python", "page_size": 50}, ensure_ascii=False)
            payload = {"total": 3, "content": [{"marcRecNo": "000123"}]}
            cache.set("search", key, payload)

            # Transport aimed at a port with no listener: network is unavailable.
            dead = opac_survey.Transport(
                policy={"127.0.0.1": {"schemes": ("http",), "ports": (1,), "https_first": False}},
                timeout=2,
            )
            opac_survey.TRANSPORT, original = dead, opac_survey.TRANSPORT
            try:
                data, hit = opac_survey.search_keyword("python", 50, cache)
            finally:
                opac_survey.TRANSPORT = original
            self.assertTrue(hit)
            self.assertEqual(data, payload)

    def test_corrupt_cache_entry_is_treated_as_miss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = opac_survey.Cache(Path(tmp), enabled=True)
            path = cache.path("search", "k")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")
            data, hit = cache.get("search", "k", ttl=3600)
            self.assertFalse(hit)
            self.assertIsNone(data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
