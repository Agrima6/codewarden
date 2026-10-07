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
- **Why intervals and repeats:** with about 10 bugs per suite one extra hit moves recall by 10 points; the Wilson interval shows that uncertainty. LLM output varies between runs, so repeated runs show the spread. The intervals count each distinct bug once: running the same case three times does not give three independent observations, so pooling repeats into the sample size would make the intervals falsely tight.
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

## Page by page: what to show and how

Open `http://127.0.0.1:8765` and hard-refresh (Cmd+Shift+R) after any restart. Ollama runs one request at a time, so do not start a model review or a Q&A while an experiment is running.

| Page | What it is | How to demonstrate |
|---|---|---|
| **Overview** | History and statistics of every review | Show the counts, severity bars, "Most common issues" and the recent-reviews table. Click a review to open it. Message: "this is the audit trail of what the tool found across pull requests." |
| **Repositories** | Connect a public GitHub repo, browse its PRs | Paste your repo URL -> **Connect** (it clones and indexes it). Click **Pull requests**, pick one, choose the reviewer, click **Review**. Message: "the model gets real surrounding code, not just the diff." Use **Remove** to show you can disconnect. |
| **New review** | Review a pasted diff, a PR URL or a bundled sample | **Sample** tab: pick *Add checkout with coupons*, reviewer = offline baseline for an instant result, then repeat with a model. **GitHub PR** tab: paste any public PR URL. **Paste diff**: paste `git diff` output. Toggle "Use repository context" off and on to show the effect. |
| **Review detail** (after any review) | The result | Findings sit on exact lines with severity, category, confidence and fix. Open **Repository context sent to the model** (the retrieved files). Click **Generate tests**. Use the severity chips to filter. **Copy summary** exports text. If a real PR was reviewed and a GitHub token is set, **Post to GitHub** publishes inline comments. |
| **Experiment** | The research part, written as a plain-language story in 5 numbered parts | Scroll it top to bottom. **1** the question and our three guesses. **2** how we tested (practice code with hidden bugs, three helpers, two tests). **3** the scoreboard: green/blue/grey bars show how many hidden bugs each helper found, with false alarms and a "likely range". Read the "In simple words" box aloud. **4** what to be careful about. **5** open **Full numbers** for the technical table (precision, recall, F1, intervals, speed), charts, bug-by-bug grid, failures and reproducibility, and **Run the test yourself** for a live run. The page opens on the most complete stored run. |
| **Guardrails** | Controls around the model, with a live tester | See the 2-minute script below. Message: "safe use of an LLM is designed in, not hoped for." |
| **Ask the repo** | Retrieval-augmented Q&A | Choose your repo, ask "how do I check a user is logged in?" or "where are files saved?". The answer cites files; open a source to show the retrieved code. With the offline reviewer you see only the retrieved code. |
| **Settings** | Configuration and status | Show which model backends are available, the retrieval settings (Chroma + LangChain chunking, top 4), whether a GitHub token / webhook is set. Message: "everything is configurable and nothing sensitive is displayed." |

### Guardrails: 2-minute script

Open **Guardrails**. Say: "A model reads untrusted code and writes text that gets published, so we put controls on all four sides of it."

1. Point at the four boxes: **Input -> Model -> Output -> Action**. Each rule below shows what it does, whether it is on, how many times it has triggered across stored reviews, and the exact function that implements it.
2. In **Try it**, tab *Before the model*, example **All three together**. Show: the password becomes `[REDACTED_SECRET]`, the email becomes `[EMAIL]`, the injected instruction is neutralised, and the event log says what happened. "That is what the model would actually receive."
3. Tab *Model output*, example **Ping and tracking image**. Show the @mention neutralised and the image and link removed. "A model cannot ping people or leak data through a markdown image."
4. Tab *Suggested fix*, example **Turns TLS verification off**. Show **Blocked**. "A one-click fix that makes code less secure is never offered."
5. Tab *File path*, `.env` -> blocked; `.env.example` -> allowed. "Sensitive files are never sent."
6. Open any review (for example *Add checkout with coupons*): the **Guardrails** panel at the top lists what triggered on that review, where, and which checks ran.
7. Close with the action layer: comment-only (it can never approve or merge), the server refuses to post without confirmation, and posting is rate limited.

Be candid about limits (the page says it too): these are pattern-based, so novel secrets or phrasing can slip through, and a model can still be wrong. That is why a human makes the final decision.

### Sample dropdowns (for a smooth demo)

| Page | Dropdown | What it does |
|---|---|---|
| New review -> Paste diff | *Load an example diff* | Fills the box with a sample or seeded-bug diff |
| New review -> GitHub PR | *Connected repository* then *Pull request* | Lists the repo's real PRs and fills the URL |
| New review -> Sample | *Bundled sample* | Runs a prepared pull request |
| Repositories | *Example repositories* | Fills the URL box (edit the list in `demo/examples.json`) |
| Ask the repo | *Try a sample question* | Fills in and runs a question (edit in `demo/examples.json`) |
| Experiment | *Preset* | Sets reviewers and repetitions for common runs |
| Guardrails | *Example* | Loads a ready-made input for each tab |

### Optional: post real review comments on your GitHub PRs

To show comments appearing on GitHub itself, start the server with a token from your own login (do this before presenting, not during an experiment):

```bash
export GITHUB_TOKEN="$(gh auth token)"
codewarden demo
```

Then review one of your PRs from **Repositories** and click **Post to GitHub** on the review page. It asks for confirmation first.

### Suggested model choice on each page
- Quick, always-available: **Rule-based baseline** (state clearly that it is the control, not an AI model).
- Real AI, local, no limits: **Ollama (local)** with the default model.
- Real AI, hosted: **Google Gemini**; subject to the key's quota, so keep a stored run ready.
