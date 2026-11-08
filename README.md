# 🎓 BAC Math Assistant (v0.1)

An AI tutor for the **Algerian Baccalaureate (BAC) in mathematics**.
Students can write in **Modern Standard Arabic, Algerian Darija, French or English** (even mixed, even with typos) and the assistant will:

- solve a **specific official BAC exercise** (e.g. *"حلي لي التمرين التالت تاع باك 2022 الموضوع الأول"*),
- answer **only one sub-question** of an exercise,
- **suggest practice exercises** on a topic (e.g. complex numbers),
- **explain a concept** (limits, derivatives, probability...),
- answer any **general maths question**.

> ⚠️ This is the **first version (v0.1)**: a working prototype, not a finished product.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🧭 **Smart routing** | A first LLM call understands the message and decides *what to do* (intent + which exercise). |
| 📚 **Grounded answers** | For dataset exercises, the model receives the **official correction** and the **figures (images)**, and must not contradict the correction. |
| 💡 **Two modes** | **Full solution** or **Hints only** (progressive hints that don't reveal the answer). |
| 🗣️ **Multilingual** | Arabic, Darija, French, English. Answers in the student's language. |
| 🛡️ **Hallucination guard** | The LLM only *chooses* exercise IDs; Python validates them against the catalog before anything else happens. |
| 🔁 **Robust API calls** | Retries, exponential back-off, quota handling and **fallback models**. |
| 🖼️ **Figures display** | Exercise figures are shown next to the chat. |
| 🧮 **LaTeX** | Formulas are rendered in the chat UI. |

---

## 🏗️ How it works

```
Student message
      │
      ▼
┌───────────────┐   catalog of exercises (id, year, subject, topic, tags)
│    ROUTER     │ ◄─────────────────────────────────────────────────────
│ (Gemini call 1│   returns JSON: intent, language, year, subject,
│  JSON output) │   exercise_number, sub_question, selected_ids...
└──────┬────────┘
       │  Python validates the decision (unknown ids dropped,
       │  wrong year dropped, fallback to "general" if nothing matches)
       ▼
┌───────────────┐
│   GENERATOR   │  Builds the context: statement + official correction
│ (Gemini call 2│  + figure images → writes the final answer
│  or pure Py)  │  (suggestions are built by Python, no LLM needed)
└──────┬────────┘
       ▼
   Gradio chat UI
```

### The router's intents

| Intent | Meaning |
|---|---|
| `solve_exercise` | Solve a full exercise from the dataset |
| `solve_subquestion` | Solve one sub-question of a dataset exercise |
| `suggest_exercises` | Recommend up to 5 exercises on a topic |
| `explain_concept` | Explain a lesson (optionally with a dataset exercise as example) |
| `general` | Anything else (simple maths, exercise not in dataset, greetings...) |
| `needs_clarification` | Ask the student for the missing info (year / subject) |

### Why two LLM calls?
Separating **deciding** from **answering** makes the system safer and easier to debug:
the router is cheap, deterministic (`temperature=0`) and its output is validated by code,
while the generator can focus on writing a good explanation.

---

## 📁 Project structure

```
bac-assistant/
├── app.py            # Gradio web interface
├── assistant.py      # Glue: loader + router + generator (no UI code)
├── router.py         # Call 1: understand the message, choose intent & exercise
├── generator.py      # Call 2: write the answer (full / hints modes)
├── llm_utils.py      # Retries, back-off, quota errors, fallback models
├── loader.py         # Loads the dataset (JSON + images) and builds the catalog
├── config.py         # Models, paths, API key handling
├── requirements.txt
├── .env.example
├── data/             # Exam dataset (not included), one folder per year
└── notebooks/
    └── bac-chatbot.ipynb   # Development notebook (Kaggle)
```

---

## 📚 Data

The exam data is **not included** in this repository. Put your own files in the `data/` folder (one sub-folder per exam year) and the app will load them at startup.

> 📌 *Add here the source of your data and your rights to publish it.*

---

## 🚀 Getting started

### 1. Clone and install
```bash
git clone https://github.com/<your-username>/bac-assistant.git
cd bac-assistant
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Add your Gemini API key
Get a key from [Google AI Studio](https://aistudio.google.com/apikey), then:
```bash
cp .env.example .env
# edit .env and set GEMINI_API_KEY=...
```

### 3. Add the data
Put your exam files in `data/<year>/`.

### 4. Run
```bash
python app.py
```
Open the local URL printed in the terminal. For a public link (Kaggle / Colab):
```bash
GRADIO_SHARE=1 python app.py
```

### Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | – | Your API key (**required**) |
| `ROUTER_MODEL` | see `config.py` | Model for the router |
| `GENERATOR_MODEL` | see `config.py` | Model for the answer |
| `ROUTER_FALLBACKS` / `GENERATOR_FALLBACKS` | the other role's model | Comma-separated backup models |
| `BAC_DATA_DIR` | `./data` | Dataset location |
| `BAC_CACHE_DIR` | `./.cache` | Cache location |

> Model names change over time. List the ones your key can use with `client.models.list()`.

---

## 💬 Example questions

- `حلي لي التمرين الأول تاع باك 2022 الموضوع الأول`
- `exo 4 sujet 2 2019`
- `عطيني تمارين على الأعداد المركبة`
- `شرحلي كيفاش نحسب نهاية دالة أسية`
- `والسؤال الثاني كيفاش؟` *(follow-up, uses the conversation history)*

---

## ⚠️ Known limitations (v0.1)

- Only covers the years present in the dataset.
- Answers depend on the quality of the LLM; the official correction is the reference, but mistakes are still possible. **Always check with your teacher.**
- Free-tier API quotas can make answers slow (the app retries and uses fallback models).
- No automated tests yet.
- Mathematical statements pasted by the student are not parsed specially (handled as a general question).

## 🛣️ Roadmap

- [ ] Add more exam years and the other streams (sciences, technique math, gestion...)
- [ ] Unit tests for `router._validate` and `llm_utils`
- [ ] Student can upload a photo of an exercise
- [ ] Quiz / exam-simulation mode
- [ ] Deploy on Hugging Face Spaces
- [ ] Evaluation set to measure answer accuracy

---

## 🧰 Tech stack

Python • [Google Gemini API](https://ai.google.dev/) (`google-genai`) • Pydantic (structured output) • [Gradio](https://www.gradio.app/)

## 📄 License

Choose a license (e.g. MIT for the code) and add a `LICENSE` file. The exam data may have its own terms.
