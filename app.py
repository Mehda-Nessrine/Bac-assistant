"""Gradio UI for the BAC assistant.

    python app.py                      # local
    GRADIO_SHARE=1 python app.py       # public link (Kaggle / Colab)
    import app; app.launch(share=True) # from a notebook
"""
import inspect
import os

import gradio as gr

import config
from assistant import Assistant

MODE_CHOICES = [("حل كامل", "full"), ("تلميحات فقط", "hints")]
LATEX = [
    {"left": "$$", "right": "$$", "display": True},
    {"left": "\\[", "right": "\\]", "display": True},
    {"left": "\\(", "right": "\\)", "display": False},
    {"left": "$", "right": "$", "display": False},
]
EXAMPLES = [
    "حلي لي التمرين الأول تاع باك 2022 الموضوع الأول",
    "عطيني تمارين على الأعداد المركبة",
    "شرحلي كيفاش نحسب نهاية دالة أسية",
    "واش هو مشتق x^2 * e^x ؟",
]
EXPANDABLE = ("solve_exercise", "solve_subquestion")


# ---------- helpers ----------

def _kw(cls, **kwargs):
    """Pass only the arguments this Gradio version supports (the API changed between 4/5/6)."""
    allowed = inspect.signature(cls.__init__).parameters
    return {k: v for k, v in kwargs.items() if k in allowed}


def _skip():
    return gr.skip() if hasattr(gr, "skip") else gr.update()


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return str(content.get("text", ""))
    if isinstance(content, (list, tuple)):
        return " ".join(_text_of(c) for c in content)
    return ""


def clean_history(chat):
    """Gradio chat history -> plain [{'role','content'}] with text only."""
    out = []
    for m in chat or []:
        text = _text_of(m.get("content")).strip()
        if text and m.get("role") in ("user", "assistant"):
            out.append({"role": m["role"], "content": text})
    return out


def status_text(assistant) -> str:
    L = assistant.loaded
    s = f"📚 قاعدة البيانات: **{len(L.years)} سنوات** ({', '.join(map(str, L.years))}) • **{len(L.chunks)} تمرين**"
    if L.warnings:
        s += f"\n\n⚠️ {len(L.warnings)} تنبيه في البيانات:\n" + "\n".join(f"- {w}" for w in L.warnings[:10])
    return s


def _gallery(paths):
    return gr.Gallery(value=paths or None, visible=bool(paths))


# ---------- handlers ----------

def make_handlers(assistant):
    def respond(message, chat, mode, last_ids, last_route):
        message = (message or "").strip()
        if not message:
            return "", _skip(), _skip(), _skip(), _skip(), _skip()
        chat = list(chat or [])
        mode = mode if mode in ("full", "hints") else "full"

        route, ans = assistant.ask(message, clean_history(chat), mode, last_ids)

        chat += [{"role": "user", "content": message}, {"role": "assistant", "content": ans.text}]
        if route.ids and route.intent in EXPANDABLE + ("explain_concept",):
            last_ids = list(route.ids)          # remembered for follow-ups like "والسؤال 2؟"
        can_expand = mode == "hints" and ans.used_gemini and route.intent in EXPANDABLE
        return "", chat, _gallery(ans.figures), last_ids, (route if can_expand else None), gr.Button(visible=can_expand)

    def full_solution(chat, last_route):
        if last_route is None:
            return _skip(), _skip(), gr.Button(visible=False), None
        chat = list(chat or [])
        ans = assistant.full_solution(last_route, clean_history(chat))
        chat += [{"role": "user", "content": "اعرض الحل الكامل"}, {"role": "assistant", "content": ans.text}]
        return chat, _gallery(ans.figures), gr.Button(visible=False), None

    def refresh():
        try:
            assistant.reload_data()
            return status_text(assistant)
        except Exception as e:
            return f"❌ تعذر تحميل البيانات: {e}"

    return respond, full_solution, refresh


# ---------- layout ----------

def build_app(assistant):
    respond, full_solution, refresh = make_handlers(assistant)

    with gr.Blocks(title="مساعد الباك – رياضيات") as demo:
        gr.Markdown("# 🎓 مساعد الباك في الرياضيات\nاسألني على تمارين الباك، أو أي سؤال في الرياضيات.")
        status = gr.Markdown(status_text(assistant))

        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(**_kw(gr.Chatbot, label="المحادثة", height=520, rtl=True,
                                           latex_delimiters=LATEX, show_copy_button=True, type="messages"))
                with gr.Row():
                    msg = gr.Textbox(**_kw(gr.Textbox, placeholder="اكتب سؤالك هنا…", show_label=False,
                                           rtl=True, scale=6, lines=1))
                    send = gr.Button("إرسال", variant="primary", scale=1)
                full_btn = gr.Button("📖 اعرض الحل الكامل", visible=False)
            with gr.Column(scale=1):
                mode = gr.Radio(choices=MODE_CHOICES, value="full", label="طريقة الإجابة على التمارين")
                gallery = gr.Gallery(**_kw(gr.Gallery, label="أشكال التمرين", visible=False, columns=1))
                refresh_btn = gr.Button("🔄 تحديث قاعدة البيانات")

        gr.Examples(examples=EXAMPLES, inputs=msg, label="أمثلة")

        last_ids, last_route = gr.State([]), gr.State(None)
        inputs = [msg, chatbot, mode, last_ids, last_route]
        outputs = [msg, chatbot, gallery, last_ids, last_route, full_btn]
        msg.submit(respond, inputs, outputs)
        send.click(respond, inputs, outputs)
        full_btn.click(full_solution, [chatbot, last_route], [chatbot, gallery, full_btn, last_route])
        refresh_btn.click(refresh, None, status)
    return demo


def launch(share=None, **kwargs):
    assistant = Assistant()
    demo = build_app(assistant)
    if share is None:
        share = bool(os.getenv("GRADIO_SHARE"))
    demo.queue().launch(share=share, allowed_paths=[str(config.DATA_DIR.resolve())], **kwargs)
    return demo


if __name__ == "__main__":
    launch()
