"""Portable model configuration checks: temporary files and mocked HTTP only."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from interview import config
from interview.llm import KimiClient, ModelError

HTTP_CLIENT = httpx.AsyncClient
TEST_KEY = "unit-test-credential-not-real"


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repository"
        self.root.mkdir()
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root_patch = patch.object(config, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def test_dotenv_is_literal_and_shell_environment_wins(self):
        (self.root / ".env").write_text(
            '# local settings\nCOCKPIT_MODEL="file-model"\n'
            "COCKPIT_API_KEY='$SHOULD_NOT_EXPAND'\n"
            "COCKPIT_API_BASE=https://provider.invalid  # comment\n"
            "HOME=/must-not-overwrite-system-variables\n", encoding="utf-8")
        os.environ["COCKPIT_MODEL"] = "shell-model"
        config.load_project_env()
        self.assertEqual(os.environ["COCKPIT_MODEL"], "shell-model")
        self.assertEqual(os.environ["COCKPIT_API_KEY"], "$SHOULD_NOT_EXPAND")
        self.assertEqual(os.environ["COCKPIT_API_BASE"], "https://provider.invalid")
        self.assertNotIn("HOME", os.environ)

    def test_invalid_dotenv_does_not_partially_change_environment(self):
        (self.root / ".env").write_text("COCKPIT_MODEL=first\ninvalid-line\n", encoding="utf-8")
        with self.assertRaises(config.ConfigurationError):
            config.load_project_env()
        self.assertNotIn("COCKPIT_MODEL", os.environ)

    def test_explicit_empty_environment_overrides_dotenv(self):
        (self.root / ".env").write_text("COCKPIT_API_KEY=file-value\n", encoding="utf-8")
        os.environ["COCKPIT_API_KEY"] = ""
        config.load_project_env()
        self.assertEqual(os.environ["COCKPIT_API_KEY"], "")

    def test_legacy_file_is_opt_in_and_relative_to_repository(self):
        (self.root / "private-api.txt").write_text(
            "https://provider.invalid/v1\nsk-unit-test-legacy\n", encoding="utf-8")
        os.environ["COCKPIT_API_FILE"] = "private-api.txt"
        credentials = config.api_credentials()
        self.assertEqual(credentials.base_url, "https://provider.invalid/v1/")
        self.assertEqual(credentials.key, "sk-unit-test-legacy")
        self.assertNotIn(credentials.key, repr(credentials))

    def test_environment_pair_takes_precedence_over_legacy_file(self):
        os.environ.update(COCKPIT_API_BASE="https://provider.invalid", COCKPIT_API_KEY=TEST_KEY,
                          COCKPIT_API_FILE="does-not-exist.txt")
        self.assertEqual(config.api_credentials().key, TEST_KEY)

    def test_incomplete_environment_does_not_silently_use_file(self):
        os.environ.update(COCKPIT_API_BASE="https://provider.invalid", COCKPIT_API_FILE="unused.txt")
        with self.assertRaisesRegex(config.ConfigurationError, "同时设置"):
            config.api_credentials()

    def test_base_url_rejects_embedded_credentials_and_query_without_echoing(self):
        os.environ.update(COCKPIT_API_BASE=f"https://user:{TEST_KEY}@provider.invalid/v1",
                          COCKPIT_API_KEY=TEST_KEY)
        with self.assertRaises(config.ConfigurationError) as raised:
            config.api_credentials()
        self.assertNotIn(TEST_KEY, str(raised.exception))
        os.environ["COCKPIT_API_BASE"] = f"https://provider.invalid/v1?key={TEST_KEY}"
        with self.assertRaises(config.ConfigurationError):
            config.api_credentials()


class ModelConnectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repository"
        self.root.mkdir()
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root_patch = patch.object(config, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.http_clients = []
        self.requests = []

    def mock_provider(self, handler):
        def dispatch(request):
            self.requests.append(request)
            return handler(request)

        def factory(**kwargs):
            client = HTTP_CLIENT(transport=httpx.MockTransport(dispatch), **kwargs)
            self.http_clients.append(client)
            return client
        mocked = patch("interview.llm.httpx.AsyncClient", side_effect=factory)
        mocked.start()
        self.addCleanup(mocked.stop)

    def configure(self, **extra):
        os.environ.update(COCKPIT_API_BASE="https://provider.invalid", COCKPIT_API_KEY=TEST_KEY, **extra)

    async def test_no_config_never_reads_neighbour_credentials_or_calls_network(self):
        neighbour = self.root.parent / "外部服务器"
        neighbour.mkdir()
        (neighbour / "api.txt").write_text("https://provider.invalid\nsk-neighbour-private\n")
        with patch("interview.llm.httpx.AsyncClient") as network:
            client = KimiClient()
            with self.assertRaisesRegex(ModelError, "尚未配置"):
                await client.connect()
            network.assert_not_called()
        self.assertEqual(client.report["status"], "unavailable")

    async def test_dotenv_credentials_autoselect_kimi_and_send_bearer_header(self):
        (self.root / ".env").write_text(
            f"COCKPIT_API_BASE=https://provider.invalid\nCOCKPIT_API_KEY={TEST_KEY}\n", encoding="utf-8")
        self.mock_provider(lambda request: httpx.Response(200, json={"data": [
            {"id": "other-model"}, {"id": "provider/Kimi"}]}))
        client = KimiClient()
        await client.connect()
        self.assertEqual(client.model, "provider/Kimi")
        self.assertEqual(str(self.requests[0].url), "https://provider.invalid/v1/models")
        self.assertEqual(self.requests[0].headers["Authorization"], f"Bearer {TEST_KEY}")
        self.assertNotIn(TEST_KEY, str(client.report))
        await client.close()
        self.assertTrue(self.http_clients[0].is_closed)

    async def test_explicit_non_kimi_model_and_tool_request_are_preserved(self):
        self.configure(COCKPIT_MODEL="another-model")
        def handler(request):
            if request.url.path.endswith("/models"):
                return httpx.Response(200, json={"data": [{"id": "another-model"}]})
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}],
                                            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}})
        self.mock_provider(handler)
        client = KimiClient()
        result = await client.request([{"role": "user", "content": "hello"}])
        self.assertEqual(result["model"], "another-model")
        self.assertEqual(result["content"], "ok")
        self.assertEqual(client.usage["total_tokens"], 5)
        self.assertEqual(len(self.requests), 2)
        await client.close()

    async def test_unknown_model_fails_clearly_and_closes_http_client(self):
        self.configure(COCKPIT_MODEL="missing-model")
        self.mock_provider(lambda request: httpx.Response(200, json={"data": [{"id": "provider/Kimi"}]}))
        client = KimiClient()
        with self.assertRaisesRegex(ModelError, "COCKPIT_MODEL"):
            await client.connect()
        self.assertFalse(client.report["available"])
        self.assertTrue(self.http_clients[0].is_closed)

    async def test_connection_errors_never_echo_url_or_key(self):
        self.configure()
        def fail(request):
            raise httpx.ConnectError(f"private provider {TEST_KEY} at {request.url}")
        self.mock_provider(fail)
        client = KimiClient()
        with self.assertRaises(ModelError) as raised:
            await client.connect()
        self.assertNotIn(TEST_KEY, str(raised.exception))
        self.assertNotIn("provider.invalid", str(raised.exception))
        self.assertTrue(self.http_clients[0].is_closed)

    async def test_provider_http_error_body_is_not_exposed(self):
        self.configure()
        self.mock_provider(lambda request: httpx.Response(401, text=f"bad key: {TEST_KEY}"))
        client = KimiClient()
        with self.assertRaises(ModelError) as raised:
            await client.connect()
        self.assertIn("HTTP 401", str(raised.exception))
        self.assertNotIn(TEST_KEY, str(raised.exception))
        self.assertTrue(self.http_clients[0].is_closed)

    async def test_malformed_model_catalog_is_closed_and_sanitized(self):
        self.configure()
        self.mock_provider(lambda request: httpx.Response(200, json={"data": [{"id": {"private": TEST_KEY}}]}))
        client = KimiClient()
        with self.assertRaisesRegex(ModelError, "目录返回格式") as raised:
            await client.connect()
        self.assertNotIn(TEST_KEY, str(raised.exception))
        self.assertTrue(self.http_clients[0].is_closed)


if __name__ == "__main__":
    unittest.main()
