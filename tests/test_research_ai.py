import http.server
import json
import threading
from urllib.error import HTTPError, URLError
import unittest
from unittest.mock import patch

from investment_monitor.research import ResearchSettings, validate_base_url
from investment_monitor.research_ai import (
    MAX_RESPONSE_BYTES,
    ResearchAIClient,
    ResearchAIError,
)


class FakeResponse:
    def __init__(self, body, status=200, headers=None):
        self._body = body
        self._pos = 0
        self.status = status
        self.headers = headers or {}
        self.closed = False

    def read(self, size=-1):
        if size is None or size < 0:
            chunk = self._body[self._pos:]
            self._pos = len(self._body)
            return chunk
        chunk = self._body[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk

    def close(self):
        self.closed = True


def make_opener(
    response=None,
    http_code=None,
    urlerror=False,
    should_timeout=False,
    oserror_type=None,
    capture=None,
    redirect_status=None,
    redirect_location=None,
    response_headers=None,
):
    def opener(request, timeout=None):
        if capture is not None:
            capture.append({
                "url": request.full_url,
                "headers": dict(request.headers),
                "data": request.data,
                "timeout": timeout,
            })
        if should_timeout:
            raise TimeoutError("simulated timeout")
        if urlerror:
            raise URLError("simulated network error")
        if oserror_type is not None:
            raise oserror_type("simulated socket interruption")
        if http_code is not None:
            raise HTTPError(request.full_url, http_code, "error", {}, None)
        if redirect_status is not None:
            return FakeResponse(
                b"", status=redirect_status,
                headers={"Location": redirect_location or "https://evil.example.com/x"},
            )
        if isinstance(response, FakeResponse):
            return response
        return FakeResponse(response, headers=response_headers)
    return opener


def openai_response(content):
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": content}}]
    }).encode("utf-8")


class _MockRedirectServer:
    """A real loopback HTTP server that answers every POST with a 3xx."""

    def __init__(self, status):
        self.status = status
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                # Drain the request body so the client can finish sending its
                # POST payload without the socket being reset mid-write (which
                # surfaces as WinError 10053 ConnectionAbortedError on Windows).
                length = int(self.headers.get("Content-Length", "0") or "0")
                if length > 0:
                    self.rfile.read(length)
                outer.requests.append(dict(self.headers))
                self.send_response(outer.status)
                self.send_header("Location", "http://127.0.0.1:9/evil-target")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        self._server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._ready = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("mock redirect server did not start")

    def _serve(self):
        self._ready.set()
        self._server.serve_forever(poll_interval=0.05)

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


