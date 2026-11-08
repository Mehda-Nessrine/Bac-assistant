"""Router: first Gemini call. Understands the student's message and decides what to do.

Gemini only *decides* (intent + which exercise ids). Python then validates the decision,
so a hallucinated id or a wrong year can never reach the generator.
"""
import enum
import json
from dataclasses import dataclass, field
from typing import List, Optional

from pydantic import BaseModel, Field

import config
import llm_utils


# ---------- what Gemini must return ----------

class Intent(str, enum.Enum):
    solve_exercise = "solve_exercise"            # full exercise from the dataset
    solve_subquestion = "solve_subquestion"      # one sub-question of a dataset exercise
    suggest_exercises = "suggest_exercises"      # "give me exercises about complex numbers"
    explain_concept = "explain_concept"          # explain a lesson (optionally using a dataset exercise)
    general = "general"                          # anything else: normal math/bac chat, or not in dataset
    needs_clarification = "needs_clarification"  # really cannot proceed without asking


class RouterDecision(BaseModel):
    intent: Intent
    language: str = Field(description="Language of the student's message: ar, darija, fr, en, or mixed")
    standalone_question: str = Field(
        description="The student's request rewritten so it is fully self-contained "
                    "(resolve 'the second question', 'the same exercise' using the history). "
                    "Same language as the student.")
    year: Optional[int] = Field(default=None, description="Exam year requested, if any")
    subject: Optional[int] = Field(default=None, description="1 or 2 (first/second subject), if given")
    exercise_number: Optional[int] = Field(default=None, description="Exercise number, if given")
    sub_question: Optional[str] = Field(default=None, description="Sub-question label such as '2' or 'أ', if given")
    selected_ids: List[str] = Field(
        default_factory=list,
        description="Ids copied EXACTLY from the catalog. Empty if nothing in the catalog matches.")
    clarification: Optional[str] = Field(
        default=None, description="Only for needs_clarification: one short question to the student, in their language")


SYSTEM_TEMPLATE = """You are the routing brain of an Algerian Baccalaureate (BAC) mathematics assistant.
You do NOT answer the student. You only decide what to do, and return JSON.

The student may write Modern Standard Arabic, Algerian Darija, French, English, or a mix,
with typos. Understand forms like: "التمرين التالت", "exo 3", "الموضوع الثاني", "sujet 2", "s2", "باك 2022".
"subject" means الموضوع الأول (1) or الموضوع الثاني (2).

DATASET CATALOG (years available: {years}). Format: id | year | subject | exercise | points | topic | tags
{catalog}

INTENT RULES
- solve_exercise: the student wants a specific catalog exercise solved (or says it is the one they mean). selected_ids = exactly 1 id.
- solve_subquestion: same, but only one sub-question. selected_ids = 1 id, and fill sub_question.
- suggest_exercises: the student wants practice exercises on a topic. selected_ids = up to 5 ids, best match first.
- explain_concept: the student wants a lesson/concept explained. selected_ids = 0-2 catalog ids ONLY if one is a really good example, else empty.
- general: everything else: simple math questions, other exercises not in the catalog, a year that is not in the catalog,
  exercises the student pasted in the message, study advice, greetings. selected_ids = [].
- needs_clarification: use ONLY when you truly cannot proceed, for example the exercise number is given but the
  year or subject is missing and both could exist. Prefer a reasonable guess over asking.

IMPORTANT
- NEVER invent an id. Copy ids exactly from the catalog or leave selected_ids empty.
- If the student asks for a year that is not in the catalog, use intent=general and keep year = that year.
- Use the conversation history and the "last exercise discussed" to resolve follow-ups such as "والسؤال 2؟" or "explain more".
- standalone_question must contain everything needed to answer without the history.
"""


# ---------- result after Python validation ----------

@dataclass
class Route:
    intent: str
    standalone_question: str
    language: str = "unknown"
    ids: list = field(default_factory=list)       # validated chunk ids
    use_dataset: bool = False
    year: Optional[int] = None
    sub_question: Optional[str] = None
    clarification: Optional[str] = None
    notes: list = field(default_factory=list)     # why Python changed/ignored something (debug)


# ---------- helpers ----------

