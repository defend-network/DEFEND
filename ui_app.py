from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import gradio as gr

from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from ollama_client import OllamaClient
from defend_system import get_system_prompt

try:
    from production_policy import ProductionPolicy
except ImportError:
    from dev_policy import DevWebPolicy as ProductionPolicy  # fallback if production_policy missing

ROOT = Path(__file__).resolve().parent
LOGO = ROOT / "logo.png"
MODEL = os.environ.get("DEFEND_MODEL", "defend-ai:latest")
HOST = "127.0.0.1"
PORT = int(os.environ.get("DEFEND_PORT", "7860"))

_model = None
_cp = None
_loop = None


def _get_loop():
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def startup_sync():
    global _model, _cp
    loop = _get_loop()
    registry = build_default_registry()
    _model = OllamaClient(model=MODEL)

    async def _open():
        if hasattr(_model, "__aenter__"):
            await _model.__aenter__()
        return ControlPlane(
            tool_registry=registry,
            model_client=_model,
            policy_engine=ProductionPolicy(),
        )

    _cp = loop.run_until_complete(_open())
    print(f"[DEFEND] model={MODEL} tools={list(registry.keys())}")
    print(f"[DEFEND] system_prompt_chars={len(get_system_prompt())}")


def shutdown_sync():
    global _model, _cp
    loop = _get_loop()
    if _model is not None and hasattr(_model, "__aexit__"):

        async def _close():
            await _model.__aexit__(None, None, None)

        try:
            loop.run_until_complete(_close())
        except Exception as e:
            print(f"[DEFEND] shutdown warning: {e}")
    _model = None
    _cp = None


def chat(message, history):
    if _cp is None:
        return "Agent not ready. Restart the app."
    text = (message or "").strip()
    if not text:
        return "Empty message."

    async def _run():
        return await _cp.handle(
            AgentRequest(request_id=str(uuid.uuid4()), message=text)
        )

    try:
        resp = _get_loop().run_until_complete(_run())
    except Exception as e:
        return f"Agent error: {type(e).__name__}: {e}"

    meta = resp.metadata or {}
    content = resp.content or ""
    if meta.get("research_status"):
        content += (
            f"\n\n— research_status: {meta.get('research_status')}"
            f" · evidence: {meta.get('evidence_count', 0)}"
        )
    return content


css = """
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=Inter:wght@400;500;600;700&display=swap');
:root {
  --bg: #070b12; --line: #1e293b; --gold: #c4a35a; --text: #e8eef7; --muted: #94a3b8;
}
html, body { background: var(--bg) !important; }
.gradio-container {
  max-width: 720px !important; margin: 0 auto !important;
  padding: 0 12px 24px !important; font-family: Inter, system-ui, sans-serif !important;
  background: transparent !important;
}
footer, .footer { display: none !important; }
#header {
  position: relative; text-align: center; padding: 1.25rem 0.75rem 1rem;
  margin: 0 -12px 0.85rem; border-bottom: 1px solid rgba(196,163,90,0.35);
  background:
    radial-gradient(120% 80% at 50% -20%, rgba(159,18,57,0.35) 0%, transparent 55%),
    linear-gradient(180deg, #0a1424 0%, #070b12 100%);
}
.brand-mark {
  font-family: "Cormorant Garamond", Georgia, serif; font-weight: 700;
  font-size: clamp(1.85rem, 6vw, 2.35rem); letter-spacing: 0.28em;
  color: var(--text); margin: 0.35rem 0 0.15rem; text-indent: 0.28em;
}
.brand-sub {
  color: var(--muted); font-size: 0.72rem; letter-spacing: 0.14em;
  text-transform: uppercase; margin: 0; font-weight: 500;
}
.brand-rule {
  width: 56px; height: 2px; margin: 0.65rem auto 0.25rem;
  background: linear-gradient(90deg, transparent, var(--gold), transparent);
}
.enjoy-line {
  text-align: center; color: var(--gold);
  font-family: "Cormorant Garamond", Georgia, serif; font-size: 1.15rem;
  font-weight: 600; letter-spacing: 0.35em; text-indent: 0.35em;
  margin: 0.1rem 0 0.9rem;
}
.site-footer {
  text-align: center; color: #64748b; font-size: 0.7rem; letter-spacing: 0.12em;
  text-transform: uppercase; margin-top: 1.1rem; padding-bottom: 1.5rem;
}
"""

startup_sync()

with gr.Blocks(title="DEFEND AI") as demo:
    with gr.Column(elem_id="header"):
        if LOGO.exists():
            gr.Image(
                value=str(LOGO),
                show_label=False,
                container=False,
                height=72,
                interactive=False,
            )
        gr.HTML(
            '<div class="brand-mark">DEFEND</div>'
            '<div class="brand-sub">For European-heritage Americans</div>'
            '<div class="brand-rule"></div>'
        )

    with gr.Tab("Chat"):
        gr.HTML('<p class="enjoy-line">ENJOY</p>')
        gr.ChatInterface(
            fn=chat,
            chatbot=gr.Chatbot(height=520, show_label=False),
            textbox=gr.Textbox(
                placeholder="Speak clearly. Think carefully. Use wisely.",
                container=False,
                scale=7,
            ),
            examples=[
                "Who is an American?",
                "Find official BJS Black and White adult imprisonment rates and cite sources.",
                "Find recent official U.S. southwest border encounter statistics and cite sources.",
                "What is DEFEND in one sentence?",
            ],
        )

    gr.HTML('<div class="site-footer">Made in America · defend-network.org</div>')


if __name__ == "__main__":
    try:
        demo.queue().launch(
            server_name=HOST,
            server_port=PORT,
            inbrowser=False,
            allowed_paths=[str(ROOT)],
            theme=gr.themes.Base(
                primary_hue="red",
                neutral_hue="slate",
                font=gr.themes.GoogleFont("Inter"),
            ).set(
                body_background_fill="#0c0f14",
                body_text_color="#e2e8f0",
                block_background_fill="#111827",
                block_border_color="#1e293b",
                input_background_fill="#0f172a",
                button_primary_background_fill="#9f1239",
                button_primary_background_fill_hover="#be123c",
                button_primary_text_color="#ffffff",
            ),
            css=css,
        )
    finally:
        shutdown_sync()
