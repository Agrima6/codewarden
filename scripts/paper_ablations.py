"""Retrieval ablations for the paper: vary top-k and compare retrieval methods on the context suite.

Usage: python scripts/paper_ablations.py   (needs a running Ollama with qwen2.5-coder:7b)
Writes docs/results/ablation_<name>.json. Each run: 7 context files x 3 repeats, retrieval-augmented system only.
"""
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from codewarden.config import Config  # noqa: E402
from codewarden.experiment import System, run_experiment  # noqa: E402

MODEL = "qwen2.5-coder:7b"
REPEATS = 3
RUNS = {  # name -> (backend, top_k, retrieval on?)
    "topk1": ("chroma", 1, True),
    "topk2": ("chroma", 2, True),
    "topk8": ("chroma", 8, True),
    "bm25_k4": ("bm25", 4, True),
    "topk4": ("chroma", 4, True),      # re-run of the main configuration on the current code (replication)
    "diffonly": ("chroma", 4, False),  # the same model without retrieval, context suite only
}

base = Config.load(str(ROOT / "demo/codewarden.yml"))  # chroma + langchain chunker, top_k 4 (the main experiment)
out_dir = ROOT / "docs/results"
only = set(sys.argv[1:])
for name, (backend, k, rag_on) in RUNS.items():
    if (only and name not in only) or (not only and name in ("topk4", "diffonly")):
        continue
    system = System("ollama-rag" if rag_on else "ollama-diff", f"Ollama ({MODEL})" + (" + RAG" if rag_on else ", diff only"),
                    "ollama", MODEL, rag_on)
    cfg = replace(base, rag=replace(base.rag, backend=backend, top_k=k))
    print(f"=== {name}: backend={backend} top_k={k} retrieval={rag_on}", flush=True)
    res = run_experiment(systems=[system], repeats=REPEATS, eval_dir=ROOT / "eval/cases", base_cfg=cfg,
                         progress=lambda d, t, label: print(f"[{d}/{t}] {label}", flush=True), project_root=ROOT,
                         only_suites=("context",))
    res["config"]["ablation"] = {"name": name, "backend": backend, "top_k": k, "retrieval": rag_on}
    (out_dir / f"ablation_{name}.json").write_text(json.dumps(res, indent=2))
    m = res["metrics"][f"{system.id}|context"]
    print(f"--- {name}: recall={m['recall']:.3f} precision={m['precision']} FP={m['false_positives']} "
          f"latency={m['avg_latency_ms']}ms", flush=True)
