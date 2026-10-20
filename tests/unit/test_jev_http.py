"""The built-in JEV HTTP client against a local fake server; no network, no real key."""

from __future__ import annotations

import http.client
import json
import os
import tempfile
import unittest
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest import mock

from tests.fixtures.fake_jev_server import fake_jev
from wev_skills.core.errors import ValidationError
from wev_skills.decisions import jev_http
from wev_skills.decisions.jev_http import (
    DEFAULT_ENDPOINT,
    Endpoint,
    HttpAsker,
    build_http_asker,
    resolve_endpoint,
    validate_questions,
)
from wev_skills.decisions.jev_key import ApiKey
from wev_skills.decisions.jev_wire import JevUnavailable

QUESTIONS: dict[str, Any] = {
    "risk": {
        "type": "choice",
        "instructions": "How risky is the task?",
        "criteria": {"low": "small", "high": "large"},
    }
}
ANSWER = {"risk": {"type": "choice", "choice": "low", "confidence": 0.9}}
OK = json.dumps({"answers": ANSWER}).encode()
SECRET = "k-secret-value"
REMOTE = Endpoint("https://example.com/x", False)


class Isolated(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"HOME": tmp.name, "XDG_CONFIG_HOME": str(home / "cfg")})
        env.start()
        self.addCleanup(env.stop)
        keychain = mock.patch.object(jev_http, "macos_keychain", lambda: None)
        keychain.start()
        self.addCleanup(keychain.stop)

    def asker(
        self, url: str, key: ApiKey | None = None, timeout: float = 5.0, **kw: Any
    ) -> HttpAsker:
        return HttpAsker(resolve_endpoint({"JEV_API_URL": url}), key, timeout, **kw)


class ServerTest(Isolated):
    def test_returns_answers_as_json_text(self) -> None:
        with fake_jev([(200, OK, 0)]) as server:
            text = self.asker(server.url)(QUESTIONS, "s")
        self.assertEqual(json.loads(text)["risk"]["choice"], "low")

    def test_body_has_model_state_questions(self) -> None:
        with fake_jev([(200, OK, 0)]) as server:
            self.asker(server.url)(QUESTIONS, "s")
            body = server.requests[0].body
        self.assertEqual(body, {"model": "jev-latest", "state": "s", "questions": QUESTIONS})

    def test_loopback_sends_no_authorization(self) -> None:
        with fake_jev([(200, OK, 0)]) as server:
            self.asker(server.url, ApiKey(SECRET, "env"))(QUESTIONS, "s")
            headers = server.requests[0].headers
        self.assertNotIn("authorization", headers)
        self.assertEqual(headers["content-type"], "application/json")

    def test_retries_429_then_succeeds(self) -> None:
        sleeps: list[float] = []
        with fake_jev([(429, b"", 0), (429, b"", 0), (200, OK, 0)]) as server:
            self.asker(server.url, sleep=sleeps.append)(QUESTIONS, "s")
            self.assertEqual(len(server.requests), 3)
        self.assertEqual(sleeps, [0.5, 1.0])

    def test_401_not_retried(self) -> None:
        sleeps: list[float] = []
        with fake_jev([(401, b"nope", 0)]) as server:
            with self.assertRaises(JevUnavailable) as caught:
                self.asker(server.url, ApiKey(SECRET, "env"), sleep=sleeps.append)(QUESTIONS, "s")
            self.assertEqual(len(server.requests), 1)
        self.assertEqual(caught.exception.code, "key_rejected")
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertEqual(sleeps, [])

    def test_other_status_message_carries_the_number(self) -> None:
        with (
            fake_jev([(500, b"boom", 0)]) as server,
            self.assertRaises(JevUnavailable) as caught,
        ):
            self.asker(server.url)(QUESTIONS, "s")
        self.assertEqual(caught.exception.code, "http_status")
        self.assertIn("500", str(caught.exception))
        self.assertNotIn("boom", str(caught.exception))

    def test_redirect_is_not_followed(self) -> None:
        with fake_jev([(302, b"", 0)]) as server:
            with self.assertRaises(JevUnavailable) as caught:
                self.asker(server.url)(QUESTIONS, "s")
            self.assertEqual(len(server.requests), 1)
        self.assertEqual(caught.exception.code, "http_status")

    def test_retries_exhausted_after_max_attempts(self) -> None:
        with fake_jev([(529, b"", 0)]) as server:
            with self.assertRaises(JevUnavailable) as caught:
                self.asker(server.url, sleep=lambda _s: None)(QUESTIONS, "s")
            self.assertEqual(len(server.requests), jev_http.MAX_ATTEMPTS)
        self.assertEqual(caught.exception.code, "retries_exhausted")

    def test_socket_timeout_is_timed_out(self) -> None:
        with (
            fake_jev([(200, OK, 1.0)]) as server,
            self.assertRaises(JevUnavailable) as caught,
        ):
            self.asker(server.url, timeout=0.2)(QUESTIONS, "s")
        self.assertEqual(caught.exception.code, "timed_out")

    def test_connection_refused_is_network(self) -> None:
        with fake_jev([(200, OK, 0)]) as server:
            url = server.url
        with self.assertRaises(JevUnavailable) as caught:
            self.asker(url)(QUESTIONS, "s")
        self.assertEqual(caught.exception.code, "network")

    def test_body_without_answers_is_unparseable(self) -> None:
        for body in (b'{"other": 1}', b'{"answers": [1]}', b"[1]"):
            with self.subTest(body=body), fake_jev([(200, body, 0)]) as server:
                with self.assertRaises(JevUnavailable) as caught:
                    self.asker(server.url)(QUESTIONS, "s")
                self.assertEqual(caught.exception.code, "unparseable")

    def test_non_json_body_is_invalid_json(self) -> None:
        with (
            fake_jev([(200, b"<html>", 0)]) as server,
            self.assertRaises(JevUnavailable) as caught,
        ):
            self.asker(server.url)(QUESTIONS, "s")
        self.assertEqual(caught.exception.code, "invalid_json")


