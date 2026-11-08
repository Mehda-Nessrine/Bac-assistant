"""Generator: second Gemini call. Writes the answer for the student.

Not every route needs Gemini:
  - needs_clarification / error -> the router's message is returned as is
  - suggest_exercises           -> built by Python from the catalog
  - solve_* / explain / general -> Gemini (with the official correction and the figures when available)
"""
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import config
import llm_utils
from router import format_history

MODES = ("full", "hints")
MAX_IMAGES = 6


@dataclass
class Answer:
    text: str
    ids: list = field(default_factory=list)       # dataset exercises used
    figures: list = field(default_factory=list)   # image paths of the statement, so the UI can show them
    used_gemini: bool = False
    notes: list = field(default_factory=list)


# ---------- prompts ----------

BASE_RULES = """You are a friendly and rigorous tutor for the Algerian Baccalaureate (BAC) in mathematics.

LANGUAGE
- Answer in the language of the student's message. If the student writes Arabic or Algerian Darija,
  answer in clear Modern Standard Arabic with simple explanations, like a good teacher. If French, answer in French.
- Write every formula in LaTeX between dollar signs, e.g. $f'(x)=e^x(x+2)$.

QUALITY
- Be accurate. Double-check calculations. Show the key steps a BAC student must write.
- Never invent the text of an exam exercise. If you are not sure of an exam statement, say so and ask the student to paste it.
"""

DATASET_RULES = """
DATASET EXERCISE
- The OFFICIAL CORRECTION in the context is the reference. Your final results must match it.
  Explain it as a clear worked solution (you may add reasoning between its steps), but never change its results.
  If it seems incomplete or inconsistent, say so briefly instead of silently changing it.
- Use ONLY the statement, descriptions and images provided. Read values from the images carefully;
  if something is not readable, say so.
"""

MODE_FULL = """
MODE: FULL SOLUTION
- Give a complete, well organized solution. Label every sub-question and highlight each final result.
"""

MODE_HINTS = """
MODE: HINTS ONLY (progressive)
- Do NOT give the full solution. Do NOT state final results, nor numeric values read from the figure or the correction.
- If the student asks about the whole exercise: give a very short overview (which lessons are needed),
  then hints for the FIRST sub-question only. Invite the student to try it and to ask for the next one.
- If the student asks about one sub-question: give hints for that sub-question only.
- Each hint: (1) the lesson or theorem to use, (2) the first step or a guiding question, (3) one short nudge.
- End by saying the student can switch to the "full solution" option (the mode selector) to see the complete answer.
"""

NOT_IN_DATASET = """
NOTE: The student asks about an exam ({year}) that is NOT in your database. Start by saying so briefly,
then help from your own knowledge. If you do not remember the exact statement, ask the student to paste it.
"""


# ---------- context ----------

def _figures_text(figs, label):
    lines = [f"- {f.get('description_ar') or f.get('description_fr') or '(figure)'}" for f in figs]
    return f"{label}:\n" + "\n".join(lines) + "\n" if lines else ""


def build_exercise_context(chunk) -> str:
    return (
        f'=== EXERCISE: BAC {chunk["year"]}, subject {chunk["subject"]}, exercise {chunk["exercise_number"]} '
        f'({chunk["points"]} pts) ===\n'
        f'Topic: {chunk["topic"]}\n\nSTATEMENT:\n{chunk["statement"]}\n\n'
        f'{_figures_text(chunk["figures_sujet"], "Figures in the statement (descriptions)")}'
        f'\n=== OFFICIAL CORRECTION ===\n{chunk["solution"] or "(no correction available: solve it yourself)"}\n\n'
        f'{_figures_text(chunk["figures_corr"], "Figures in the correction (descriptions)")}'
    )


def _image_parts(chunk, mode, notes):
    """Statement figures always; correction figures only in full mode (so hints don't leak the answer)."""
    figs = list(chunk["figures_sujet"]) + (list(chunk["figures_corr"]) if mode == "full" else [])
    parts = []
    for f in figs[:MAX_IMAGES]:
        p = Path(f["path"])
        if not p.exists():
            notes.append(f"image not found: {p.name}")
            continue
        mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        parts.append({"mime": mime, "data": p.read_bytes()})
    return parts


