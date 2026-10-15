"""Isolated expansion API contracts: temporary SQLite/PDFs, no provider network.

ASGITransport deliberately does not start the application lifespan, so neither
model discovery nor production manual seeding occurs in these tests.
"""
import asyncio
import base64
import importlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from PIL import Image
import pymupdf

from interview.services import Services
from interview.media import MediaService, normalise_image


class NoNetworkClient:
    model = "test-model"
    models = ["test-vision"]
    report = {"available": True, "name": "test-model", "status": "test"}

    def __init__(self):
        self.requests = []

    async def connect(self):
        pass

    async def request(self, messages, **kwargs):
        self.requests.append((messages, kwargs))
        if kwargs.get("model") != "test-vision":
            raise AssertionError("Test unexpectedly requested a planner")
        return {"content": "图片中可见测试符号，不能据此确认车辆故障。", "model": "test-vision", "tool_calls": [], "usage": {}}


def image_data():
    output = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


def sample_pdf():
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), "TEST ONLY - EC40 2026 UK child restraint instructions. WARNING: child restraint and airbag conditions must be checked.")
        return pdf.tobytes()


class ExpansionAPITests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.bootdir = tempfile.TemporaryDirectory(prefix="cockpit-api-bootstrap-")
        cls.bootservices = Services(Path(cls.bootdir.name))
        # Avoid opening the deliverable's actual SQLite store on app import.
        with patch("interview.services.Services", return_value=cls.bootservices):
            cls.module = importlib.import_module("interview.app")

    @classmethod
    def tearDownClass(cls):
        asyncio.run(cls.bootservices.close())
        cls.bootdir.cleanup()

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cockpit-api-test-")
        self.services = Services(Path(self.temp.name))
        self.model = NoNetworkClient()
        self.media = MediaService(self.model)
        self.media.model = "test-vision"
        self.patch = patch.multiple(self.module, services=self.services, client=self.model, media=self.media,
                                    sessions={}, lab_sessions={}, locks={}, histories={}, contexts={})
        self.patch.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.module.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.patch.stop()
        await self.services.close()
        self.temp.cleanup()

    async def chat(self, text, channel="workspace", session_id="unit"):
        response = await self.client.post("/api/studio/chat", json={"session_id": session_id, "text": text, "provider": "offline", "channel": channel})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_workspace_actuators_do_not_change_frozen_lab(self):
        result = await self.chat("天窗开30%")
        self.assertEqual(result["vehicle"]["sunroof_percent"], 30)
        lab = (await self.client.get("/api/studio/bootstrap", params={"session_id": "unit", "channel": "lab"})).json()
        self.assertNotIn("sunroof_percent", lab["vehicle"])
        legacy = await self.chat("天窗开30%", channel="lab")
        self.assertEqual(legacy["status"], "unsupported")

    async def test_sse_contains_progress_and_one_terminal_result(self):
        response = await self.client.post("/api/studio/chat/stream", json={"session_id": "unit", "text": "开启舒适模式", "provider": "offline"})
        self.assertEqual(response.status_code, 200)
        records = []
        for frame in response.text.split("\n\n"):
            rows = frame.splitlines()
            if rows and rows[0].startswith("event:"):
                records.append((rows[0].split(":", 1)[1].strip(), json.loads(rows[1].split(":", 1)[1])))
        self.assertTrue(any(event == "progress" for event, _ in records))
        final = [value for event, value in records if event == "final"]
        self.assertEqual(len(final), 1)
        self.assertEqual(final[0]["status"], "executed")
        self.assertEqual(len(final[0]["steps"]), 7)
        self.assertEqual(final[0]["vehicle"]["temperature"], 22)

    async def test_confirmation_is_bound_to_requested_channel(self):
        result = await self.chat("打开副驾车门", channel="lab")
        token = result["pending"]["token"]
        wrong = await self.client.post("/api/studio/confirm", json={"session_id": "unit", "channel": "workspace", "token": token})
        self.assertEqual(wrong.json()["status"], "blocked")
        self.assertFalse(self.module.lab_sessions["unit"].vehicle()["doors"]["front_right"])
        correct = await self.client.post("/api/studio/confirm", json={"session_id": "unit", "channel": "lab", "token": token})
        self.assertEqual(correct.json()["status"], "executed")

    async def test_vision_revokes_confirmation_and_has_no_tool_authority(self):
        pending = await self.chat("打开副驾车门")
        token = pending["pending"]["token"]
        response = await self.client.post("/api/studio/vision", json={"session_id": "unit", "image": image_data(), "question": "这个仪表图标是什么？"})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["plan"]["read_only"])
        self.assertFalse(data["calls"])
        self.assertFalse(data["vehicle"]["doors"]["front_right"])
        self.assertIsNone(self.module.sessions["unit"].pending)
        self.assertNotIn("tools", self.model.requests[0][1])
        wrong = await self.client.post("/api/studio/confirm", json={"session_id": "unit", "token": token})
        self.assertEqual(wrong.json()["status"], "blocked")
        self.assertFalse(list(Path(self.temp.name).rglob("*.jpg")))
        self.assertFalse(list(Path(self.temp.name).rglob("*.png")))

    async def test_invalid_image_rejected_before_model_request(self):
        response = await self.client.post("/api/studio/vision", json={"session_id": "unit", "image": "data:image/png;base64,bm90YW5pbWFnZQ=="})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(self.model.requests)

    async def test_manual_selection_controls_query_document(self):
        response = await self.client.post("/api/studio/documents/import", files={"file": ("test_manual.pdf", sample_pdf(), "application/pdf")}, data={"vehicle": "EC40 2026 UK test fixture"})
        self.assertEqual(response.status_code, 200, response.text)
        doc_id = response.json()["data"]["document"]["id"]
        chosen = await self.client.post("/api/studio/workspace", json={"session_id": "unit", "document_id": doc_id})
        self.assertEqual(chosen.status_code, 200)
        self.assertEqual(chosen.json()["active_document_id"], doc_id)
        result = await self.chat("儿童座椅如何安装？")
        self.assertEqual(result["status"], "answered", result)
        self.assertTrue(result["evidence"])
        self.assertTrue(all(e["page"] == 1 for e in result["evidence"]))
        self.assertEqual(result["workspace"]["last_manual"]["document"]["id"], doc_id)
        document = await self.client.get(f"/api/studio/documents/{doc_id}/file")
        self.assertEqual(document.status_code, 200)
        self.assertTrue(document.content.startswith(b"%PDF"))

    async def test_preferences_survive_session_reset_and_cross_session(self):
        saved = await self.client.post("/api/studio/preferences", json={"session_id": "unit", "key": "temperature", "value": "23"})
        self.assertEqual(saved.json()["status"], "executed")
        await self.client.post("/api/studio/reset", json={"session_id": "unit"})
        other = await self.client.get("/api/studio/workspace", params={"session_id": "other"})
        self.assertEqual(other.json()["preferences"][0]["value"], "23")
        result = await self.chat("开启舒适模式", session_id="other")
        self.assertEqual(result["vehicle"]["temperature"], 23)

    async def test_missing_speech_provider_returns_unavailable(self):
        for path, body in [("transcribe", {}), ("synthesize", {"text": "你好"})]:
            response = await self.client.post("/api/studio/speech/" + path, json=body)
            self.assertEqual(response.status_code, 503)
            self.assertIn("浏览器", response.json()["detail"])

    async def test_invalid_session_cannot_alias_another_owner(self):
        response = await self.client.get("/api/studio/preferences", params={"session_id": "../other"})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(self.module.sessions)


class ImageBoundaryTests(unittest.TestCase):
    def test_jpeg_normalization_strips_original_metadata(self):
        normal = normalise_image(image_data())
        self.assertTrue(normal.startswith("data:image/jpeg;base64,"))
        with Image.open(io.BytesIO(base64.b64decode(normal.split(",", 1)[1]))) as image:
            self.assertEqual(image.size, (20, 20))
            self.assertEqual(image.format, "JPEG")

    def test_external_url_not_accepted_as_image(self):
        with self.assertRaises(ValueError):
            normalise_image("https://localhost/private")


if __name__ == "__main__":
    unittest.main()
