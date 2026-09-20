"""FastAPI interface. Start with:  python -m src.api   (docs at http://localhost:8000/docs, metrics at /metrics)."""
import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from prometheus_client import make_asgi_app

from . import config
from .pipeline import SupportPipeline, kill_switch_on

app = FastAPI(title="CloudServe Support Triage", version=config.SYSTEM_VERSION)
app.mount("/metrics", make_asgi_app())
_pipe: Optional[SupportPipeline] = None


def pipe() -> SupportPipeline:
    global _pipe
    if _pipe is None:
        _pipe = SupportPipeline()
    return _pipe


@app.get("/health")
def health():
    p = pipe()
    return {"status": "ok", "version": config.SYSTEM_VERSION, "retrieval": p.retriever.backend,
            "llm_configured": bool(config.OPENROUTER_API_KEY) and p.llm.enabled, "kill_switch": kill_switch_on()}


@app.post("/ticket")
def ticket(payload: dict):
    """Accepts one ticket in the dataset schema (any of the four channels). Never returns a 5xx for bad input."""
    return pipe().process(payload)


@app.post("/admin/kill-switch")
def kill_switch(on: bool, x_admin_token: str = Header(default="")):
    """Stops all automatic answering immediately (next ticket), no deployment. Requires ADMIN_TOKEN."""
    tok = os.getenv("ADMIN_TOKEN", "")
    if not tok or x_admin_token != tok:
        raise HTTPException(403, "admin token required")
    f = config.KILL_SWITCH_FILE
    if on:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("on")
    elif f.exists():
        f.unlink()
    return {"kill_switch": kill_switch_on()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
