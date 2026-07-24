"""Unit tests for qa-queue/scripts/build_dashboard_widget.py — verifies the
template-substitution layer. Pure-Python; the HTML widget itself runs in a
browser frame and isn't unit-testable here.

    pytest skills/qa-queue/tests/test_build_dashboard.py
"""
from pathlib import Path

import pytest

import build_dashboard_widget as B

SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = SKILL_ROOT / "templates" / "dashboard.html"


def _values(**overrides):
    base = {
        "OPTIMUS_LIST_LANE_TASKS_TOOL": "mcp__test__list_lane_tasks",
        "MEM_LIST_NOTES_TOOL":          "mcp__test__list_notes",
        "MEM_RUN_LOGS_COLLECTION_ID":   "abc-123",
        "OPTIMUS_PRODUCT":              "medtrics",
        "OPTIMUS_QA1_LANE":             "qa1",
        "COWORK_DASHBOARD_TITLE":       "Test Dashboard",
    }
    base.update(overrides)
    return base


# ---------- build() core ----------

def test_build_substitutes_every_placeholder():
    out = B.build(TEMPLATE.read_text(encoding="utf-8"), _values())
    # Every placeholder name should be gone from the result.
    for key in B.PLACEHOLDERS:
        assert "{{" + key + "}}" not in out, f"{key} not substituted"


def test_build_injects_values_into_output():
    out = B.build(TEMPLATE.read_text(encoding="utf-8"), _values(
        MEM_RUN_LOGS_COLLECTION_ID="3533-real-uuid",
        COWORK_DASHBOARD_TITLE="QA1 — Production",
        OPTIMUS_PRODUCT="medtrics-staging",
    ))
    assert '"3533-real-uuid"' in out
    assert "QA1 — Production" in out
    assert '"medtrics-staging"' in out


def test_build_raises_on_missing_value():
    vals = _values()
    del vals["MEM_RUN_LOGS_COLLECTION_ID"]
    with pytest.raises(ValueError, match="MEM_RUN_LOGS_COLLECTION_ID"):
        B.build(TEMPLATE.read_text(encoding="utf-8"), vals)


def test_build_raises_on_unknown_leftover():
    # Force a stray {{UNKNOWN}} in the input.
    tampered = TEMPLATE.read_text(encoding="utf-8") + "\n<!-- {{UNKNOWN_THING}} -->\n"
    with pytest.raises(ValueError, match="UNKNOWN_THING"):
        B.build(tampered, _values())


def test_build_is_idempotent():
    t = TEMPLATE.read_text(encoding="utf-8")
    a = B.build(t, _values())
    b = B.build(t, _values())
    assert a == b


# ---------- values_from_config() ----------

def test_values_from_config_uses_defaults_when_only_collection_id_present():
    vals = B.values_from_config({"mem": {"run_logs_collection_id": "uuid-1"}})
    assert vals["MEM_RUN_LOGS_COLLECTION_ID"] == "uuid-1"
    assert vals["OPTIMUS_PRODUCT"] == "medtrics"
    assert vals["OPTIMUS_QA1_LANE"] == "qa1"
    assert vals["OPTIMUS_LIST_LANE_TASKS_TOOL"].startswith("mcp__")
    assert vals["MEM_LIST_NOTES_TOOL"].startswith("mcp__")
    assert vals["COWORK_DASHBOARD_TITLE"] == B.DEFAULT_TITLE


def test_values_from_config_honors_overrides():
    vals = B.values_from_config({
        "mem": {"run_logs_collection_id": "uuid-2"},
        "optimus": {"product": "med-staging", "qa1_lane": "qa1-staging"},
        "cowork": {"dashboard_title": "Staging Dashboard"},
        "mcp": {
            "optimus_list_lane_tasks_tool": "mcp__alt__lane",
            "mem_list_notes_tool": "mcp__alt__notes",
        },
    })
    assert vals["OPTIMUS_PRODUCT"] == "med-staging"
    assert vals["OPTIMUS_QA1_LANE"] == "qa1-staging"
    assert vals["COWORK_DASHBOARD_TITLE"] == "Staging Dashboard"
    assert vals["OPTIMUS_LIST_LANE_TASKS_TOOL"] == "mcp__alt__lane"
    assert vals["MEM_LIST_NOTES_TOOL"] == "mcp__alt__notes"


def test_values_from_config_missing_collection_id_returns_none():
    # Caller is responsible for catching this before calling build().
    vals = B.values_from_config({})
    assert vals["MEM_RUN_LOGS_COLLECTION_ID"] is None


# ---------- GAP-2: CLI must refuse to render with a null collection UUID ----------

def test_cli_refuses_null_collection_id(tmp_path, capsys, monkeypatch):
    """The CLI must exit non-zero with an actionable error when the Mem
    collection UUID is missing — instead of silently rendering a widget that
    queries collection_id=null and shows zero rows (GAP-2)."""
    import json as _json
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(_json.dumps({
        "optimus": {"product": "medtrics", "qa1_lane": "qa1"},
        "mem": {"run_logs_collection_id": None},
    }))
    monkeypatch.setattr(
        "sys.argv",
        ["build_dashboard_widget.py", "--config", str(cfg_path)],
    )
    rc = B.main()
    captured = capsys.readouterr()
    assert rc == 1
    payload = _json.loads(captured.err.strip())
    assert payload["error"] == "mem_collection_missing"
    assert "/setup-medtrics-qa-automation" in payload["reason"]