def _suggest_text(route, by_id) -> str:
    lines = ["هذه تمارين من الباك تناسب طلبك:", ""]
    for i, cid in enumerate(route.ids, 1):
        c = by_id[cid]
        lines.append(f'{i}. **باك {c["year"]} – الموضوع {c["subject"]} – التمرين {c["exercise_number"]}** '
                     f'({c["points"]} نقاط): {c["topic"]}')
    lines += ["", "قولي أي تمرين تحب نحلوه معاك، مثلا: «حلي لي التمرين 3 تاع 2019 الموضوع الأول»."]
    return "\n".join(lines)


# ---------- Gemini call ----------

def _call_gemini(client, system: str, parts: list, model: str = None) -> str:
    """parts: list of str or {'mime','data'} dicts. Isolated so it can be mocked in tests."""
    from google.genai import types
    contents = []
    for p in parts:
        if isinstance(p, str):
            contents.append(types.Part.from_text(text=p))
        else:
            contents.append(types.Part.from_bytes(data=p["data"], mime_type=p["mime"]))
    resp = client.models.generate_content(
        model=model or config.GENERATOR_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=system, temperature=0.3),
    )
    return resp.text


# ---------- public API ----------

def generate(route, loaded, client, mode: str = "full", history=None) -> Answer:
    """Never raises. mode: 'full' (complete solution) or 'hints'."""
    if mode not in MODES:
        mode = "full"
    by_id = loaded.by_id()

    # 1) no Gemini needed
    if route.intent in ("needs_clarification", "error"):
        return Answer(text=route.clarification or "")
    if route.intent == "suggest_exercises":
        return Answer(text=_suggest_text(route, by_id), ids=route.ids)

    # 2) build the Gemini request
    notes, images, figures = [], [], []
    system = BASE_RULES
    context = ""

    chunks = [by_id[i] for i in route.ids if i in by_id]
    if route.intent in ("solve_exercise", "solve_subquestion") and chunks:
        system += DATASET_RULES + (MODE_HINTS if mode == "hints" else MODE_FULL)
        context = build_exercise_context(chunks[0])
        images = _image_parts(chunks[0], mode, notes)
        shown = list(chunks[0]["figures_sujet"]) + (list(chunks[0]["figures_corr"]) if mode == "full" else [])
        figures = [f["path"] for f in shown if Path(f["path"]).exists()]   # corr. figures only in full mode
        if route.intent == "solve_subquestion" and route.sub_question:
            context += f'\nThe student asks ONLY about sub-question "{route.sub_question}". Answer only that part ' \
                       f'(recall earlier results briefly if needed).\n'
    elif route.intent == "explain_concept" and chunks:
        context = "Example exercise you may use to illustrate (optional):\n" + build_exercise_context(chunks[0])
        images = _image_parts(chunks[0], "hints", notes)
        figures = []
    else:  # general (or anything else)
        if route.year and route.year not in loaded.years:
            system += NOT_IN_DATASET.format(year=route.year)
        if mode == "hints":
            system += "\nIf the student asks to solve a problem, prefer guiding hints over the full solution.\n"

    text = (
        f"Conversation so far:\n{format_history(history, max_turns=6, max_chars=500)}\n\n"
        f"{context}\nStudent's request:\n{route.standalone_question}"
    )
    parts = [text] + images

    # 3) call Gemini: retries, back-off and fallback model are handled by llm_utils
    models = list(dict.fromkeys([config.GENERATOR_MODEL] + list(getattr(config, "GENERATOR_FALLBACKS", []))))
    out, err, used = llm_utils.call_with_retry(lambda m: _call_gemini(client, system, parts, m), models)

    if err is None:
        if used != models[0]:
            notes.append(f"used fallback model: {used}")
        if out and out.strip():
            return Answer(text=out, ids=route.ids if chunks else [], figures=figures,
                          used_gemini=True, notes=notes)
        return Answer(text="ما قدرتش نولّد جواب لهذا السؤال. جرّب تعيد صياغته.",
                      notes=notes + ["empty response from Gemini"])

    busy = llm_utils.is_quota_error(err) or llm_utils.is_transient_error(err)
    msg = ("الخدمة مشغولة حاليا. عاود المحاولة بعد دقيقة." if busy
           else "صرات مشكلة تقنية. عاود المحاولة من فضلك.")
    return Answer(text=msg, notes=notes + [f"generation failed: {err!r}"[:300]])
