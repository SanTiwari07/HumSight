"""Wiring test for GeminiProvider with a fake client (no network, no key)."""
from types import SimpleNamespace

from google.genai import types

from conftest import make_clip
from humsight.agent.loop import run_agent
from humsight.agent.provider_gemini import GeminiProvider
from humsight.agent.state import JobParams, JobState


class FakeModels:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def generate_content(self, model, contents, config):
        self.calls.append(len(contents))
        name, args, text = self.script.pop(0)
        parts = [types.Part.from_text(text=text)] if text else []
        content = types.Content(role="model", parts=parts)
        return SimpleNamespace(function_calls=[SimpleNamespace(name=name, args=args)],
                               candidates=[SimpleNamespace(content=content)])


def test_gemini_provider_drives_the_loop(quiet, tmp_path):
    script = [("probe_clip", {}, "Start with the probe."),
              ("scan_motion", {"grid": "coarse"}, "Scan the grid."),
              ("classify_peaks", {}, "Classify the peaks."),
              ("file_report", {"verdict": "NO_FAULT", "summary": "No localized vibration above SNR 6.0."}, "")]
    client = SimpleNamespace(models=FakeModels(script))
    prov = GeminiProvider(client=client, brief={})
    st = JobState(make_clip(quiet), JobParams(policy="llm", render=False), str(tmp_path))
    r = run_agent(st, prov)
    assert r["verdict"] == "NO_FAULT" and r["n_tool_calls"] == 4
    assert {e["source"] for e in r["trace"] if e["kind"] == "tool"} == {"llm"}
    # each request carries the growing conversation (brief, call, response, ...)
    assert client.models.calls == sorted(client.models.calls) and client.models.calls[0] == 1


def test_function_declarations_use_json_schema():
    from humsight.agent.tools import TOOLS
    prov = GeminiProvider(client=SimpleNamespace(models=None), brief={})
    cfg = prov._make_config("sys", TOOLS)
    assert len(cfg.tools[0].function_declarations) == len(TOOLS)
    assert cfg.automatic_function_calling.disable is True
