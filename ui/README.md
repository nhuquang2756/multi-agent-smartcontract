# Marlowe Studio UI and local bridge

This repo pairs the browser UI with the project's real interactive orchestration pipeline.

## Start the MVP

From the repository root in PowerShell:

```powershell
python -m pip install -r requirements.txt
python -m research.web.server
```

Open <http://127.0.0.1:4173>. This single local server serves the UI and `/api` routes. It binds to `127.0.0.1` only. Stop it with `Ctrl+C`.

Configure a provider, Model ID, and API key in the UI. The key stays in tab memory until the tab closes, is sent to the local bridge when a session starts, and is passed to the selected provider. It is not written to disk or included in run logs. OpenAI, OpenRouter, Gemini, and an OpenAI-compatible custom endpoint are supported. Custom public endpoints must use HTTPS.

## Real interactive flow

1. The browser posts the natural-language prompt and transient model configuration to the local bridge.
2. `research.web.server` creates `ModelTransport` and calls `research.orchestration.cli_runner.run_session` with interactive callbacks.
3. The UI polls session events. Clarification questions block the run until the user replies; answers become versioned requirement history in the pipeline.
4. When extraction resolves, the UI displays the complete IntentSpec and requires explicit approval tied to that exact spec before generation.
5. The result and diagnostics are shown from the backend payload. A generated contract remains `CANDIDATE_ONLY`; the UI does not sign, submit, or deploy it.

Sessions and prompts remain in server memory only and disappear when the server restarts; this MVP does not persist UI run history. The server never prints request bodies or keys. This is a local development MVP, not a multi-user or internet-facing service.

## Integration scope and limitations

The UI is wired to real prompting, multi-turn clarification, explicit IntentSpec approval, candidate output, and run diagnostics. SMT, reference, exploration, and ledger stages keep the backend's real availability and evidence limits; unavailable tools are not represented as passing. The current chat flow does not yet collect an independent reference expectation or configure a ledger node. Family selection is an organizational hint and is not passed as a deterministic compiler profile.

See the main [README](../README.md) for pipeline architecture and existing tool prerequisites.
