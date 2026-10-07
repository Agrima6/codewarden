# Demo guide

> For the mid-term evaluation use [DEMO_DAY.md](DEMO_DAY.md), which maps every evaluation criterion to something you can show.


A 6-minute walkthrough that works with **no API key and no internet**. Add a Gemini key (or Ollama) to show the AI-only extras in step 6.

## Before you present

```bash
cd codewarden
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web,langchain,dev]"
pytest -q                 # 82 passing
codewarden demo           # opens http://127.0.0.1:8765 with 3 demo PRs already reviewed
```

Optional, for step 6: `export GEMINI_API_KEY=...` **before** running `codewarden demo`, or run `ollama pull qwen2.5-coder:7b`.

Everything is local. `codewarden demo` resets its database each time, so you can rehearse freely.

## Script

| # | Show | Say |
|---|---|---|
| 1 | **Overview** | "CodeWarden reviews pull requests automatically. This dashboard is the history: what it reviewed, what it found, which issues repeat." Point at severity bars and "Most common issues". |
| 2 | **Open "Add checkout with coupons"** | "This is a realistic PR: a new `checkout.py` plus a lockfile. Each finding sits on the exact line, ranked by severity, with a confidence score." Scroll to the SQL injection, then the off-by-one. |
| 3 | **Auto-fix on the off-by-one** | "When the fix is one line, it shows the exact replacement, and on GitHub it posts as a one-click *suggestion* block." |
| 4 | **Open "Repository context sent to the model"** | "This is the RAG part. Before reviewing, it indexed the repo and retrieved related code: `db.py`, `orders.py`, the README conventions. A reviewer that only sees the diff cannot know the repo already has a safe `run_query` helper." |
| 5 | **Prompt-injection finding** | "Line 13 has a comment telling an AI reviewer to approve the PR. CodeWarden treats PR content as untrusted data and flags it. Secrets are also redacted before anything is sent to a model." |
| 6 | **New review -> Sample -> *Upload endpoint*** then switch **Reviewer** to Gemini/Ollama | "The offline baseline is regex rules. It caught `eval` and `verify=False` but missed the path traversal, even though the repo already has a `sanitize_filename` helper. It also missed that `cancel_order` in the checkout PR has no login check. Compare with a real model and repo context." (Only claim what you see on screen.) |
| 7 | **Generate tests** on `checkout.py` | "It also writes unit tests for the new functions. Offline you get skeletons; with a model you get real assertions." |
| 8 | **Evaluation** | "How do we know it's any good? Twelve seeded-bug diffs with known answers, plus a safe-looking trap. The regex baseline gets 86% precision but only 60% recall: it misses logic bugs. That is the number a real model has to beat." Run it with Gemini/Ollama to compare live. |
| 9 | **Ask the repo** | "Same retrieval layer powers Q&A: 'how do I check a user is logged in?' returns `require_login` with citations." |
| 10 | **GitHub** | Show `.github/workflows/codewarden.yml`: "To use it for real, add this workflow. Every PR gets inline comments, and repeats are suppressed on later pushes." |

## Map to the course rubric

| Rubric item | Where to point |
|---|---|
| Prompt engineering for code models (Phase 1) | `src/codewarden/prompts.py`: rubric, JSON schema, injection defence |
| Open code models (Phase 1) | `--provider ollama --model deepseek-coder:6.7b` (also codellama, starcoder2) |
| RAG pipeline, LangChain (Phase 2) | `src/codewarden/rag/`; `rag.chunker: langchain` uses LangChain's language-aware splitters; `as_langchain_retriever()` exposes the index to LangChain chains |
| Code Q&A bot (Phase 2) | "Ask the repo" page, `codewarden ask` |
| GitHub Actions CI/CD (Phase 2) | `action.yml`, `.github/workflows/` |
| AI test generation (Phase 2) | "Generate tests" button, `codewarden testgen`. A built-in generator, not CodiumAI/Codeium |
| Evaluation and ethics (Phase 3) | Evaluation page; README "Limitations" |

Not built: Sweep.dev, CodiumAI/Codeium and Sourcegraph integrations. If asked: they are external services, and this project reimplements the relevant capability (auto-fix suggestions, test generation, code search) rather than calling them.

## Likely questions

- **"Can it hallucinate?"** Yes. It verifies each finding points at a real changed line and filters by confidence, but cannot verify the claim is true. Comments are a first pass for a human.
- **"Is my code sent to Google?"** With `gemini`, yes, after secret redaction. Use `ollama` to keep everything local.
- **"Why is the offline reviewer in a project about AI?"** As a control. Without a baseline you cannot show the model adds value.
- **"What stops it spamming a PR?"** Severity and confidence thresholds, a comment cap, and a fingerprint of each flagged line so earlier findings are not repeated.

## Troubleshooting

- *Port in use*: `codewarden demo --port 9000`
- *"demo/ folder not found"*: run from the repository root.
- *Gemini shows "unavailable"*: the key must be exported before the server starts.
- *"quota exceeded" (HTTP 429)*: the key's free-tier limit is used up. It resets on Google's schedule, or use another key. A failed run is reported as an error and never saved as a result. Do your Gemini runs sparingly (a review is 1-3 calls, a full evaluation about 12) and rehearse the offline path first.
- *Blank page*: hard-refresh; check the terminal for tracebacks.
