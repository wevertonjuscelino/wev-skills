"""Ask JEV over HTTPS with the standard library: no external program.

The behavior ports ``jev.mjs``: the same endpoint, model, retry statuses and backoff, plus
one deadline. The deadline bounds the retries and each request's socket timeout; a server
that drips bytes, or slow DNS, can still exceed it. Every failure is a ``JevUnavailable`` so the
caller falls back to the local policy; the key never reaches a message.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from wev_skills import i18n
from wev_skills.core.errors import ValidationError
from wev_skills.decisions.jev_key import ApiKey, env_file_path, macos_keychain, resolve_api_key
from wev_skills.decisions.jev_wire import JevUnavailable

DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
ENDPOINT_VAR = "JEV_API_URL"
MODEL = "jev-latest"
RETRYABLE = (429, 529)
MAX_ATTEMPTS = 4
BASE_BACKOFF_SECONDS = 0.5
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
QUESTION_TYPES = ("noul", "choice", "score")
MIN_OPTIONS = 2
MAX_CHOICE_OPTIONS = 255
MAX_SCORE_LEVELS = 10
HTTP_OK_FIRST = 200
HTTP_OK_LAST = 299
HTTP_UNAUTHORIZED = 401
MAX_RESPONSE_BYTES = 1_048_576
"""At most this much of a response body is read; a longer one is ``response_too_large``."""
SPACE = 0x20
DELETE = 0x7F

Opener = Callable[[urllib.request.Request, float], tuple[int, bytes]]


@dataclass(frozen=True)
class Endpoint:
    url: str
    local: bool


def _why(code: str, key: str, **params: object) -> JevUnavailable:
    return JevUnavailable(code, i18n.t(f"decisions.jev.why.{key}", **params))


def resolve_endpoint(env: Mapping[str, str]) -> Endpoint:
    url = env.get(ENDPOINT_VAR) or DEFAULT_ENDPOINT
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        parts.port  # noqa: B018 - reading it validates the port
    except ValueError:
        raise _why("endpoint_invalid", "endpoint_invalid") from None
    local = host in LOOPBACK_HOSTS
    if parts.username or parts.password:
        raise _why("endpoint_credentials", "endpoint_credentials")
    if parts.scheme != "https" and not (local and parts.scheme == "http"):
        raise _why("endpoint_insecure", "endpoint_insecure")
    return Endpoint(url, local)


def _invalid(message_key: str, **params: object) -> ValidationError:
    why = i18n.t(f"decisions.jev.error.{message_key}", **params)
    return ValidationError(
        "invalid_questions", i18n.t("decisions.jev.error.invalid_questions", why=why)
    )


def _is_object(value: Any) -> bool:
    return isinstance(value, Mapping)


def _validate_criteria(name: str, question: Mapping[str, Any]) -> None:
    kind, criteria = question["type"], question.get("criteria")
    if kind == "choice":
        count = len(criteria) if isinstance(criteria, Mapping) else 0
        if not MIN_OPTIONS <= count <= MAX_CHOICE_OPTIONS:
            raise _invalid("choice_options", name=name, low=MIN_OPTIONS, high=MAX_CHOICE_OPTIONS)
    if kind == "score":
        count = len(criteria) if isinstance(criteria, list) else 0
        if not MIN_OPTIONS <= count <= MAX_SCORE_LEVELS:
            raise _invalid("score_levels", name=name, low=MIN_OPTIONS, high=MAX_SCORE_LEVELS)


def validate_questions(questions: Mapping[str, Any]) -> None:
    if not _is_object(questions) or not questions:
        raise _invalid("not_object")
    for name, question in questions.items():
        if not _is_object(question) or question.get("type") not in QUESTION_TYPES:
            raise _invalid("bad_type", name=name, types=", ".join(QUESTION_TYPES))
        instructions = question.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            raise _invalid("no_instructions", name=name)
        _validate_criteria(name, question)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the Authorization header to another host: never follow one."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _urlopen(request: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.read(MAX_RESPONSE_BYTES + 1)


def _network_failure(exc: OSError) -> JevUnavailable:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return _why("timed_out", "timed_out")
    return _why("network", "network")


def _answers(body: bytes) -> str:
    try:
        data = json.loads(body)
    except (ValueError, RecursionError) as exc:
        raise _why("invalid_json", "invalid_json") from exc
    answers = data.get("answers") if isinstance(data, Mapping) else None
    if not isinstance(answers, Mapping):
        raise _why("unparseable", "not_object")
    return json.dumps(answers)


class HttpAsker:
    def __init__(
        self,
        endpoint: Endpoint,
        key: ApiKey | None,
        timeout_seconds: float,
        *,
        opener: Opener = _urlopen,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._endpoint = endpoint
        self._key = key
        self._timeout = timeout_seconds
        self._opener = opener
        self._sleep = sleep
        self._clock = clock

    def _request(self, questions: Mapping[str, Any], state: str) -> urllib.request.Request:
        headers = {"Content-Type": "application/json"}
        if not self._endpoint.local and self._key is not None:
            headers["Authorization"] = f"Bearer {self._key.value}"
        body = json.dumps({"model": MODEL, "state": state, "questions": questions})
        return urllib.request.Request(
            self._endpoint.url, data=body.encode(), headers=headers, method="POST"
        )

    def _send(self, request: urllib.request.Request, remaining: float) -> tuple[int, bytes]:
        try:
            return self._opener(request, remaining)
        except OSError as exc:
            raise _network_failure(exc) from None
        except http.client.HTTPException, ValueError, UnicodeError:
            # Never chain: an http.client ValueError message can carry the Authorization value.
            raise _why("network", "network") from None

    def __call__(self, questions: Mapping[str, Any], state: str) -> str:
        validate_questions(questions)
        request = self._request(questions, state)
        deadline = self._clock() + self._timeout
        for attempt in range(1, MAX_ATTEMPTS + 1):
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise _why("timed_out", "timed_out")
            status, body = self._send(request, remaining)
            if len(body) > MAX_RESPONSE_BYTES:
                raise _why("response_too_large", "response_too_large")
            if HTTP_OK_FIRST <= status <= HTTP_OK_LAST:
                return _answers(body)
            if status == HTTP_UNAUTHORIZED:
                raise _why("key_rejected", "key_rejected")
            if status not in RETRYABLE:
                raise _why("http_status", "http_status", status=status)
            if attempt == MAX_ATTEMPTS:
                raise _why("retries_exhausted", "retries_exhausted")
            backoff = BASE_BACKOFF_SECONDS * 2 ** (attempt - 1)
            if self._clock() + backoff >= deadline:
                raise _why("timed_out", "timed_out")
            self._sleep(backoff)
        raise _why("retries_exhausted", "retries_exhausted")


def _usable_header_value(value: str) -> bool:
    try:
        value.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return not any(ord(char) < SPACE or ord(char) == DELETE for char in value)


class LazyAsker:
    """Builds the ``HttpAsker`` on the first call, so a missing key is a per-call
    ``JevUnavailable`` (a local fallback) and not a startup failure. A failed build is not
    kept: the next call tries again, which picks up a key added mid-session."""

    def __init__(self, timeout_seconds: float) -> None:
        self._timeout = timeout_seconds
        self._asker: HttpAsker | None = None

    def __call__(self, questions: Mapping[str, Any], state: str) -> str:
        if self._asker is None:
            self._asker = build_http_asker(self._timeout)
        return self._asker(questions, state)


def build_http_asker(timeout_seconds: float, env: Mapping[str, str] | None = None) -> HttpAsker:
    source = os.environ if env is None else env
    endpoint = resolve_endpoint(source)
    key = resolve_api_key(source, env_file_path(), macos_keychain)
    if key is None and not endpoint.local:
        raise _why("key_missing", "key_missing")
    if key is not None and not endpoint.local and not _usable_header_value(key.value):
        raise _why("key_invalid", "key_invalid")
    return HttpAsker(endpoint, key, timeout_seconds)
