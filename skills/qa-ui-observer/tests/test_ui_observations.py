"""Unit tests for qa-ui-observer/scripts/check_observations.py.

Covers every catalog kind (positive + negative) plus stable ordering.
Pure-Python, no network, no browser.

    pytest tests/test_ui_observations.py
"""
import check_observations as C


def _step(n=1, priority="P1"):
    return {"n": n, "step_id": f"step-{n}", "priority": priority}


# ---------- console_warning ----------

def test_console_warning_emitted_for_warn_level():
    obs = C.observe(_step(), {"console": [{"level": "warn", "text": "Hey heads up"}]})
    assert len(obs) == 1
    assert obs[0]["kind"] == "console_warning"
    assert obs[0]["severity"] == "info"
    assert "Hey heads up" in obs[0]["evidence"]


def test_console_error_is_not_a_warning():
    # Errors are already covered by the console_clean assertion.
    obs = C.observe(_step(), {"console": [{"level": "error", "text": "boom"}]})
    assert obs == []


def test_console_empty_text_is_skipped():
    obs = C.observe(_step(), {"console": [{"level": "warn", "text": "   "}]})
    assert obs == []


# ---------- deprecated_api_warning ----------

def test_deprecated_api_warning_overrides_console_warning():
    obs = C.observe(_step(), {"console": [
        {"level": "warn", "text": "Deprecated: moment.js .add() since version 2.5"}
    ]})
    assert len(obs) == 1
    assert obs[0]["kind"] == "deprecated_api_warning"


def test_will_be_removed_pattern_matches():
    obs = C.observe(_step(), {"console": [
        {"level": "warn", "text": "WARNING: this API will be removed in v3."}
    ]})
    assert obs[0]["kind"] == "deprecated_api_warning"


# ---------- asset_load_error ----------

def test_asset_load_error_for_4xx_static_asset():
    obs = C.observe(_step(), {"network": [
        {"method": "GET", "url": "/static/icons/calendar.svg", "status": 404}
    ]})
    assert len(obs) == 1
    assert obs[0]["kind"] == "asset_load_error"
    assert obs[0]["severity"] == "warn"
    assert "404" in obs[0]["evidence"]


def test_asset_load_skipped_for_non_static_url():
    obs = C.observe(_step(), {"network": [
        {"method": "POST", "url": "/api/v2/schedule", "status": 500}
    ]})
    assert obs == []


def test_asset_load_skipped_when_status_ok():
    obs = C.observe(_step(), {"network": [
        {"method": "GET", "url": "/static/app.js", "status": 200}
    ]})
    assert obs == []


def test_asset_load_with_query_string_still_matches():
    obs = C.observe(_step(), {"network": [
        {"method": "GET", "url": "/static/app.js?v=abc123", "status": 502}
    ]})
    assert len(obs) == 1
    assert obs[0]["kind"] == "asset_load_error"


# ---------- broken_image ----------

def test_broken_image_when_natural_width_zero():
    obs = C.observe(_step(), {"elements": [
        {"selector": "img.x", "tag": "img", "exists": True, "natural_width": 0}
    ]})
    assert len(obs) == 1
    assert obs[0]["kind"] == "broken_image"


def test_loaded_image_emits_nothing():
    obs = C.observe(_step(), {"elements": [
        {"selector": "img.ok", "tag": "img", "exists": True, "natural_width": 800, "alt": "Logo"}
    ]})
    assert obs == []


def test_image_check_skips_non_img_tags():
    obs = C.observe(_step(), {"elements": [
        {"selector": ".banner", "tag": "div", "exists": True, "natural_width": 0}
    ]})
    assert obs == []


# ---------- missing_alt_text ----------

def test_missing_alt_text_on_p0_only():
    payload = {"elements": [
        {"selector": "img.x", "tag": "img", "exists": True, "natural_width": 800, "alt": ""}
    ]}
    p0_obs = C.observe(_step(priority="P0"), payload)
    p1_obs = C.observe(_step(priority="P1"), payload)
    p0_kinds = [o["kind"] for o in p0_obs]
    p1_kinds = [o["kind"] for o in p1_obs]
    assert "missing_alt_text" in p0_kinds
    assert "missing_alt_text" not in p1_kinds


def test_present_alt_passes():
    obs = C.observe(_step(priority="P0"), {"elements": [
        {"selector": "img.x", "tag": "img", "exists": True, "natural_width": 800, "alt": "Calendar"}
    ]})
    assert obs == []


# ---------- layout_overflow ----------

def test_horizontal_overflow_emits_layout_observation():
    obs = C.observe(_step(), {"elements": [
        {"selector": ".tbl", "tag": "table", "exists": True,
         "scroll_width": 1200, "client_width": 800,
         "is_scrollable_declared": False}
    ]})
    assert len(obs) == 1
    assert obs[0]["kind"] == "layout_overflow"


def test_overflow_ignored_when_element_declared_scrollable():
    obs = C.observe(_step(), {"elements": [
        {"selector": ".scroll", "tag": "div", "exists": True,
         "scroll_width": 1200, "client_width": 800,
         "is_scrollable_declared": True}
    ]})
    assert obs == []


def test_overflow_tolerates_one_pixel():
    # scrollWidth - clientWidth == 1 is within sub-pixel rounding tolerance.
    obs = C.observe(_step(), {"elements": [
        {"selector": ".x", "tag": "div", "exists": True,
         "scroll_width": 801, "client_width": 800,
         "is_scrollable_declared": False}
    ]})
    assert obs == []


# ---------- ordering ----------

def test_observation_order_is_console_then_network_then_image_then_overflow():
    obs = C.observe(_step(priority="P0"), {
        "console": [{"level": "warn", "text": "deprecated thing since version 1"}],
        "network": [{"method": "GET", "url": "/static/a.css", "status": 404}],
        "elements": [
            {"selector": "img.x", "tag": "img", "exists": True,
             "natural_width": 0, "alt": ""},
            {"selector": ".tbl", "tag": "table", "exists": True,
             "scroll_width": 1200, "client_width": 800,
             "is_scrollable_declared": False},
        ],
    })
    kinds = [o["kind"] for o in obs]
    # console (deprecated) → network → broken_image → missing_alt_text → layout_overflow
    assert kinds == ["deprecated_api_warning", "asset_load_error",
                     "broken_image", "missing_alt_text", "layout_overflow"]


def test_step_metadata_attached_to_every_observation():
    obs = C.observe(_step(n=4, priority="P0"), {"console": [{"level": "warn", "text": "x"}]})
    o = obs[0]
    assert o["step_id"] == "step-4"
    assert o["step_n"] == 4
    assert o["step_priority"] == "P0"
