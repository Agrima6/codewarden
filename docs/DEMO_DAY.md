# Demo day guide (mid-term evaluation, 20-minute slot)

Everything below is real. The dashboard states which models produced which numbers, and you should say so out loud too: examiners reward a team that knows exactly what it ran, and they probe exactly this ("which model? how many runs? what are the limits?").

**Suggested split of the 20 minutes:** 4 min problem and method, 9 min live demo, 7 min questions. Questions go to any member, so every member must be able to present every part. The "Know your system" section below is the minimum each person should be able to say from memory.

## The night before

```bash
cd ~/Downloads/codewarden && source .venv/bin/activate
pytest -q                                   # all green
ollama serve &                              # local model server (ignore "address in use" if already running)
ollama list                                 # qwen2.5-coder models present
export GEMINI_API_KEY='...'                 # never paste it on screen or into a file
codewarden demo                             # opens http://127.0.0.1:8765
```

1. **Experiment page -> Run** with *Regex baseline + Gemini + Ollama*, **3 runs**. Let it finish (several minutes). This gives you stored results with confidence intervals and run-to-run spread, so you are not dependent on live API quota in the room.
2. Connect the GitHub repository you will demo on (**Repositories** page) and open its pull-request list once, so it is cloned and indexed.
3. Run **one** review of a PR from that repo and keep it open in a tab as a fallback.
4. Close other apps and set the browser zoom to about 110%.

If the key's quota is exhausted, the Experiment page reports the failure and records nothing. Use the stored run from step 1.

## Map: evaluation criterion -> what to show

| Criterion | Where | What to say and show |
|---|---|---|
| **Research question and experimental alignment** | **Experiment** page, top | Read the question. Point to H1/H2/H3 and the "Design" box: one independent variable (the review system), fixed prompt/temperature/datasets/scoring. Say why the datasets match the question: the *context* suite contains bugs that are only bugs given the repository, so it can actually separate RAG from no-RAG. |
| **Quantitative evaluation** | **Datasets** card, then the metric tables | Two suites, counts of planted bugs and clean cases. Define precision, recall, F1, false-alarm rate (the grey note under the tables). Show the baseline, the diff-only model and the RAG model side by side. Mention 95% intervals and repeated runs. |
| **Results and interpretation** | **What the data shows** + charts + per-case matrix | Read the generated sentences, then add your own reading. Use the matrix to point at specific cases: which bugs each system found and missed. Compare RAG against diff-only on the context suite; say whether the intervals overlap. |
| **Technical implementation** | **New review** -> run on a sample, then the review page | Walk the pipeline: diff parser with real line numbers -> retrieval (open "Repository context sent to the model") -> redaction -> LLM -> validation against the diff -> ranked inline findings. Show the one-line fix suggestion and **Generate tests**. Show **Settings** for the retrieval configuration. |
| **Limitations and failure analysis** | **Failure analysis** and **Limitations** cards | Open two or three real misses and false alarms and say why they happened. Then read the threats to validity: small synthetic data, author-written baseline, non-determinism, scoring tolerance, retrieval confound. |
| **Methodology and reproducibility** | **Methodology and reproducibility** card | Point at prompt hash, dataset hash, git commit, models that answered, temperature, repetitions. Click **Download JSON/CSV**. Show the one-line command that reproduces the run from a terminal. |
| **Individual understanding** | Q&A | Anyone can be asked anything. See below. |

## Live demo script (9 minutes)

