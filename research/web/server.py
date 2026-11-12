"""Loopback-only HTTP bridge between the static UI and the real CLI pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import re
import threading
from typing import Any
from urllib.parse import urlsplit
import uuid

from research.adapters.model_transport import ModelTransport, ModelTransportError
from research.orchestration.cli_runner import SessionOptions, run_session
from research.web.storage import SessionStore


ROOT = Path(__file__).resolve().parents[2]
UI_DIR = ROOT / "ui"
MAX_BODY = 256 * 1024
MAX_SESSIONS = 16
OPENROUTER_URL = "https://openrouter.ai/api/v1"
QUESTION_LIMIT = 4
STORE = SessionStore()


@dataclass
class LiveSession:
    session_id: str
    model_name: str
    events: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)
    answers: queue.Queue[str] = field(default_factory=queue.Queue)
    pending: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    status: str = "STARTING"
    intent_spec: dict[str, Any] | None = None
    error: str | None = None
    worker: threading.Thread | None = None
    waiting_for_intent_json: bool = False

    def add_event(self, kind: str, **data: Any) -> None:
        with self.lock:
            event = {"id": len(self.events) + 1, "type": kind, **data}
            self.events.append(event)
            STORE.event(self.session_id, event)
            STORE.update(self.session_id, status=self.status, pending=self.pending,
                         result=self.result, error=self.error)

    def emit(self, message: str) -> None:
        text = str(message)
        if text == "Diễn giải intent được đề nghị:":
            self.waiting_for_intent_json = True
        elif self.waiting_for_intent_json:
            self.waiting_for_intent_json = False
            try:
                value = json.loads(text)
                self.intent_spec = value if isinstance(value, dict) else None
            except json.JSONDecodeError:
                self.intent_spec = None
            if self.intent_spec is not None:
                self.add_event("intent_spec", spec=self.intent_spec)
        self.add_event("progress", message=text)

    def ask(self, prompt: str) -> str:
        clean = str(prompt).strip()
        if "Xác nhận đúng toàn bộ diễn giải" in clean:
            pending = {"type": "intent_approval", "spec": self.intent_spec}
            self.status = "WAITING_APPROVAL"
            self.add_event("approval_requested", spec=self.intent_spec)
        elif "Tên người xác nhận" in clean:
            pending = {"type": "reviewer_name"}
            self.status = "WAITING_USER"
            self.add_event("reviewer_requested")
        else:
            question = re.sub(r"\s*>\s*$", "", clean).strip()
            pending = {"type": "clarification", "question": question}
            self.status = "WAITING_USER"
            self.add_event("clarification", question=question)
        with self.lock:
            self.pending = pending
            STORE.update(self.session_id, status=self.status, pending=self.pending,
                         result=self.result, error=self.error)
        answer = self.answers.get()
        with self.lock:
            self.pending = None
            self.status = "RUNNING"
        return answer

    def snapshot(self, after: int = 0) -> dict[str, Any]:
        with self.lock:
            return {
                "session_id": self.session_id,
                "status": self.status,
                "events": [item for item in self.events if item["id"] > after],
                "pending": self.pending,
                "result": self.result,
                "error": self.error,
            }


SESSIONS: dict[str, LiveSession] = {}
SESSIONS_LOCK = threading.Lock()


def _safe_endpoint(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Nhập Base URL hợp lệ cho provider tùy chỉnh.")
    parts = urlsplit(value.strip())
    if (parts.scheme not in {"https", "http"} or not parts.netloc
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment):
        raise ValueError("Base URL phải là URL HTTP(S) không chứa thông tin đăng nhập.")
    if parts.scheme != "https" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Base URL công khai cần dùng HTTPS.")
    return value.strip().rstrip("/")


def _make_model(body: dict[str, Any]) -> tuple[ModelTransport, str]:
    provider = body.get("provider")
    model = body.get("model")
    api_key = body.get("api_key")
    if provider not in {"openrouter", "openai", "gemini", "custom"}:
        raise ValueError("Provider chưa được hỗ trợ.")
    if not isinstance(model, str) or not model.strip() or len(model) > 200:
        raise ValueError("Model ID không hợp lệ.")
    if not isinstance(api_key, str) or not api_key.strip() or len(api_key) > 4096:
        raise ValueError("Thiếu API key hợp lệ.")
    model = model.strip()
    api_key = api_key.strip()
    try:
        if provider == "gemini":
            return ModelTransport(model=model, provider="gemini",
                                  api_key_override=api_key), "gemini"
        if provider == "openrouter":
            return ModelTransport(model=model, api_key_override=api_key,
                                  base_url_override=OPENROUTER_URL,
                                  api_style="chat"), provider
        if provider == "custom":
            endpoint = _safe_endpoint(body.get("endpoint"))
            return ModelTransport(model=model, api_key_override=api_key,
                                  base_url_override=endpoint, api_style="chat"), provider
        return ModelTransport(model=model, api_key_override=api_key,
                              base_url_override="", api_style="responses"), provider
    except ModelTransportError as exc:
        raise ValueError(f"Cấu hình model không hợp lệ ({exc.code}).") from exc


def _start(body: dict[str, Any]) -> LiveSession:
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 30_000:
        raise ValueError("Prompt phải có nội dung và tối đa 30.000 ký tự.")
    expectation_text = body.get("expectation_text", "")
    if not isinstance(expectation_text, str) or len(expectation_text) > 20_000:
        raise ValueError("Kịch bản kiểm chứng tối đa 20.000 ký tự.")
    model, provider = _make_model(body)
    with SESSIONS_LOCK:
        expired = [key for key, value in SESSIONS.items()
                   if value.status in {"COMPLETE", "BLOCKED", "UNSUPPORTED", "FAILED"}]
        for key in expired:
            if len(SESSIONS) >= MAX_SESSIONS:
                SESSIONS.pop(key, None)
        if len(SESSIONS) >= MAX_SESSIONS:
            raise RuntimeError("Đã có quá nhiều phiên UI đang chạy. Hãy kết thúc phiên cũ trước.")
        live = LiveSession(str(uuid.uuid4()), model_name=model.model)
        SESSIONS[live.session_id] = live
    STORE.create(live.session_id, provider, model.model, prompt.strip())
    live.add_event("user_message", text=prompt.strip())
    if expectation_text.strip():
        live.add_event("verification_scenario", text=expectation_text.strip())

    def worker() -> None:
        try:
            live.status = "RUNNING"
            live.add_event("session_started", provider=provider, model=model.model)
            result = run_session(
                prompt.strip(), model,
                options=SessionOptions(interactive=True, property_dataset_path=None,
                                       expectation_text=(expectation_text.strip() or None)),
                ask=live.ask,
                emit=live.emit,
            )
            with live.lock:
                live.result = result
                live.pending = None
                live.status = ("COMPLETE" if result.get("status") in {
                    "CANDIDATE_ONLY", "LEDGER_SIZE_CHECKED", "SIMULATED_LEDGER_SIZE_CHECKED"
                } else result.get("status", "BLOCKED"))
                STORE.update(live.session_id, status=live.status, pending=None,
                             result=live.result, error=live.error)
            live.add_event("session_finished", status=live.status,
                           stop_reason=result.get("stop_reason"))
        except Exception as exc:  # keep provider details and secrets out of browser errors
            with live.lock:
                live.error = type(exc).__name__
                live.status = "FAILED"
                live.pending = None
                STORE.update(live.session_id, status=live.status, pending=None,
                             result=live.result, error=live.error)
            live.add_event("session_error", message="Phiên không thể hoàn tất. Kiểm tra provider, model và log máy chủ.")

    live.worker = threading.Thread(target=worker, name=f"marlowe-{live.session_id[:8]}", daemon=True)
    live.worker.start()
    return live


class Handler(SimpleHTTPRequestHandler):
    server_version = "MarloweLocal/1.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        # Do not echo request payloads; they may contain names, financial terms or API keys.
        print(f"[marlowe-web] {self.address_string()} {self.command} {self.path.split('?')[0]}")

    def _json(self, status: int, data: dict[str, Any]) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length không hợp lệ.") from exc
        if not 0 < length <= MAX_BODY:
            raise ValueError("Request body rỗng hoặc vượt giới hạn.")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("Request body cần là JSON object.")
        return value

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._json(200, {"ok": True, "pipeline": "research.orchestration.cli_runner",
                             "provider_transport": "ModelTransport", "loopback_only": True})
            return
        if path == "/api/sessions":
            self._json(200, {"sessions": STORE.recent()})
            return
        match = re.fullmatch(r"/api/sessions/([0-9a-f-]{36})", path)
        if match:
            live = SESSIONS.get(match.group(1))
            if live is None:
                saved = STORE.detail(match.group(1))
                if saved is None:
                    self._json(404, {"error": "Không tìm thấy phiên."})
                else:
                    try:
                        after = max(0, int(self.headers.get("X-Event-Cursor", "0")))
                    except ValueError:
                        after = 0
                    saved["events"] = [item for item in saved["events"] if item["id"] > after]
                    self._json(200, saved)
                return
            try:
                after = max(0, int(self.headers.get("X-Event-Cursor", "0")))
            except ValueError:
                after = 0
            self._json(200, live.snapshot(after))
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        try:
            body = self._body()
            if path == "/api/sessions":
                live = _start(body)
                self._json(201, live.snapshot())
                return
            match = re.fullmatch(r"/api/sessions/([0-9a-f-]{36})/(reply|approve|reject|stop)", path)
            if not match:
                self._json(404, {"error": "Không tìm thấy API route."})
                return
            live = SESSIONS.get(match.group(1))
            if live is None:
                self._json(404, {"error": "Không tìm thấy phiên."})
                return
            action = match.group(2)
            with live.lock:
                pending = live.pending
                if action == "reply":
                    answer = body.get("answer")
                    if (pending is None or pending["type"] == "intent_approval"
                            or not isinstance(answer, str) or not answer.strip()
                            or len(answer) > 10_000):
                        self._json(409, {"error": "Phiên chưa chờ câu trả lời hợp lệ."})
                        return
                    live.answers.put(answer.strip())
                elif action == "approve":
                    if (pending is None or pending["type"] != "intent_approval"
                            or live.intent_spec is None
                            or body.get("approved_spec") != live.intent_spec):
                        self._json(409, {"error": "IntentSpec đã thay đổi hoặc chưa sẵn sàng duyệt."})
                        return
                    live.answers.put("dong y")
                elif action == "reject":
                    if (pending is None or pending["type"] != "intent_approval"
                            or live.intent_spec is None
                            or body.get("approved_spec") != live.intent_spec):
                        self._json(409, {"error": "IntentSpec đã thay đổi hoặc chưa sẵn sàng chỉnh sửa."})
                        return
                    live.answers.put("khong dong y")
                else:
                    if pending is None:
                        self._json(409, {"error": "Phiên hiện không chờ phản hồi."})
                        return
                    if pending["type"] == "intent_approval":
                        # Let run_session take its explicit-rejection path, then leave correction blank.
                        live.answers.put("khong dong y")
                        live.answers.put("")
                    else:
                        live.answers.put("")
            self._json(202, {"ok": True, "session": live.snapshot()})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self._json(429, {"error": str(exc)})


def main() -> None:
    port = int(os.environ.get("MARLOWE_UI_PORT", "4173"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    print(f"Marlowe UI + backend bridge: http://127.0.0.1:{port}")
    print("Bound to localhost only. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Marlowe UI server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
