# CodeWarden

An AI-powered pull request review assistant with a web dashboard. It reads the diff of a PR, retrieves related code from the repository, asks an LLM to find bugs, security issues and risky changes, and posts severity-ranked inline comments on GitHub.

Built for CSE 4011 *Intelligent Developer Tools and AI DevOps Workflows*.

| Overview | Review detail | Evaluation |
|---|---|---|
| ![Overview](docs/screenshots/overview.jpg) | ![Review](docs/screenshots/review-detail.jpg) | ![Evaluation](docs/screenshots/evaluation.jpg) |

```
PR opened/updated -> GitHub Action / webhook / dashboard -> fetch diff -> parse hunks & line numbers
      -> RAG: related code from the repo -> redact secrets -> LLM (JSON findings)
      -> validate lines, drop low confidence / duplicates, rank by severity
      -> inline comments + summary on the PR (with one-click fix suggestions)
```

## Try it in 2 minutes (no API key, no internet)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web,langchain,dev]"
pytest -q                 # 143 tests
codewarden demo           # dashboard at http://127.0.0.1:8765 with demo PRs pre-reviewed
```

A step-by-step presentation script is in [docs/DEMO.md](docs/DEMO.md).

## What is in the box

| Feature | Where |
|---|---|
| Web dashboard: history, stats, annotated diffs, repo Q&A | `codewarden serve` / `codewarden demo` |
| **Experiment**: baseline vs LLM vs LLM+RAG on labelled data, with confidence intervals, per-case outcomes, failure analysis and a reproducibility record | dashboard **Experiment**, `codewarden experiment` |
| **Connect a public GitHub repository**: shallow clone, index for RAG, browse and review its pull requests | dashboard **Repositories** |
| Review a local diff or branch | `codewarden review --base main` |
| Review a GitHub PR by URL (public repos work without a token) | dashboard **New review -> GitHub PR** |
| GitHub Action + signature-verified webhook receiver | `action.yml`, `/webhook/github` |
| RAG over the repository (BM25 default, Chroma optional, LangChain chunking) | `src/codewarden/rag/` |
| Ask-the-repo Q&A with citations | dashboard **Ask the repo**, `codewarden ask` |
| One-line auto-fix suggestions (posted as GitHub `suggestion` blocks) | `replacement` field in findings |
| Unit-test generation for changed code | dashboard **Generate tests**, `codewarden testgen` |
| Quick precision/recall check on the seeded-bug cases | `codewarden eval` |
| Guardrails on input, model, output and action; dedupe across pushes | `guardrails.py`, `prompts.py`, `report.py` |

## Models

| Provider | Setup | Notes |
|---|---|---|
| `gemini` | `export GEMINI_API_KEY=...` | Default `gemini-flash-latest`. Plain REST, no SDK. |
| `ollama` | `ollama pull qwen2.5-coder:7b`, then `--provider ollama` | Local and private. Try `deepseek-coder`, `codellama`, `starcoder2` via `--model`. |
| `rules` | none | Deterministic regex baseline. **Not an AI model.** For tests, demos and as an evaluation control. |

```bash
codewarden review --base main --provider gemini
codewarden review --staged --provider ollama --model deepseek-coder:6.7b
git diff main | codewarden review --diff-file - --format markdown
codewarden ask "where do we validate uploads?" --repo-root . --provider gemini
codewarden testgen --diff-file change.diff --file app/checkout.py --provider gemini
```

## Dashboard

```bash
codewarden serve --repo-root /path/to/your/repo      # indexes that repo for RAG and Q&A
```

- Binds to `127.0.0.1`. To listen elsewhere you must set `CODEWARDEN_DASHBOARD_TOKEN`; the API then requires `Authorization: Bearer <token>`.
- Reviews are stored in SQLite (`.codewarden/dashboard.db`), including the diff text. Treat the file like your source code.
- Reviewing a PR URL uses RAG only when the server's `--repo-root` is a checkout of that same GitHub repository; otherwise unrelated code would be misleading context, so RAG is switched off and the review says so.
- **Post to GitHub** (button) needs `GITHUB_TOKEN` on the server and asks for confirmation first.
- Webhook: set `GITHUB_WEBHOOK_SECRET` and point a repository webhook (event: pull requests) at `/webhook/github`. Reviews appear in the dashboard; set `CODEWARDEN_WEBHOOK_POST=1` to also post them to the PR.
- `/api/docs` serves the OpenAPI description.

## GitHub Action

Add `.github/workflows/codewarden.yml` to the repository you want reviewed:

```yaml
name: CodeWarden review
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
permissions:
  contents: read
  pull-requests: write
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: <your-github-user>/codewarden@main   # pin a tag or SHA in real use
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          gemini_api_key: ${{ secrets.GEMINI_API_KEY }}
```

Add `GEMINI_API_KEY` under *Settings -> Secrets and variables -> Actions*. Commit a `.codewarden.yml` to tune it.

- Findings already posted on earlier pushes are not repeated (a fingerprint of the flagged code is hidden in each comment).
- Pull requests from forks do not receive secrets, so they are skipped with a warning rather than failing.
- Draft PRs are skipped. A comment trigger (`issue_comment` + `/codewarden review`) is supported by `codewarden action`, but wire it to a **pinned** copy of the action, never `uses: ./` after checking out PR code, or a commenter could run their own code with your secrets.
- With `fail_on: critical` the check fails when a critical finding exists; the default is advisory.

## Configuration

`.codewarden.yml` (all optional):

| Key | Default | Meaning |
|---|---|---|
| `provider`, `model` | `gemini`, provider default | Which LLM |
| `min_severity` | `low` | Hide findings below this |
| `min_confidence` | `0.5` | Hide findings the model is unsure of |
| `max_comments` | `25` | Cap per run, most severe first |
| `fail_on` | `none` | Fail CI at this severity or above |
| `exclude` | built-in list | Extra globs, added to lockfiles/images/`dist/`/`node_modules/` |
| `redact_secrets` | `true` | Strip keys/tokens/passwords before sending code to the model |
| `rag.enabled`, `rag.top_k` | `true`, `4` | Repository context |
| `rag.backend` | `bm25` | `bm25` (no dependencies) or `chroma` (`pip install 'codewarden[chroma]'`) |
| `rag.chunker` | `lines` | `lines` (fixed windows) or `langchain` (language-aware splitting) |

Environment overrides: `CODEWARDEN_PROVIDER`, `CODEWARDEN_MODEL`, `CODEWARDEN_EXCLUDE`.

## How it works

| Module | Responsibility |
|---|---|
| `diff.py` | Unified-diff parser that tracks real new-file line numbers and survives wrong hunk counts. |
| `review.py` | Pipeline: skip filters, batching, retrieval, prompt, parse, anchor, filter, dedupe, rank. |
| `rag/` | Chunks the checkout; BM25 or Chroma retrieval; LangChain splitters and a `BaseRetriever` adapter. Chunks overlapping the changed lines are excluded so the model gets *other* code. |
| `prompts.py` | Review rubric and JSON schema. PR text, diff and retrieved code are labelled untrusted data. |
| `llm/` | `gemini`, `ollama`, `rules` behind one `complete(system, user)` interface, with retry/backoff on 429/5xx. |
| `github.py` | Reads PRs, posts one review. Uses `line` + `side` anchors, falls back to per-comment posting if GitHub rejects one anchor, and moves un-anchorable findings into the summary. |
| `services.py`, `server.py`, `store.py`, `web/` | Dashboard: engine, FastAPI app, SQLite history, dependency-free UI (no build step, no CDN). |
| `testgen.py`, `qa.py` | Test generation and retrieval-augmented Q&A. |
| `evaluate.py` | Precision/recall over `eval/cases/`. |

### Why not just use `gemini-ai-code-reviewer`?

[Jainharshit09/gemini-ai-code-reviewer](https://github.com/Jainharshit09/gemini-ai-code-reviewer) is a good minimal example of the idea (comment-triggered Action, Gemini, per-hunk prompts). CodeWarden was written from scratch (that repo has no license) and goes further:

| | Reference repo | CodeWarden |
|---|---|---|
| Context beyond the hunk | none | RAG over the repository |
| Output | line + comment | severity, category, confidence, fix suggestion, one-click replacement |
| Comment anchoring | hunk-relative number sent as GitHub `position` (wrong for later hunks) | real file line numbers via `line`/`side`, validated against the diff |
| Repeat pushes | re-comments everything | fingerprint dedupe |
| Secrets in code | sent to the model; prompts printed to the Actions log | redacted first, prompts not logged |
| Models | Gemini only | Gemini, local Ollama models, offline baseline |
| Visibility | Actions log | dashboard with history, stats and annotated diffs |
| Quality measurement | none | seeded-bug evaluation harness |
| Tests | none | 143 offline tests |

## Guardrails

Controls on all four sides of the model, each visible in the dashboard (**Guardrails** page, plus a per-review panel):

| Layer | Rules |
|---|---|
| **Input** | sensitive files (`.env`, keys, tfstate...) never sent; secret redaction; PII masking (email, phone, Luhn-checked cards, Aadhaar-style IDs); prompt-injection detection (flagged in changed lines and turned into a finding, neutralised in PR text and retrieved code); "untrusted data" system prompt |
| **Model** | output schema validation; findings must be grounded in a changed line; confidence/severity thresholds; comment cap and cross-push dedupe |
| **Output** | @mention, link, image and HTML stripping; length limits; secret scrub on model text; unsafe one-click fixes blocked (shell pipes, `eval`, TLS off, `chmod 777`, hard-coded credentials) |
| **Action** | comment-only reviews (never approve or merge); posting needs server-side confirmation; posting rate limit |

Every trigger is stored as an event with the review it belongs to. `POST /api/guardrails/test` runs text through the real functions, which powers the dashboard's live tester. Switches live in `.codewarden.yml` (`redact_secrets`, `mask_pii`, `detect_injection`, `sanitize_output`, `post_limit_per_hour`). Implementation: `src/codewarden/guardrails.py`, wired in `review.py`, `filters.py`, `services.py` and `github.py`. Detection is pattern-based, so it reduces risk without eliminating it.

## Experiment

**Research question:** does giving an LLM reviewer retrieved repository context improve its ability to find bugs in pull requests, compared with reviewing the diff alone and with a pattern-matching baseline?

| | |
|---|---|
| Systems | regex baseline; each model *diff-only*; the same model *+ RAG* (ablation) |
| Datasets | **general** (`eval/cases`): 12 diffs, 10 planted bugs visible in the diff, 2 clean. **context** (`eval/context_cases`): 7 diffs against `demo/shop`, 6 planted bugs that are only bugs given the repository's helpers and conventions, 1 clean |
| Metrics | precision, recall, F1 (95% Wilson intervals), clean-case false-alarm rate, latency, tokens, per-category recall; run-to-run spread over repeated runs |
| Scoring | a finding is a true positive if it is in the same file within 2 lines of a planted bug |
| Records | prompt hash, dataset hash, git commit, models that actually answered, temperature, retrieval settings, exact reproduction command |

```bash
codewarden experiment --providers rules,gemini,ollama --repeats 3 --out results.json
```

or use the dashboard **Experiment** page, which also shows the per-case outcome matrix, a failure analysis and a limitations section. A failed model call aborts the run and nothing is recorded, so a partial or empty result can never be mistaken for a measurement.

The datasets are small and were written by the same team as the baseline, so treat the numbers as evidence for this setup, not a benchmark. The dashboard states the threats to validity next to the results.

## Status

**Verified** (143 offline tests with HTTP mocked, run on Python 3.14): diff parser, pipeline, filters, dedupe, redaction, retry logic, BM25 retrieval, LangChain chunker and retriever adapter, request/response shapes for Gemini and Ollama, CLI, Action flow, GitHub posting logic, the dashboard API (auth, validation, webhook signatures, storage), and the web UI in a real browser (desktop, mobile, dark mode) using the offline provider.

**Run for real on this machine:** Gemini (live API), Ollama with Qwen2.5-Coder, ChromaDB with LangChain chunking, and cloning/indexing public GitHub repositories. **Not verified:** posting reviews to the real GitHub API, the Docker image (no Docker daemon was running), Python 3.10/3.12 (CI is configured for them). Do a first run on a throwaway repository before relying on it.

## Roadmap (course phases)

1. **Phase 1:** done: diff parsing, prompt design, model comparison via Ollama/Gemini, CLI.
2. **Phase 2:** done: RAG with LangChain chunking, Q&A, GitHub Actions, test generation, auto-fix suggestions. Not integrated: Sweep.dev, CodiumAI/Codeium, Sourcegraph (external services; their capabilities are reimplemented here).
3. **Phase 3:** the experiment, RAG on/off ablation and failure analysis are implemented; remaining work is a larger and more realistic case set, a larger local model, and a human-reviewer comparison.

## Limitations

LLMs hallucinate. CodeWarden checks that each finding points at a real line in the diff and filters by confidence, but cannot verify that the claim is true. Treat comments as a first pass for a human reviewer. Code sent to a hosted model leaves your machine (after secret redaction); use `ollama` to keep it local.
