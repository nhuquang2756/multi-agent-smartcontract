# Marlowe Studio UI preview

Static, dependency-free frontend concept for the AI-Agent-SC research pipeline.

## Run locally

From the repository root:

```powershell
python -m http.server 4173 --directory ui
```

Open `http://127.0.0.1:4173`.

## Included screens

1. Contract prompt and benchmark-family selector.
2. Clarification and requirement-history view.
3. IntentSpec review and explicit ratification boundary.
4. Marlowe Core V1 candidate and mapping evidence.
5. AST/lint, SMT, comparison, exploration and authority gates.
6. User-reviewed behavior expectation/reference comparison.
7. Bounded exploration, property observations and opt-in ledger-size analysis.
8. Run history and sanitized usage metadata.

The provider dialog accepts a provider, model ID and API key. The API key is held only in the current page's JavaScript memory, cleared from the password input when the dialog closes, and never written to local storage or sent by this preview. The endpoint field appears only for a custom OpenAI-compatible provider.

## Conversational requirement flow

The primary workspace is a multi-turn chat surface. The UI communicates the intended sequence: initial natural-language request, clarification questions and user replies, explicit IntentSpec review, then Marlowe candidate generation. The “Xem hội thoại minh họa” control runs a clearly labeled static UI scenario only; it does not call an AI provider or claim to be a real backend response. Submitting a real draft currently reports that the backend is not connected.

## Current integration boundary

This repo exposes the interactive pipeline through `research/orchestration/cli_runner.py`; it does not currently expose HTTP routes for a browser client. Buttons that would start runs, approve intent, or execute analyzers are therefore disabled or report that no backend connection exists. The UI does not generate fake LLM, SMT, reference, exploration or ledger results.

The family selector lists the 19 contract families represented in dataset v4 (omitting its `infeasible` test class) plus a custom option. These are prompt-organization hints. A selected family is not a claim that a matching deterministic compiler/profile is implemented or verified in the runtime pipeline.

## UI conventions

- `PASS/VALID`, `FAIL/INVALID`, `BLOCKED/UNAVAILABLE`, and `INCONCLUSIVE` must remain distinct when API data is connected.
- A successful gate is scoped to that gate's declared model and evidence.
- Generated Marlowe remains `CANDIDATE_ONLY`; testnet and deployment are disabled in the current backend.
- The page has dark and light themes and adapts to tablet/mobile widths.