1. **(1 min) Problem.** Code review is a bottleneck; a reviewer sees only the diff but bugs often depend on the rest of the repository. *Question: does retrieved repository context help an LLM reviewer?*
2. **(2 min) Upload a GitHub repo.** **Repositories** -> paste the repo URL -> **Connect**. Say: shallow clone into a private cache, indexed for retrieval, nothing from the repo is executed. Click **Pull requests**, pick one, choose the reviewer, **Review**.
3. **(2 min) Review page.** Findings sit on the exact lines with severity, confidence and a suggested fix. Open **Repository context sent to the model** to show the retrieved files. Click **Generate tests** on one file.
4. **(1 min) Safety.** Secrets are redacted before anything is sent to a model; PR text is treated as untrusted data (show the prompt-injection finding on the *Add checkout with coupons* sample).
5. **(3 min) Experiment page.** Show the stored results: baseline vs diff-only vs RAG, the intervals, the matrix, two failures, the reproducibility card. State the conclusion *the data supports*, including where it does not.

## Know your system (every member, from memory)

- **Pipeline:** parse the unified diff -> for each batch of hunks, retrieve related code chunks from the repository -> redact secrets -> prompt the model for JSON findings -> parse and validate (the cited line must be a changed line, otherwise it is moved out of the inline comments) -> filter by confidence and severity, deduplicate against earlier reviews -> rank and post.
- **Retrieval:** repository files are split into chunks (LangChain's language-aware splitter) and embedded into ChromaDB; the query is the changed code; chunks overlapping the changed lines are excluded so the model receives *other* code. BM25 (keyword ranking) is the dependency-free alternative.
- **Why a baseline:** without a control you cannot say the model adds anything. The baseline is regex rules.
- **Metrics:** a finding is a true positive if it is in the right file within 2 lines of the planted bug. Precision = TP findings / all findings. Recall = planted bugs found / planted bugs. F1 = harmonic mean. False-alarm rate = clean cases where anything was reported.
- **Why intervals and repeats:** with about 10 bugs per suite one extra hit moves recall by 10 points; the Wilson interval shows that uncertainty. LLM output varies between runs, so repeated runs show the spread.
- **Why the context suite exists:** the general suite cannot distinguish RAG from no-RAG, because its bugs are visible in the diff. The context suite uses bugs that depend on helper signatures and conventions defined elsewhere in the repository.
- **Models used:** Google Gemini (hosted) and a local Ollama model (Qwen2.5-Coder). The exact model names that answered are stored with each run.
- **Where the code is:** `src/codewarden/review.py` (pipeline), `rag/` (retrieval), `experiment.py` (the experiment), `eval/` (datasets), `web/` (dashboard).

## Questions you should expect, and honest answers

- **"Is the improvement from RAG real?"** Say what the intervals show. If they overlap, say the sample is too small to establish it and that you would need more cases and repeated runs. Do not claim more than the data supports.
- **"Why is the small local model so weak?"** A 1.5-7B parameter model has little capacity for instruction following and structured JSON output; the experiment measures exactly this trade-off (H3): data stays local and latency is low, accuracy is lower.
- **"Did you tune the baseline or the prompt on the test cases?"** Be candid: the datasets and baseline were written by the team (listed under limitations); the prompt was designed before the experiment runs and is versioned by hash.
- **"Could the model have memorised these cases?"** The cases are original and small, but cannot be ruled out entirely for common bug types; this is why the context suite uses repository-specific conventions.
- **"What would you do next?"** More and real-world cases (for example bugs from public pull requests), a larger local model, a human-reviewer comparison, and measuring review comments that developers actually accept.
- **"How do you stop prompt injection / data leakage?"** Secrets are redacted before sending; PR text and retrieved code are labelled as untrusted in the prompt; a regex rule flags attempts to instruct the reviewer; with a local model nothing leaves the machine.

## If something goes wrong

| Problem | Do this |
|---|---|
| Gemini reports quota exceeded / busy | The app retries and falls back to another Gemini model. If it still fails, say so and show the stored run. A failed run is never recorded as a result. |
| Ollama not responding | `ollama serve` in a terminal; check **Settings** shows it available. |
| Repo clone fails | The repo may be private, misspelled or over 400 MB. Use another public repo or one connected earlier. |
| Page will not load | `codewarden demo` must be running in a terminal; reload `http://127.0.0.1:8765`. |
| Asked something you do not know | Say what the data shows and what you would test next. |
