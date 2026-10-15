"""Synthetic browser recognition/TTS lifecycle with actual offline workspace API.

This checks dispatch and UI state, not microphone audio, ASR quality, or hardware.
"""
from pathlib import Path
import json
import os
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("STUDIO_TEST_URL", "http://127.0.0.1:8788")
SCRIPT = """
window.__voice = {starts:0,cancels:0,spoken:[]};
class FakeRecognition {
  start(){window.__voice.recognition=this;window.__voice.starts++;}
  stop(){queueMicrotask(()=>this.onend?.());}
}
window.SpeechRecognition = FakeRecognition;
window.webkitSpeechRecognition = undefined;
Object.defineProperty(window,'speechSynthesis',{configurable:true,value:{
  cancel(){window.__voice.cancels++;},
  speak(utterance){window.__voice.utterance=utterance;window.__voice.spoken.push(utterance.text);}
}});
window.__say = text => {const row=[{transcript:text}]; row.isFinal=true; window.__voice.recognition.onresult({results:[row]});};
"""
checks, errors = [], []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.add_init_script(SCRIPT)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.get_by_label("推理提供方").select_option("offline")
    page.get_by_role("button", name="开启连续语音").click()
    expect(page.locator(".workspace-voice-bar")).to_contain_text("正在聆听")
    page.evaluate("window.__say('空调温度设为23度')")
    expect(page.locator(".meridian-message.assistant")).to_have_count(1)
    expect(page.locator(".meridian-temperature>strong")).to_contain_text("23")
    expect(page.locator(".workspace-voice-bar")).to_contain_text("正在播报")
    checks.append("final recognition automatically dispatches through actual guarded API")
    assert page.evaluate("window.__voice.spoken.length") == 1
    before = page.evaluate("window.__voice.cancels")
    page.get_by_role("button", name="打断并说话").click()
    expect(page.locator(".workspace-voice-bar")).to_contain_text("正在聆听")
    assert page.evaluate("window.__voice.cancels") > before
    page.evaluate("window.__say('副驾车窗开50%')")
    expect(page.locator(".meridian-message.assistant")).to_have_count(2)
    expect(page.locator(".window-1 strong")).to_contain_text("50")
    checks.append("explicit barge-in cancels TTS and accepts next utterance")
    starts = page.evaluate("window.__voice.starts")
    page.evaluate("window.__voice.utterance.onend()")
    page.wait_for_function("window.__voice.starts > " + str(starts))
    expect(page.locator(".workspace-voice-bar")).to_contain_text("正在聆听")
    checks.append("continuous mode resumes recognition after TTS completes")
    page.evaluate("window.__say('停止聆听')")
    expect(page.get_by_role("button", name="开启连续语音")).to_be_visible()
    expect(page.locator(".meridian-message.assistant")).to_have_count(2)
    checks.append("spoken stop exits locally without backend action")
    page.get_by_role("button", name="开启连续语音").click()
    page.evaluate("window.__voice.recognition.onerror({error:'not-allowed'});window.__voice.recognition.onend()")
    expect(page.get_by_role("alert")).to_contain_text("not-allowed")
    expect(page.get_by_role("button", name="开启连续语音")).to_be_visible()
    checks.append("microphone rejection exits loop with explicit message")
    page.close()
    unsupported = browser.new_page()
    unsupported.add_init_script("window.SpeechRecognition=undefined;window.webkitSpeechRecognition=undefined;")
    unsupported.goto(BASE, wait_until="networkidle")
    expect(unsupported.get_by_role("button", name="开启连续语音")).to_be_disabled()
    expect(unsupported.get_by_label("开始语音识别")).to_be_disabled()
    expect(unsupported.get_by_label("给经纬助手发送指令")).to_be_enabled()
    checks.append("unsupported recognition keeps text input and disables microphone")
    browser.close()
assert not errors, errors
result = {"passed": True, "checks": checks, "page_errors": errors, "api_mocked": False,
          "speech_recognition_events": "synthetic", "speech_synthesis": "stubbed",
          "microphone_hardware_tested": False, "acoustic_quality_tested": False}
(ROOT / "results/voice_browser_lifecycle.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(result, ensure_ascii=False))
