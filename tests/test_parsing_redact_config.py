import pytest

from codewarden.config import Config
from codewarden.parsing import parse_findings
from codewarden.redact import redact


def test_parse_clean_json():
    out = parse_findings('{"findings":[{"line":3,"severity":"HIGH","category":"security","title":"t","explanation":"e","confidence":0.9}]}')
    assert out[0]["line"] == 3 and out[0]["severity"] == "high" and out[0]["confidence"] == 0.9


def test_parse_fenced_and_chatty_output():
    raw = 'Sure! ```json\n{"findings":[{"line":"5","title":"x","explanation":"y"}]}\n```'
    out = parse_findings(raw)
    assert out[0]["line"] == 5 and out[0]["category"] == "bug"


def test_parse_legacy_shape_and_aliases():
    out = parse_findings('{"reviews":[{"lineNumber":2,"reviewComment":"bad","severity":"error"}]}')
    assert out[0]["severity"] == "high" and out[0]["explanation"] == "bad"


@pytest.mark.parametrize("raw", ["", "not json", "[]", '{"findings":"nope"}', '{"findings":[{"line":"x"}]}', '{"findings":[1,2]}'])
def test_parse_garbage_never_raises(raw):
    assert parse_findings(raw) == []


def test_confidence_clamped():
    out = parse_findings('{"findings":[{"line":1,"title":"t","confidence":7}]}')
    assert out[0]["confidence"] == 1.0


def test_redact_secrets():
    text = 'key = "AKIAABCDEFGHIJKLMNOP"\npassword = "hunter2hunter2"\nok = "hello"\nx = sk-abcdefghijklmnopqrstuvwx'
    out = redact(text)
    assert "AKIAABCDEFGHIJKLMNOP" not in out and "hunter2hunter2" not in out and "sk-abcdefghij" not in out
    assert 'ok = "hello"' in out


def test_config_defaults_and_validation(tmp_path):
    assert Config.load(tmp_path / "missing.yml" if False else None).provider == "gemini"
    bad = tmp_path / "bad.yml"
    bad.write_text("min_severity: urgent\n")
    with pytest.raises(ValueError):
        Config.load(bad)
    unknown = tmp_path / "u.yml"
    unknown.write_text("colour: red\n")
    with pytest.raises(ValueError):
        Config.load(unknown)


def test_config_file_overrides(tmp_path):
    f = tmp_path / ".codewarden.yml"
    f.write_text("provider: ollama\nmax_comments: 5\nrag:\n  top_k: 2\n  backend: bm25\n")
    c = Config.load(f)
    assert (c.provider, c.max_comments, c.rag.top_k) == ("ollama", 5, 2)
    assert c.resolved_model() == "qwen2.5-coder:7b"


def test_yaml_exclude_extends_defaults(tmp_path):
    f = tmp_path / "c.yml"
    f.write_text('exclude:\n  - "*.generated.*"\n')
    c = Config.load(f)
    assert "*.generated.*" in c.exclude and "package-lock.json" in c.exclude
