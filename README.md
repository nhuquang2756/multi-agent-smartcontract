# multi-agent-smartcontract

Frontend workspace for the Marlowe multi-agent smart contract research project.

## Run the UI preview

From the repository root, run:

```powershell
python -m http.server 4173 --bind 127.0.0.1 --directory ui
```

Then open <http://127.0.0.1:4173> in a browser. The interface is dependency-free HTML, CSS, and JavaScript.

## Current scope

- Eight workspace screens for contract setup, clarification, intent review, candidate AST, verification evidence, reference scenarios, bounded exploration, and run history.
- Multi-turn conversational UI: the intended product flow is request → clarification and replies → explicit IntentSpec approval → Marlowe candidate generation.
- A clearly labeled static conversation preview can demonstrate the clarification interaction. It does not call an AI provider or represent a real model response.
- Provider, model ID, and API-key settings are held in the current browser tab only. The preview does not transmit them.

## Backend integration status

The UI is a frontend preview. The backend repository currently exposes its pipeline through a CLI and does not provide HTTP routes for a browser client. Submitting a prompt therefore reports that no backend is connected; no model, verification, or contract-generation result is fabricated. Generated output must remain `CANDIDATE_ONLY`; testnet and deployment are disabled.

See [ui/README.md](ui/README.md) for the screen map, design notes, and integration boundaries.
