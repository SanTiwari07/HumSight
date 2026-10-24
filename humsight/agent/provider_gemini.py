"""Gemini provider (google-genai SDK). Only compact numeric summaries are sent, never frames."""
from __future__ import annotations

import json
import os
import time

from .tools import compact

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "gemini-flash-latest")


class GeminiProvider:
    name = "llm"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 brief: dict | None = None, client=None):
        from google import genai  # imported lazily so the library has no hard dependency
        from google.genai import types
        self._types = types
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if client is None and not key:
            raise RuntimeError("no Gemini API key")
        self.client = client or genai.Client(api_key=key)
        self.model = model or DEFAULT_MODEL
        self._config = None
        self._sent_results = 0
        self._nudged = False
        self._contents = [types.Content(role="user", parts=[types.Part.from_text(
            text=json.dumps({"job_brief": brief or {},
                             "task": "Analyse this clip using the tools. Begin with probe_clip."}))])]

    def _make_config(self, system: str, tools: list[dict]):
        t = self._types
        decls = [t.FunctionDeclaration(name=x["name"], description=x["description"],
                                       parameters_json_schema=x["parameters"]) for x in tools]
        return t.GenerateContentConfig(
            system_instruction=system, tools=[t.Tool(function_declarations=decls)],
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.2)

    def _generate(self):
        last = None
        for attempt in range(2):
            try:
                return self.client.models.generate_content(
                    model=self.model, contents=self._contents, config=self._config)
            except Exception as e:  # 429 / 5xx: back off once, then let the loop fall back to rules
                last = e
                code = getattr(e, "code", None) or getattr(e, "status_code", None)
                if attempt == 0 and (code in (429, 500, 502, 503, 504) or code is None):
                    time.sleep(2)
                    continue
                raise
        raise last  # pragma: no cover

    def next_action(self, system: str, history: list[dict], tools: list[dict]) -> dict:
        t = self._types
        if self._config is None:
            self._config = self._make_config(system, tools)
        # feed the result of the previous call back to the model
        while self._sent_results < len(history):
            h = history[self._sent_results]
            self._contents.append(t.Content(role="user", parts=[t.Part.from_function_response(
                name=h["tool"], response={"result": compact(h["result"])})]))
            self._sent_results += 1

        resp = self._generate()
        calls = list(getattr(resp, "function_calls", None) or [])
        cand = resp.candidates[0].content if resp.candidates else None
        text = ""
        if cand is not None and cand.parts:
            text = " ".join(p.text for p in cand.parts if getattr(p, "text", None))
        if not calls:
            if not self._nudged:
                self._nudged = True
                if cand is not None:
                    self._contents.append(cand)
                self._contents.append(t.Content(role="user", parts=[t.Part.from_text(
                    text="Call exactly one tool now; finish with file_report or request_review.")]))
                return self.next_action(system, history, tools)
            return {"final": True, "rationale": text[:400]}
        call = calls[0]
        self._contents.append(cand)   # keep the raw model turn (thought signatures included)
        args = json.loads(json.dumps(dict(call.args or {}), default=str))
        return {"tool": call.name, "args": args, "rationale": text[:400]}