def format_catalog(catalog) -> str:
    lines = []
    for c in catalog:
        tags = ", ".join(c.get("topic_tags") or [])
        lines.append(f'{c["id"]} | {c["year"]} | S{c["subject"]} | Ex{c["exercise_number"]} | '
                     f'{c["points"]}pts | {c["topic"]} | {tags}')
    return "\n".join(lines)


def format_history(history, max_turns=4, max_chars=300) -> str:
    if not history:
        return "(none)"
    out = []
    for m in history[-max_turns:]:
        role = "Student" if m.get("role") == "user" else "Assistant"
        out.append(f'{role}: {str(m.get("content", ""))[:max_chars]}')
    return "\n".join(out)


def _call_router(client, system: str, contents: str, model: str = None) -> str:
    """One Gemini call that returns the raw JSON text. Isolated so it is easy to mock/test."""
    from google.genai import types
    resp = client.models.generate_content(
        model=model or config.ROUTER_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=RouterDecision,
            temperature=0.0,
        ),
    )
    return resp.text


def _validate(decision: RouterDecision, by_id: dict) -> Route:
    notes = []
    intent = decision.intent.value

    # keep only ids that really exist (dedupe, keep order)
    ids = []
    for i in decision.selected_ids:
        if i in by_id and i not in ids:
            ids.append(i)
        elif i not in by_id:
            notes.append(f"dropped unknown id: {i}")

    # if a year was requested, ids from another year are a hallucination for solve_* intents
    if intent in ("solve_exercise", "solve_subquestion") and decision.year:
        good = [i for i in ids if by_id[i]["year"] == decision.year]
        if len(good) != len(ids):
            notes.append("dropped ids not matching the requested year")
        ids = good

    if intent in ("solve_exercise", "solve_subquestion"):
        ids = ids[:1]
        if not ids:
            intent = "general"
            notes.append("exercise not found in dataset -> answer from model knowledge")
    elif intent == "suggest_exercises":
        ids = ids[:5]
        if not ids:
            intent = "general"
            notes.append("no matching exercises -> answer from model knowledge")
    elif intent == "explain_concept":
        ids = ids[:2]
    elif intent == "general":
        ids = []

    clarification = decision.clarification
    if intent == "needs_clarification" and not clarification:
        clarification = "Peux-tu préciser l'année et le sujet (1 ou 2) ? / وضّحلي السنة والموضوع (1 ولا 2)؟"

    return Route(
        intent=intent,
        standalone_question=decision.standalone_question,
        language=decision.language,
        ids=ids,
        use_dataset=bool(ids),
        year=decision.year,
        sub_question=decision.sub_question,
        clarification=clarification,
        notes=notes,
    )


# ---------- public API ----------

def route(question: str, history, loaded, client, last_ids=None) -> Route:
    """loaded = loader.LoadResult. Never raises.
    Quota / overload errors -> retries, then a fallback model, then intent="error" (never a silent "general").
    Other failures (malformed JSON...) -> intent="general"."""
    system = SYSTEM_TEMPLATE.format(
        years=", ".join(map(str, loaded.years)),
        catalog=format_catalog(loaded.catalog),
    )
    contents = (
        f"Conversation so far:\n{format_history(history)}\n\n"
        f"Last exercise(s) discussed: {', '.join(last_ids) if last_ids else '(none)'}\n\n"
        f"New student message:\n{question}"
    )
    by_id = loaded.by_id()
    models = list(dict.fromkeys([config.ROUTER_MODEL] + list(getattr(config, "ROUTER_FALLBACKS", []))))

    last_err = None
    for _ in range(2):   # the second pass only matters for malformed JSON
        raw, err, used = llm_utils.call_with_retry(lambda m: _call_router(client, system, contents, m), models)
        if err is not None:
            last_err = err
            break
        try:
            result = _validate(RouterDecision.model_validate_json(raw), by_id)
            if used != models[0]:
                result.notes.append(f"used fallback model: {used}")
            return result
        except Exception as e:
            last_err = e

    if llm_utils.is_quota_error(last_err) or llm_utils.is_transient_error(last_err):
        return Route(
            intent="error",
            standalone_question=question,
            clarification="الخدمة مشغولة حاليا. عاود المحاولة بعد دقيقة.",
            notes=[f"service busy: {last_err!r}"[:300]],
        )
    return Route(intent="general", standalone_question=question,
                 notes=[f"router failed, fallback to general: {last_err!r}"[:300]])
