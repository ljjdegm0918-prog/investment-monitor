"""OpenAI-compatible model adapter for research card generation.

This module is intentionally small and dependency-free. It uses the same
stdlib ``urllib.request`` pattern as the rest of the monitor, and never
exposes the API key, the Authorization header, or the full upstream response
in an exception or log message.

Redirects are never followed: the Authorization header must not be replayed to
a different host. Response bodies are read with a hard byte cap so an
unbounded upstream response cannot exhaust memory.

It performs no implicit retries: a request is issued once, so a transient
failure cannot silently double-bill the user's model provider.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, List, Mapping, Optional
import urllib.request
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .research import (
    ERROR_INVALID_MODEL_RESPONSE,
    ERROR_RESPONSE_TOO_LARGE,
    ERROR_UPSTREAM_AUTH,
    ERROR_UPSTREAM_NETWORK,
    ERROR_UPSTREAM_RATE_LIMITED,
    ERROR_UPSTREAM_REDIRECT,
    ERROR_UPSTREAM_SERVER,
    ERROR_UPSTREAM_TIMEOUT,
    ResearchSettings,
)

# Hard cap on the model response body. A valid research card is a few KB;
# this cap exists to stop a hostile or broken upstream from streaming an
# unbounded payload.
MAX_RESPONSE_BYTES = 512 * 1024
_READ_CHUNK_BYTES = 64 * 1024


class ResearchAIError(Exception):
    """A stable, non-sensitive generation error with a machine error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject every redirect so the Authorization header is never replayed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler())


@dataclass(frozen=True)
class ResearchAIClient:
    """Minimal OpenAI-compatible chat-completions client."""

    settings: ResearchSettings
    opener: Optional[Callable[..., Any]] = None
    max_response_bytes: int = MAX_RESPONSE_BYTES

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        language: str,
    ) -> Mapping[str, Any]:
        """Send one chat completion and return the parsed JSON object."""
        url = self._chat_completions_url()
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.api_key}",
            },
        )
        opener = self.opener or _NO_REDIRECT_OPENER.open
        response = None
        try:
            response = opener(request, timeout=self.settings.request_timeout_seconds)
        except HTTPError as error:
            raise self._http_error(error) from error
        except TimeoutError as error:
            raise ResearchAIError(
                ERROR_UPSTREAM_TIMEOUT,
                "The model request timed out.",
            ) from error
        except URLError as error:
            raise ResearchAIError(
                ERROR_UPSTREAM_NETWORK,
                "The model provider could not be reached.",
            ) from error
        except OSError as error:
            # Socket-level interruptions (ConnectionAbortedError,
            # ConnectionResetError, BrokenPipeError, ...) surface as OSError and
            # must be mapped to a controlled network error, never a raw traceback.
            raise ResearchAIError(
                ERROR_UPSTREAM_NETWORK,
                "The model provider connection was interrupted.",
            ) from error

        try:
            status = _response_status(response)
            if status is not None and 300 <= status < 400:
                raise ResearchAIError(
                    ERROR_UPSTREAM_REDIRECT,
                    "The model provider returned a redirect, which is not followed.",
                )
            raw = self._read_limited(response)
        finally:
            _close_response(response)

        return self._parse_content(raw)

    def _chat_completions_url(self) -> str:
        base = self.settings.base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _read_limited(self, response: Any) -> bytes:
        """Read the response body with a hard byte cap.

        A declared Content-Length is checked first; the body is then read in
        chunks and aborted as soon as the cap is exceeded. A too-large
        response fails safely without attempting to parse it.
        """
        content_length = None
        headers = getattr(response, "headers", None)
        if headers is not None:
            raw_length = headers.get("Content-Length") if hasattr(headers, "get") else None
            if raw_length:
                try:
                    content_length = int(raw_length)
                except (TypeError, ValueError):
                    content_length = None
        if content_length is not None and content_length > self.max_response_bytes:
            raise ResearchAIError(
                ERROR_RESPONSE_TOO_LARGE,
                "The model response exceeded the size limit.",
            )
        chunks: List[bytes] = []
        total = 0
        while True:
            try:
                chunk = response.read(_READ_CHUNK_BYTES)
            except TypeError:
                # A simple fake response with a size-less read().
                chunk = response.read()
            if not chunk:
                break
            total += len(chunk)
            if total > self.max_response_bytes:
                raise ResearchAIError(
                    ERROR_RESPONSE_TOO_LARGE,
                    "The model response exceeded the size limit.",
                )
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _http_error(error: HTTPError) -> ResearchAIError:
        code = getattr(error, "code", None)
        if code is not None and 300 <= code < 400:
            return ResearchAIError(
                ERROR_UPSTREAM_REDIRECT,
                "The model provider returned a redirect, which is not followed.",
            )
        if code in (401, 403):
            return ResearchAIError(
                ERROR_UPSTREAM_AUTH,
                "The model provider rejected the API key.",
            )
        if code == 429:
            return ResearchAIError(
                ERROR_UPSTREAM_RATE_LIMITED,
                "The model provider rate limit was exceeded.",
            )
        if code is not None and 500 <= code < 600:
            return ResearchAIError(
                ERROR_UPSTREAM_SERVER,
                "The model provider returned a server error.",
            )
        return ResearchAIError(
            ERROR_UPSTREAM_SERVER,
            "The model provider returned an error.",
        )

    @staticmethod
    def _parse_content(raw: bytes) -> Mapping[str, Any]:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ResearchAIError(
                ERROR_INVALID_MODEL_RESPONSE,
                "The model provider returned a non-JSON response.",
            ) from error
        if not isinstance(payload, dict):
            raise ResearchAIError(
                ERROR_INVALID_MODEL_RESPONSE,
                "The model provider returned an unexpected response shape.",
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ResearchAIError(
                ERROR_INVALID_MODEL_RESPONSE,
                "The model provider returned no choices.",
            )
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise ResearchAIError(
                ERROR_INVALID_MODEL_RESPONSE,
                "The model provider returned no message.",
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ResearchAIError(
                ERROR_INVALID_MODEL_RESPONSE,
                "The model returned empty content.",
            )
        return _extract_json_object(content)


def _response_status(response: Any) -> Optional[int]:
    status = getattr(response, "status", None)
    if status is not None:
        return status
    getcode = getattr(response, "getcode", None)
    if callable(getcode):
        return getcode()
    return None


def _close_response(response: Any) -> None:
    """Close a response on every path, tolerating double-close and failures."""
    if response is None:
        return
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _extract_json_object(content: str) -> Mapping[str, Any]:
    """Parse a model content string that should be a JSON object.

    Tolerates a single wrapping Markdown code fence, but never accepts HTML or
    free text. Returns a mapping or raises ``ResearchAIError``.
    """
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ResearchAIError(
            ERROR_INVALID_MODEL_RESPONSE,
            "The model response is not valid JSON.",
        ) from error
    if not isinstance(parsed, dict):
        raise ResearchAIError(
            ERROR_INVALID_MODEL_RESPONSE,
            "The model response JSON is not an object.",
        )
    return parsed
