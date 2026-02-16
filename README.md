# Alpha Hub Kernel (v0)

This is a minimal, contract-driven Kernel implementation:
- REST: /v1/health, /v1/capabilities, /v1/attachments, /v1/messages, /v1/conversations/{id}/messages
- WS: /v1/ws/chat?conversation_id=...

## Run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export ALPHA_HUB_TOKEN="dev-token"
# Alternatively, put ALPHA_HUB_TOKEN / ALPHA_HUB_LLM_API_KEY in .env (auto-loaded on startup)
uvicorn alpha_hub.app:app --reload --host 0.0.0.0 --port 8000
```

## Quick check
```bash
curl -H "Authorization: Bearer dev-token" http://localhost:8000/v1/health
```
