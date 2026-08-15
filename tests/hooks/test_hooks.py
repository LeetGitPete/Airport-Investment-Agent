import importlib.util
import json
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[2] / ".claude" / "hooks"


def load(name):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_guard_secrets_blocks_env_in_commit():
    g = load("guard_secrets")
    assert g.blocked_files(["src/a.py", ".env"]) == [".env"]
    assert g.blocked_files(["config/keys.yaml", "notes/secret_stuff.md"]) == ["config/keys.yaml", "notes/secret_stuff.md"]
    assert g.blocked_files([".env.example", "src/ok.py"]) == []
    assert g.blocked_files(["api_secret_monkey.txt"]) == ["api_secret_monkey.txt"]
    assert g.blocked_files([".claude/keybindings.json"]) == []
    assert g.is_git_write("git commit -m x") and g.is_git_write("git push origin main")
    assert not g.is_git_write("git status")


def test_guard_frozen_blocks_contract_edits_when_marker_present(tmp_path, monkeypatch):
    g = load("guard_frozen")
    root = tmp_path
    (root / ".contracts-frozen").write_text("frozen")
    monkeypatch.delenv("CONTRACTS_UNFROZEN", raising=False)
    assert g.should_block(root, str(root / "src/airport_agent/contracts/models.py"))
    assert g.should_block(root, str(root / "config/metrics.yaml"))
    assert not g.should_block(root, str(root / "src/airport_agent/data/x.py"))
    monkeypatch.setenv("CONTRACTS_UNFROZEN", "1")
    assert not g.should_block(root, str(root / "src/airport_agent/contracts/models.py"))


def test_guard_frozen_allows_when_no_marker(tmp_path, monkeypatch):
    g = load("guard_frozen")
    monkeypatch.delenv("CONTRACTS_UNFROZEN", raising=False)
    assert not g.should_block(tmp_path, str(tmp_path / "src/airport_agent/contracts/models.py"))


def test_lint_on_edit_selects_only_src_python():
    m = load("lint_on_edit")
    assert m.wants_lint("src/airport_agent/data/x.py")
    assert not m.wants_lint("docs/design/00-overview.md")
    assert m.wants_lint("tests/test_x.py")


def test_log_agent_stop_appends_jsonl(tmp_path):
    m = load("log_agent_stop")
    out = tmp_path / "log.jsonl"
    m.append_event(out, {"hook_event_name": "SubagentStop", "agent_type": "data-engineer",
                         "last_assistant_message": "changed: x\ntested: y"}, now="2026-08-15T10:00:00")
    m.append_event(out, {"hook_event_name": "Stop"}, now="2026-08-15T10:05:00")
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert lines[0]["agent"] == "data-engineer" and lines[0]["ts"] == "2026-08-15T10:00:00"
    assert lines[0]["summary"].startswith("changed: x")
    assert lines[0]["event"] == "SubagentStop"
    assert lines[1]["agent"] == "main"
