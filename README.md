# CodeWarden

An AI-powered pull request review assistant. It reads the diff of a PR, retrieves related code from the repository, asks an LLM to find bugs, security issues and risky changes, and posts severity-ranked inline comments on GitHub.

Built for CSE 4011 *Intelligent Developer Tools and AI DevOps Workflows*.

```
PR opened/updated -> GitHub Action -> fetch diff -> parse hunks & line numbers
      -> RAG: related code from the repo -> redact secrets -> LLM (JSON findings)
      -> validate lines, drop low confidence / duplicates, rank by severity
      -> one review with inline comments + summary on the PR
```

## Quick start (no API key needed)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q

# Review your current branch against main with the offline rule-based reviewer
codewarden review --base main --head HEAD --provider rules

# Score the reviewer on the seeded-bug cases in eval/cases/
codewarden eval --provider rules
```

## Use a real model

| Provider | Setup | Notes |
|---|---|---|
| `gemini` | `export GEMINI_API_KEY=...` | Default model `gemini-2.5-flash`. Plain REST, no SDK. |
| `ollama` | `ollama pull qwen2.5-coder:7b`, then `--provider ollama` | Local and private. Try `deepseek-coder`, `codellama`, `starcoder2` via `--model`. |
| `rules` | none | Deterministic regex baseline. Not an AI model; used for tests, demos and as an evaluation baseline. |

```bash
codewarden review --base main --provider gemini
codewarden review --staged --provider ollama --model deepseek-coder:6.7b
git diff main | codewarden review --diff-file - --format markdown
```

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

Add `GEMINI_API_KEY` under *Settings -> Secrets and variables -> Actions*. Commit a `.codewarden.yml` (see the one in this repo) to tune it.

Behaviour worth knowing:
- Findings already posted on earlier pushes are not repeated (a fingerprint of the flagged code is hidden in each comment).
- Pull requests from forks do not receive repository secrets, so they are skipped with a warning rather than failing.
- Draft PRs are skipped. Re-running the action on a comment trigger (`issue_comment` + `/codewarden review`) is supported by `codewarden action`, but wire it to a **pinned** copy of the action, never `uses: ./` after checking out PR code, or a commenter could execute their own code with your secrets.
- With `fail_on: critical` the check fails when a critical finding exists; the default is advisory only.

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
| `rag.enabled`, `rag.backend`, `rag.top_k` | `true`, `bm25`, `4` | Repository context |

Environment overrides: `CODEWARDEN_PROVIDER`, `CODEWARDEN_MODEL`, `CODEWARDEN_EXCLUDE`.

## How it works

| Module | Responsibility |
|---|---|
| `diff.py` | Unified-diff parser that tracks real new-file line numbers (hunk bodies are consumed by their header counts, and tolerate wrong counts). |
| `review.py` | Pipeline: skip filters, batching by size, retrieval, prompt, parse, anchor, filter, dedupe, rank. |
| `rag/` | Chunks the checkout into overlapping line windows. `bm25` retriever has no dependencies; `chroma` is an optional semantic backend. Chunks overlapping the changed lines are excluded so the model gets *other* code. |
| `prompts.py` | Review rubric and JSON schema. PR text, diff and retrieved code are labelled untrusted data to resist prompt injection. |
| `llm/` | `gemini`, `ollama`, `rules` behind one `complete(system, user)` interface, with retry/backoff on 429/5xx. |
| `github.py` | Reads the PR, posts one review. Uses `line` + `side: RIGHT` anchors, falls back to per-comment posting when GitHub rejects one anchor, and pushes un-anchorable findings into the summary. |
| `redact.py` | Removes AWS/GitHub/Google/Slack keys, private keys and `password = "..."` style values before any LLM call. |
| `evaluate.py` | Precision/recall over `eval/cases/*.diff` with expected locations. |

### Why not just use `gemini-ai-code-reviewer`?

[Jainharshit09/gemini-ai-code-reviewer](https://github.com/Jainharshit09/gemini-ai-code-reviewer) is a good minimal example of the idea (comment-triggered Action, Gemini, per-hunk prompts). CodeWarden was written from scratch (that repo has no license) and goes further:

| | Reference repo | CodeWarden |
|---|---|---|
| Context beyond the hunk | none | RAG over the repository |
| Output | line + comment | severity, category, confidence, suggested fix |
| Comment anchoring | hunk-relative number sent as GitHub `position` (wrong for later hunks) | real file line numbers via `line`/`side`, validated against the diff |
| Repeat pushes | re-comments everything | fingerprint dedupe |
| Secrets in code | sent to the model, and prompts logged to the Actions log | redacted first, prompts not logged |
| Models | Gemini only | Gemini, local Ollama models, offline baseline |
| Quality measurement | none | seeded-bug evaluation harness |
| Tests | none | 54 offline tests |

## Evaluation

`eval/cases/` holds seeded-bug diffs (SQL injection, hard-coded secret, off-by-one, swallowed exception, N+1 query, XSS) plus a clean file. Each has an `.expected.json` with the true location.

Baseline (`rules` provider): precision 100%, recall 83%. It deliberately misses `n_plus_one`, which needs reasoning rather than a regex. Run `codewarden eval --provider gemini` or `--provider ollama` to compare real models against this baseline. The set is small; grow it before drawing conclusions.

## Status

Verified: the diff parser, pipeline, filters, dedupe, redaction, retry logic, BM25 retrieval, CLI, Action flow and GitHub posting logic are covered by offline tests (HTTP mocked), and the CLI was run end to end on a real git repo with the `rules` provider.

Not yet verified against live services: the Gemini and Ollama calls, the `chroma` backend, posting to the real GitHub API, and the Docker image. Do a first run on a throwaway repository before relying on it.

## Roadmap (course phases)

1. **Phase 1:** done: diff parsing, prompt design, model comparison via Ollama/Gemini, CLI.
2. **Phase 2:** RAG and GitHub Actions are in place. To add: LangChain/LlamaIndex wrapper around the retriever, Sweep.dev auto-fix hand-off, generated-test suggestions (CodiumAI/Codeium), Sourcegraph for cross-repo search.
3. **Phase 3:** larger evaluation set, RAG on/off comparison, per-language prompts, ethics/limitations write-up.

## Limitations

LLMs hallucinate. CodeWarden checks that each finding points at a real line in the diff and filters by confidence, but cannot verify that the claim is true. Treat comments as a first pass for a human reviewer.
