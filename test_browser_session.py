"""Tests for browser_session — lifecycle config, delays, CAPTCHA loop.

No real browser: fake pages/detectors cover the shared logic. The launch
path itself is verified by running the e-disclosure pilot manually.
"""
import uuid
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import browser_session as bs
from browser_session import (
    BrowserSession,
    EDISCLOSURE_CAPTCHA,
    EdisclosureCaptchaDetector,
    FinamCaptchaDetector,
    wait_captcha_resolved,
)


@pytest.fixture
def sleep_log(monkeypatch):
    """Capture time.sleep calls inside browser_session."""
    calls = []
    monkeypatch.setattr(bs.time, "sleep", lambda s: calls.append(s))
    return calls


def make_config():
    from config import Config
    return Config()


# ---------------------------------------------------------------------------
# Delays
# ---------------------------------------------------------------------------

def test_human_delay_uses_session_range(sleep_log):
    session = BrowserSession(make_config(), delay_range=(2.0, 3.0))
    for _ in range(30):
        session.human_delay()
    assert sleep_log and all(2.0 <= s <= 3.0 for s in sleep_log)


def test_human_delay_override_per_call(sleep_log):
    session = BrowserSession(make_config(), delay_range=(20.0, 45.0))
    session.human_delay((0.1, 0.2))
    assert sleep_log and all(0.1 <= s <= 0.2 for s in sleep_log)


# ---------------------------------------------------------------------------
# wait_captcha_resolved
# ---------------------------------------------------------------------------

def make_page(captcha_sequence):
    """Fake page whose evaluate returns values popped from a sequence."""
    seq = list(captcha_sequence)

    def evaluate(js):
        return seq.pop(0) if seq else False

    def wait_for_load_state(state, timeout):
        pass

    return SimpleNamespace(evaluate=evaluate, wait_for_load_state=wait_for_load_state)


def test_wait_returns_true_immediately_without_captcha(sleep_log):
    page = make_page([False])
    assert wait_captcha_resolved(page, EDISCLOSURE_CAPTCHA, timeout_seconds=10) is True
    assert sleep_log == []  # no polling when nothing detected


def test_wait_polls_until_resolution(sleep_log):
    page = make_page([True, True, False])
    assert wait_captcha_resolved(page, EDISCLOSURE_CAPTCHA, timeout_seconds=60) is True
    assert sleep_log == [3, 3]  # two poll intervals


def test_wait_holds_min_wait_after_auto_resolution(sleep_log):
    # Captcha detected, resolves on first poll
    page = make_page([True, False])
    assert wait_captcha_resolved(page, EDISCLOSURE_CAPTCHA, timeout_seconds=60, min_wait=15) is True
    # One poll interval (3s) + the min_wait hold. Sleeps are mocked, so real
    # elapsed time is ~0 and the hold is the full min_wait.
    assert len(sleep_log) == 2
    assert sleep_log[0] == 3
    assert sleep_log[-1] == pytest.approx(15.0, abs=0.5)


def test_wait_timeout_returns_false(sleep_log):
    page = make_page([])  # never a captcha — but force the "detected" branch via always-True detector

    class AlwaysCaptcha:
        def detect(self, page):
            return True

    assert wait_captcha_resolved(page, AlwaysCaptcha(), timeout_seconds=0.05) is False


def test_wait_treats_page_destruction_as_resolution(sleep_log):
    """Page destroyed mid-navigation → detector swallows → no captcha."""
    class Boom:
        def evaluate(self, js):
            raise RuntimeError("Execution context was destroyed")

    assert wait_captcha_resolved(Boom(), EDISCLOSURE_CAPTCHA, timeout_seconds=10) is True


# ---------------------------------------------------------------------------
# Detection adapters
# ---------------------------------------------------------------------------

def test_finam_detector_css_path():
    visible = SimpleNamespace(evaluate=lambda js: "block")
    hidden = SimpleNamespace(evaluate=lambda js: "none")
    assert FinamCaptchaDetector().detect(SimpleNamespace(query_selector=lambda sel: visible)) is True
    assert FinamCaptchaDetector().detect(SimpleNamespace(query_selector=lambda sel: hidden)) is False
    assert FinamCaptchaDetector().detect(SimpleNamespace(query_selector=lambda sel: None)) is False


def test_finam_detector_swallows_errors():
    class Boom:
        def query_selector(self, sel):
            raise RuntimeError("no page")

    assert FinamCaptchaDetector().detect(Boom()) is False


def test_edisclosure_detector_text_match():
    assert EdisclosureCaptchaDetector().detect(make_page([True])) is True
    assert EdisclosureCaptchaDetector().detect(make_page([False])) is False


def test_edisclosure_detector_swallows_errors():
    class Boom:
        def evaluate(self, js):
            raise RuntimeError("context destroyed")

    assert EdisclosureCaptchaDetector().detect(Boom()) is False


# ---------------------------------------------------------------------------
# Session lifecycle (no real launch: start/stop state transitions)
# ---------------------------------------------------------------------------

def test_session_headless_defaults_to_config():
    config = make_config()
    assert BrowserSession(config).headless == config.browser_headless
    assert BrowserSession(config, headless=False).headless is False


def test_session_stop_without_start_is_noop():
    session = BrowserSession(make_config(), delay_range=(0.1, 0.2))
    session.stop()  # must not raise
    assert session._page is None
    assert session._started is False


def test_lazy_session_starts_on_first_page_access(monkeypatch):
    session = BrowserSession(make_config(), delay_range=(0.1, 0.2), lazy=True)
    calls = []
    monkeypatch.setattr(session, "_start_impl", lambda: calls.append("start"))

    assert calls == []  # nothing started yet
    page1 = session.page  # first access triggers start
    assert calls == ["start"]
    page2 = session.page  # second access is a no-op
    assert calls == ["start"]
    assert page1 is page2


def test_lazy_with_block_defers_start(monkeypatch):
    session = BrowserSession(make_config(), delay_range=(0.1, 0.2), lazy=True)
    calls = []
    monkeypatch.setattr(session, "_start_impl", lambda: calls.append("start"))

    with session as entered:
        assert calls == []  # context entry does NOT start a lazy session
        entered.page  # but touching the page does
        assert calls == ["start"]
    assert session._started is False  # stop() reset the state


def test_eager_with_block_starts_immediately(monkeypatch):
    session = BrowserSession(make_config(), delay_range=(0.1, 0.2))
    calls = []
    monkeypatch.setattr(session, "_start_impl", lambda: calls.append("start"))

    with session as entered:
        assert calls == ["start"]  # eager start on entry
        assert entered.page is session._page
    assert session._started is False


def test_stop_resets_started_flag(monkeypatch):
    session = BrowserSession(make_config(), delay_range=(0.1, 0.2))
    monkeypatch.setattr(session, "_start_impl", lambda: None)
    session.start()
    assert session._started is True
    session.stop()
    assert session._started is False
    session.stop()  # idempotent