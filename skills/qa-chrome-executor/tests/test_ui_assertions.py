"""Unit tests for the agentic UI assertion vocabulary in scenario_dispatcher.

Pure-Python, no network, no browser. Run with: pytest tests/test_ui_assertions.py
"""
from scenario_dispatcher import (
    Assertion,
    CapturedPage,
    FoundElement,
    ConsoleMessage,
    run_ui_assertions,
    ALLOWED_UI_ASSERTION_KINDS,
    ALLOWED_ASSERTION_KINDS,
)


def A(kind, **args):
    return Assertion(kind=kind, args=args)


def test_ui_kinds_registered_in_master_set():
    # The matrix validator must accept UI kinds too (for future UI matrix rules).
    assert ALLOWED_UI_ASSERTION_KINDS <= ALLOWED_ASSERTION_KINDS


def test_element_visible_pass_and_fail():
    page = CapturedPage(elements=[
        FoundElement(selector="[data-testid=save]", exists=True, visible=True),
        FoundElement(selector="[data-testid=hidden]", exists=True, visible=False),
    ])
    ok, failed = run_ui_assertions(page, [A("element_visible", selector="[data-testid=save]")])
    assert ok and not failed

    ok, failed = run_ui_assertions(page, [A("element_visible", selector="[data-testid=hidden]")])
    assert not ok and failed

    # Never-queried selector is not visible.
    ok, _ = run_ui_assertions(page, [A("element_visible", selector="[data-testid=ghost]")])
    assert not ok


def test_element_absent():
    page = CapturedPage(elements=[
        FoundElement(selector="#err", exists=False, visible=False),
        FoundElement(selector="#shown", exists=True, visible=True),
    ])
    ok, _ = run_ui_assertions(page, [A("element_absent", selector="#err")])
    assert ok
    ok, _ = run_ui_assertions(page, [A("element_absent", selector="#shown")])
    assert not ok
    # Selector never queried counts as absent.
    ok, _ = run_ui_assertions(page, [A("element_absent", selector="#never")])
    assert ok


def test_text_present_and_absent_case_insensitive():
    page = CapturedPage(text="Internal Medicine — Block Schedule 2026-05-12")
    ok, _ = run_ui_assertions(page, [A("text_present", patterns=["internal medicine", "2026-05-12"])])
    assert ok
    # off-by-one date bug: the wrong date must NOT be present
    ok, _ = run_ui_assertions(page, [A("text_absent", patterns=["2026-05-11"])])
    assert ok
    ok, _ = run_ui_assertions(page, [A("text_present", patterns=["nonexistent"])])
    assert not ok


def test_value_eq():
    page = CapturedPage(elements=[
        FoundElement(selector="#start_date", exists=True, visible=True, value="2026-05-12"),
    ])
    ok, _ = run_ui_assertions(page, [A("value_eq", selector="#start_date", value="2026-05-12")])
    assert ok
    ok, _ = run_ui_assertions(page, [A("value_eq", selector="#start_date", value="2026-05-11")])
    assert not ok


def test_console_clean_with_ignore():
    page = CapturedPage(console=[
        ConsoleMessage(level="warning", text="deprecation"),
        ConsoleMessage(level="error", text="favicon.ico 404"),
    ])
    # Bare console_clean fails because there's an error.
    ok, _ = run_ui_assertions(page, [A("console_clean")])
    assert not ok
    # Ignoring the known-benign favicon error makes it clean.
    ok, _ = run_ui_assertions(page, [A("console_clean", ignore=["favicon.ico"])])
    assert ok


def test_console_clean_no_errors():
    page = CapturedPage(console=[ConsoleMessage(level="log", text="ok")])
    ok, _ = run_ui_assertions(page, [A("console_clean")])
    assert ok


def test_url_matches():
    page = CapturedPage(url="https://6850.medtrics.dev/curriculum/block-schedule/")
    ok, _ = run_ui_assertions(page, [A("url_matches", pattern=r"/block-schedule/?$")])
    assert ok
    ok, _ = run_ui_assertions(page, [A("url_matches", pattern=r"/login")])
    assert not ok


def test_download_filename_eq_value_and_pattern():
    page = CapturedPage(downloads=["courses_and_rotations.csv"])
    ok, _ = run_ui_assertions(page, [A("download_filename_eq", value="courses_and_rotations.csv")])
    assert ok
    ok, _ = run_ui_assertions(page, [A("download_filename_eq", pattern=r"\.csv$")])
    assert ok
    ok, _ = run_ui_assertions(page, [A("download_filename_eq", pattern=r"\.xlsx$")])
    assert not ok


def test_multiple_assertions_all_must_pass():
    page = CapturedPage(
        text="Saved successfully",
        console=[ConsoleMessage(level="log", text="ok")],
    )
    ok, failed = run_ui_assertions(page, [
        A("text_present", patterns=["Saved successfully"]),
        A("console_clean"),
    ])
    assert ok and not failed

    page2 = CapturedPage(
        text="Saved successfully",
        console=[ConsoleMessage(level="error", text="boom")],
    )
    ok, failed = run_ui_assertions(page2, [
        A("text_present", patterns=["Saved successfully"]),
        A("console_clean"),
    ])
    assert not ok and len(failed) == 1