class DeadlineTest(Isolated):
    def test_deadline_bounds_retry_storm(self) -> None:
        now = [0.0]

        def sleep(seconds: float) -> None:
            now[0] += seconds

        def opener(_request: urllib.request.Request, _timeout: float) -> tuple[int, bytes]:
            return 429, b""

        asker = HttpAsker(
            REMOTE, ApiKey(SECRET, "env"), 1.0, opener=opener, sleep=sleep, clock=lambda: now[0]
        )
        with self.assertRaises(JevUnavailable) as caught:
            asker(QUESTIONS, "s")
        self.assertEqual(caught.exception.code, "timed_out")
        self.assertLessEqual(now[0], 1.0)

    def test_each_request_gets_the_remaining_time(self) -> None:
        now = [0.0]
        seen: list[float] = []

        def opener(_request: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
            seen.append(timeout)
            return (429, b"") if len(seen) == 1 else (200, OK)

        def sleep(seconds: float) -> None:
            now[0] += seconds

        asker = HttpAsker(
            REMOTE, ApiKey(SECRET, "env"), 10.0, opener=opener, sleep=sleep, clock=lambda: now[0]
        )
        asker(QUESTIONS, "s")
        self.assertEqual(seen, [10.0, 9.5])

    def test_remote_request_carries_the_bearer_key(self) -> None:
        sent: list[urllib.request.Request] = []

        def opener(request: urllib.request.Request, _timeout: float) -> tuple[int, bytes]:
            sent.append(request)
            return 200, OK

        HttpAsker(REMOTE, ApiKey(SECRET, "env"), 5.0, opener=opener)(QUESTIONS, "s")
        self.assertEqual(sent[0].get_header("Authorization"), f"Bearer {SECRET}")


class EndpointTest(Isolated):
    def test_insecure_endpoint_refused(self) -> None:
        cases = {
            "http://example.com/x": "endpoint_insecure",
            "https://u:p@example.com/": "endpoint_credentials",
        }
        for url, code in cases.items():
            with self.subTest(url=url), mock.patch("urllib.request.urlopen") as urlopen:
                with self.assertRaises(JevUnavailable) as caught:
                    build_http_asker(5.0, {"JEV_API_URL": url, "TYPESAFE_API_KEY": SECRET})
                self.assertEqual(caught.exception.code, code)
                urlopen.assert_not_called()

    def test_loopback_hosts_allow_plain_http(self) -> None:
        for url in ("http://127.0.0.1:1/x", "http://localhost:1/x", "http://[::1]:1/x"):
            with self.subTest(url=url):
                self.assertTrue(resolve_endpoint({"JEV_API_URL": url}).local)

    def test_default_endpoint_is_remote(self) -> None:
        self.assertEqual(resolve_endpoint({}), Endpoint(DEFAULT_ENDPOINT, False))

    def test_missing_key_for_remote_endpoint(self) -> None:
        with self.assertRaises(JevUnavailable) as caught:
            build_http_asker(5.0, {})
        self.assertEqual(caught.exception.code, "key_missing")
        for place in ("TYPESAFE_API_KEY", "wev-skills/.env", "typesafe-api-key"):
            self.assertIn(place, str(caught.exception))

    def test_unsendable_key_is_refused_without_leaking_it(self) -> None:
        for key in ("a\nb-secret", "cafœ-secret", "tab\there"):
            with self.subTest(key=key.encode("unicode_escape")):
                with self.assertRaises(JevUnavailable) as caught:
                    build_http_asker(5.0, {"TYPESAFE_API_KEY": key})
                self.assertEqual(caught.exception.code, "key_invalid")
                for text in (str(caught.exception), repr(caught.exception)):
                    self.assertNotIn("secret", text)
                    self.assertNotIn("a\nb", text)

    def test_non_oserror_failures_become_network_without_chaining(self) -> None:
        failures = (
            http.client.IncompleteRead(b"x"),
            http.client.BadStatusLine("x"),
            http.client.InvalidURL("x"),
            ValueError(f"Invalid header value Bearer {SECRET}"),
            UnicodeEncodeError("latin-1", "x", 0, 1, "bad"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):

                def opener(_r: urllib.request.Request, _t: float, f: Exception = failure) -> Any:
                    raise f

                asker = HttpAsker(REMOTE, ApiKey(SECRET, "env"), 5.0, opener=opener)
                with self.assertRaises(JevUnavailable) as caught:
                    asker(QUESTIONS, "s")
                self.assertEqual(caught.exception.code, "network")
                self.assertIsNone(caught.exception.__cause__)
                self.assertTrue(caught.exception.__suppress_context__)
                self.assertNotIn(SECRET, repr(caught.exception))

    def test_malformed_endpoint_is_endpoint_invalid(self) -> None:
        for url in ("http://[::1", "https://example.com:notaport/x"):
            with self.subTest(url=url), self.assertRaises(JevUnavailable) as caught:
                resolve_endpoint({"JEV_API_URL": url})
            self.assertEqual(caught.exception.code, "endpoint_invalid")

    def test_loopback_needs_no_key(self) -> None:
        asker = build_http_asker(5.0, {"JEV_API_URL": "http://127.0.0.1:1/x"})
        self.assertIsInstance(asker, HttpAsker)


class ValidateQuestionsTest(unittest.TestCase):
    def test_valid_questions_pass(self) -> None:
        validate_questions(QUESTIONS)
        validate_questions({"s": {"type": "score", "instructions": "i", "criteria": ["a", "b"]}})
        validate_questions({"n": {"type": "noul", "instructions": "i"}})

    def test_validate_questions_rules(self) -> None:
        def one(**fields: Any) -> Mapping[str, Any]:
            return {"q": {"type": "noul", "instructions": "i", **fields}}

        bad: list[Mapping[str, Any]] = [
            {},
            one(type="choice", criteria={"only": "x"}),
            one(type="choice", criteria={f"o{i}": "x" for i in range(256)}),
            one(type="score", criteria=[str(i) for i in range(11)]),
            one(type="score", criteria=["a"]),
            one(instructions="  "),
            one(type="maybe"),
        ]
        for questions in bad:
            with self.subTest(questions=str(questions)[:60]):
                with self.assertRaises(ValidationError) as caught:
                    validate_questions(questions)
                self.assertEqual(caught.exception.code, "invalid_questions")


if __name__ == "__main__":
    unittest.main()