class ResearchAIClientTests(unittest.TestCase):
    def setUp(self):
        self.settings = ResearchSettings(
            enabled=True,
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
            api_key="secret-key",
        )

    def make_client(self, **kwargs):
        return ResearchAIClient(self.settings, **kwargs)

    def test_base_url_normalization_without_v1(self):
        client = self.make_client()
        self.assertEqual(
            client._chat_completions_url(),
            "https://api.deepseek.com/v1/chat/completions",
        )

    def test_base_url_normalization_with_v1(self):
        client = ResearchAIClient(
            ResearchSettings(base_url="https://api.deepseek.com/v1")
        )
        self.assertEqual(
            client._chat_completions_url(),
            "https://api.deepseek.com/v1/chat/completions",
        )

    def test_request_payload_and_headers(self):
        captured = []
        client = self.make_client(
            opener=make_opener(response=openai_response('{"a": 1}'), capture=captured)
        )
        client.generate(system_prompt="sys", user_prompt="user", language="en")
        self.assertEqual(len(captured), 1)
        request = captured[0]
        self.assertEqual(request["url"], "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(request["headers"]["Authorization"], "Bearer secret-key")
        payload = json.loads(request["data"].decode("utf-8"))
        self.assertEqual(payload["model"], "deepseek-chat")
        self.assertEqual(payload["temperature"], 0.1)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["stream"], False)
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["content"], "user")

    def test_api_key_only_in_authorization_header(self):
        captured = []
        client = self.make_client(
            opener=make_opener(response=openai_response('{"a": 1}'), capture=captured)
        )
        client.generate(system_prompt="sys", user_prompt="user", language="en")
        raw = captured[0]["data"].decode("utf-8")
        self.assertNotIn("secret-key", raw)
        self.assertNotIn("secret-key", captured[0]["url"])
        self.assertIn("Authorization", captured[0]["headers"])

    def test_timeout_is_passed_to_opener(self):
        captured = []
        client = self.make_client(
            opener=make_opener(response=openai_response('{"a": 1}'), capture=captured)
        )
        client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(captured[0]["timeout"], self.settings.request_timeout_seconds)

    def test_auth_error_401(self):
        client = self.make_client(opener=make_opener(http_code=401))
        with self.assertRaises(ResearchAIError) as ctx:
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(ctx.exception.code, "upstream_auth_error")
        self.assertNotIn("secret-key", ctx.exception.message)

    def test_auth_error_403(self):
        client = self.make_client(opener=make_opener(http_code=403))
        with self.assertRaises(ResearchAIError) as ctx:
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(ctx.exception.code, "upstream_auth_error")

    def test_rate_limited_429(self):
        client = self.make_client(opener=make_opener(http_code=429))
        with self.assertRaises(ResearchAIError) as ctx:
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(ctx.exception.code, "upstream_rate_limited")

    def test_server_error_5xx(self):
        client = self.make_client(opener=make_opener(http_code=500))
        with self.assertRaises(ResearchAIError) as ctx:
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(ctx.exception.code, "upstream_server_error")

    def test_network_error(self):
        client = self.make_client(opener=make_opener(urlerror=True))
        with self.assertRaises(ResearchAIError) as ctx:
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(ctx.exception.code, "upstream_network_error")
        self.assertNotIn("secret-key", ctx.exception.message)

    def test_connection_aborted_maps_to_network_error(self):
        client = self.make_client(opener=make_opener(oserror_type=ConnectionAbortedError))
        with self.assertRaises(ResearchAIError) as ctx:
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(ctx.exception.code, "upstream_network_error")
        self.assertNotIn("secret-key", ctx.exception.message)

    def test_connection_reset_maps_to_network_error(self):
        client = self.make_client(opener=make_opener(oserror_type=ConnectionResetError))
        with self.assertRaises(ResearchAIError) as ctx:
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(ctx.exception.code, "upstream_network_error")
        self.assertNotIn("secret-key", ctx.exception.message)

    def test_broken_pipe_maps_to_network_error(self):
        client = self.make_client(opener=make_opener(oserror_type=BrokenPipeError))
        with self.assertRaises(ResearchAIError) as ctx:
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(ctx.exception.code, "upstream_network_error")
        self.assertNotIn("secret-key", ctx.exception.message)

    def test_timeout_error(self):
        client = self.make_client(opener=make_opener(should_timeout=True))
        with self.assertRaises(ResearchAIError) as ctx:
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(ctx.exception.code, "upstream_timeout")

    def test_non_json_response_rejected(self):
        client = self.make_client(opener=make_opener(response=b"not json at all"))
        with self.assertRaises(ResearchAIError) as ctx:
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(ctx.exception.code, "invalid_model_response")

    def test_empty_choices_rejected(self):
        body = json.dumps({"choices": []}).encode("utf-8")
        client = self.make_client(opener=make_opener(response=body))
        with self.assertRaises(ResearchAIError) as ctx:
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(ctx.exception.code, "invalid_model_response")

    def test_code_fence_tolerated(self):
        body = openai_response('```json\n{"a": 1}\n```')
        client = self.make_client(opener=make_opener(response=body))
        result = client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(result, {"a": 1})

    def test_content_is_parsed_json_object(self):
        body = openai_response(json.dumps({"schema_version": "x"}))
        client = self.make_client(opener=make_opener(response=body))
        result = client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(result["schema_version"], "x")

    # --- P0-2: redirects are never followed ---

    def _assert_redirect_rejected(self, status):
        captured = []
        client = self.make_client(
            opener=make_opener(redirect_status=status, capture=captured)
        )
        with self.assertRaises(ResearchAIError) as ctx:
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(ctx.exception.code, "upstream_redirect_error")
        # Only one request was made: the redirect target was never contacted.
        self.assertEqual(len(captured), 1)

    def test_redirect_301_not_followed(self):
        self._assert_redirect_rejected(301)

    def test_redirect_302_not_followed(self):
        self._assert_redirect_rejected(302)

    def test_redirect_303_not_followed(self):
        self._assert_redirect_rejected(303)

    def test_redirect_307_not_followed(self):
        self._assert_redirect_rejected(307)

    def test_redirect_308_not_followed(self):
        self._assert_redirect_rejected(308)

    def test_base_url_rejects_userinfo(self):
        with self.assertRaises(ValueError):
            ResearchSettings(base_url="https://user:pass@api.deepseek.com")

    def test_base_url_rejects_fragment(self):
        with self.assertRaises(ValueError):
            ResearchSettings(base_url="https://api.deepseek.com#frag")

    def test_base_url_rejects_file_scheme(self):
        with self.assertRaises(ValueError):
            ResearchSettings(base_url="file:///etc/passwd")

    def test_base_url_rejects_ftp_scheme(self):
        with self.assertRaises(ValueError):
            ResearchSettings(base_url="ftp://api.deepseek.com")

    def test_base_url_rejects_arbitrary_http(self):
        with self.assertRaises(ValueError):
            ResearchSettings(base_url="http://intranet.example.com")

    def test_base_url_allows_https(self):
        settings = ResearchSettings(base_url="https://api.deepseek.com")
        self.assertEqual(settings.base_url, "https://api.deepseek.com")

    def test_base_url_allows_loopback_http_with_test_switch(self):
        with patch.dict("os.environ", {"RESEARCH_AI_ALLOW_LOOPBACK_HTTP": "true"}):
            settings = ResearchSettings(base_url="http://localhost:8000")
        self.assertEqual(settings.base_url, "http://localhost:8000")

    def test_base_url_rejects_loopback_http_without_switch(self):
        with patch.dict("os.environ", {"RESEARCH_AI_ALLOW_LOOPBACK_HTTP": "false"}):
            with self.assertRaises(ValueError):
                ResearchSettings(base_url="http://localhost:8000")

    def test_base_url_rejects_missing_hostname(self):
        with self.assertRaises(ValueError):
            ResearchSettings(base_url="https:///path-only")

    def test_base_url_allows_allowlisted_second_provider(self):
        with patch.dict("os.environ", {"RESEARCH_AI_ALLOWED_HOSTS": "example.provider.com"}):
            settings = ResearchSettings(base_url="https://example.provider.com")
        self.assertEqual(settings.base_url, "https://example.provider.com")

    def test_base_url_rejects_non_allowlisted_host(self):
        with self.assertRaises(ValueError):
            ResearchSettings(base_url="https://evil.example.com")

    def test_base_url_rejects_ip_literal(self):
        with self.assertRaises(ValueError):
            ResearchSettings(base_url="https://127.0.0.1")

    def test_base_url_rejects_private_ip(self):
        with self.assertRaises(ValueError):
            ResearchSettings(base_url="https://10.0.0.1")

    def test_base_url_rejects_link_local(self):
        with self.assertRaises(ValueError):
            ResearchSettings(base_url="https://169.254.169.254")

    def test_base_url_rejects_query(self):
        with self.assertRaises(ValueError):
            ResearchSettings(base_url="https://api.deepseek.com?token=secret")

    # --- P1-2: response size limits ---

    def test_oversized_content_length_rejected(self):
        client = self.make_client(
            opener=make_opener(
                response=openai_response('{"a": 1}'),
                response_headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)},
            )
        )
        with self.assertRaises(ResearchAIError) as ctx:
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(ctx.exception.code, "response_too_large")

    def test_oversized_chunked_response_rejected(self):
        big = b"x" * (MAX_RESPONSE_BYTES + 1)
        client = self.make_client(opener=make_opener(response=big))
        with self.assertRaises(ResearchAIError) as ctx:
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(ctx.exception.code, "response_too_large")

    def test_normal_sized_response_ok(self):
        client = self.make_client(opener=make_opener(response=openai_response('{"a": 1}')))
        result = client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertEqual(result, {"a": 1})

    # --- P1: real 3xx via a real urllib opener and a local mock server ---

    def _assert_real_redirect_rejected(self, status):
        server = _MockRedirectServer(status)
        server.start()
        try:
            with patch.dict("os.environ", {"RESEARCH_AI_ALLOW_LOOPBACK_HTTP": "true"}):
                settings = ResearchSettings(
                    enabled=True,
                    base_url=f"http://127.0.0.1:{server.port}",
                    api_key="secret-key",
                )
            client = ResearchAIClient(settings)
            with self.assertRaises(ResearchAIError) as ctx:
                client.generate(system_prompt="s", user_prompt="u", language="en")
            self.assertEqual(ctx.exception.code, "upstream_redirect_error")
            self.assertEqual(len(server.requests), 1)
            self.assertIn("Authorization", server.requests[0])
        finally:
            server.stop()

    def test_real_redirect_301_not_followed(self):
        self._assert_real_redirect_rejected(301)

    def test_real_redirect_302_not_followed(self):
        self._assert_real_redirect_rejected(302)

    def test_real_redirect_303_not_followed(self):
        self._assert_real_redirect_rejected(303)

    def test_real_redirect_307_not_followed(self):
        self._assert_real_redirect_rejected(307)

    def test_real_redirect_308_not_followed(self):
        self._assert_real_redirect_rejected(308)

    # --- P1: response close on every path ---

    def test_response_closed_on_success(self):
        response = FakeResponse(openai_response('{"a": 1}'))
        client = self.make_client(opener=make_opener(response=response))
        client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertTrue(response.closed)

    def test_response_closed_on_oversized_content_length(self):
        response = FakeResponse(
            openai_response('{"a": 1}'),
            headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)},
        )
        client = self.make_client(opener=make_opener(response=response))
        with self.assertRaises(ResearchAIError):
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertTrue(response.closed)

    def test_response_closed_on_oversized_chunked(self):
        response = FakeResponse(b"x" * (MAX_RESPONSE_BYTES + 1))
        client = self.make_client(opener=make_opener(response=response))
        with self.assertRaises(ResearchAIError):
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertTrue(response.closed)

    def test_response_closed_on_non_json(self):
        response = FakeResponse(b"not json")
        client = self.make_client(opener=make_opener(response=response))
        with self.assertRaises(ResearchAIError):
            client.generate(system_prompt="s", user_prompt="u", language="en")
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
