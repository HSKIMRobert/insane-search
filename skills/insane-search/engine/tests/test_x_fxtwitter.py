#!/usr/bin/env python3
"""X 장문·아티클 FxTwitter 조건부 폴백 테스트 (v0.17.0).

Background (2026-10-08 measurement, 18 tweets): syndication tweet-result and
oEmbed cut long-form tweets at ~280 chars and return only a t.co link for X
Articles. api.fxtwitter.com returned the full text for 6/6 long/article tweets
and added nothing for 12/12 short tweets. So FxTwitter is called ONLY when the
tweet-result JSON shows a long/article signal.

Run manually:
    python3 engine/tests/test_x_fxtwitter.py                       # offline
    INSANE_TEST_NETWORK=1 python3 engine/tests/test_x_fxtwitter.py  # + live re-measure
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from engine import phase0  # noqa: E402

LONG_TEXT = ("There's a new kind of coding I call \"vibe coding\", where you fully give in to the vibes, "
             "embrace exponentials, and forget that the code even exists. ") * 6
ARTICLE_BODY = ["2025 has been a strong and eventful year of progress in LLMs.",
                "The following is a list of personally notable paradigm changes."]


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def json(self):
        return json.loads(self.text)


def _install(routes):
    """routes: substring → (status, payload) | Exception. Records every URL called."""
    calls = []

    def fake(url, *, impersonate="safari", timeout=15):
        calls.append(url)
        for key, val in routes.items():
            if key in url:
                if isinstance(val, Exception):
                    raise val
                return _Resp(*val)
        return _Resp(404, {})

    phase0._cffi_get = fake
    return calls


def _synd(text, **extra):
    d = {"__typename": "Tweet", "text": text, "user": {"screen_name": "karpathy"}}
    d.update(extra)
    return (200, d)


def _fx_tweet(text):
    return (200, {"code": 200, "tweet": {"text": text, "raw_text": {"text": text}}})


def _fx_article():
    return (200, {"code": 200, "tweet": {"text": "", "article": {
        "title": "2025 LLM Year in Review",
        "content": {"blocks": [{"text": t} for t in ARTICLE_BODY]}}}})


URL = "https://x.com/karpathy/status/1886192184808149383"


def _route(url, **kw) -> dict:
    r = phase0.route(url, **kw)
    assert r is not None, url
    return r


def _fx_called(calls):
    return any("api.fxtwitter.com" in c for c in calls)


# ── offline ────────────────────────────────────────────────────────────────

def t_short_tweet_never_calls_fxtwitter():
    calls = _install({"tweet-result": _synd("Short tweet, nothing to expand here.")})
    r = _route(URL)
    assert r["ok"] and r["route"] == "tweet-result", r
    assert not _fx_called(calls), calls
    assert not r.get("truncated_possible"), r


def t_note_tweet_signal_gets_full_text():
    calls = _install({"tweet-result": _synd(LONG_TEXT[:280], note_tweet={"id": "x"}),
                      "api.fxtwitter.com": _fx_tweet(LONG_TEXT)})
    r = _route(URL)
    assert _fx_called(calls), calls
    assert r["ok"] and r["route"] == "fxtwitter", r
    assert LONG_TEXT.strip()[-40:] in r["content"], r["content"][:200]
    assert not r.get("truncated_possible"), r
    assert [a["route"] for a in r["attempts"]] == ["tweet-result", "fxtwitter"], r["attempts"]


def t_article_signal_gets_blocks():
    _install({"tweet-result": _synd("https://t.co/Lb6T42n5jl", article={"title": "2025 LLM Year in Review"}),
              "api.fxtwitter.com": _fx_article()})
    r = _route(URL)
    assert r["route"] == "fxtwitter", r
    for line in ARTICLE_BODY:
        assert line in r["content"], line
    assert "2025 LLM Year in Review" in r["content"]


def t_length_270_signal():
    calls = _install({"tweet-result": _synd("a" * 275), "api.fxtwitter.com": _fx_tweet("a" * 900)})
    r = _route(URL)
    assert _fx_called(calls) and r["route"] == "fxtwitter", r


def t_tco_only_signal():
    calls = _install({"tweet-result": _synd("https://t.co/abc123XYZ"), "api.fxtwitter.com": _fx_article()})
    _route(URL)
    assert _fx_called(calls), calls


def t_fxtwitter_failure_falls_back_with_flag():
    _install({"tweet-result": _synd(LONG_TEXT[:280], note_tweet={"id": "x"}),
              "api.fxtwitter.com": RuntimeError("boom")})
    r = _route(URL)
    assert r["ok"] and r["route"] == "tweet-result", r
    assert r["truncated_possible"] is True and r["truncation_reason"] == "fxtwitter_failed", r
    assert r["attempts"][-1]["route"] == "fxtwitter" and not r["attempts"][-1]["ok"], r["attempts"]


def t_fxtwitter_not_longer_is_failure():
    _install({"tweet-result": _synd(LONG_TEXT[:280], note_tweet={"id": "x"}),
              "api.fxtwitter.com": _fx_tweet(LONG_TEXT[:280])})
    r = _route(URL)
    assert r["route"] == "tweet-result" and r["truncation_reason"] == "fxtwitter_failed", r


def t_switch_off():
    os.environ["INSANE_SEARCH_FXTWITTER"] = "0"
    try:
        calls = _install({"tweet-result": _synd(LONG_TEXT[:280], note_tweet={"id": "x"}),
                          "api.fxtwitter.com": _fx_tweet(LONG_TEXT)})
        r = _route(URL)
    finally:
        del os.environ["INSANE_SEARCH_FXTWITTER"]
    assert not _fx_called(calls), calls
    assert r["truncated_possible"] is True and r["truncation_reason"] == "fxtwitter_disabled", r


def t_flag_reaches_fetch_result():
    """phase0 표시가 FetchResult.extraction_meta와 summary까지 전달된다."""
    from engine.fetch_chain import fetch
    _install({"tweet-result": _synd(LONG_TEXT[:280], note_tweet={"id": "x"}),
              "api.fxtwitter.com": RuntimeError("boom")})
    res = fetch(URL, enable_playwright=False)
    assert res.ok, res.summary
    assert res.extraction_meta.get("truncated_possible") is True, res.extraction_meta
    assert "truncated_possible" in res.summary, res.summary


# ── network (re-measure 2026-10-08 sample) ────────────────────────────────

_SAMPLE = os.path.join(ROOT, "..", "..", "..", "..", "PRD-insane-evidence-x", "evidence", "fxtwitter_results.json")


def n_live_remeasure():
    import importlib
    importlib.reload(phase0)  # drop offline fake
    rows = json.load(open(os.path.abspath(_SAMPLE)))
    long_ids = {"1886192184808149383", "1937902205765607626", "2029882554401099799",
                "2002118205729562949", "1764712134888325534", "2043751384487723323"}
    full, short_no_fx, short_total = 0, 0, 0
    for row in rows:
        calls = []
        real = phase0._cffi_get

        def spy(url, **kw):
            calls.append(url)
            return real(url, **kw)

        phase0._cffi_get = spy
        try:
            r = _route(row["url"], timeout=20)
        finally:
            phase0._cffi_get = real
        if row["id"] in long_ids:
            full += int(r["route"] == "fxtwitter")
        else:
            short_total += 1
            short_no_fx += int(not _fx_called(calls))
    print(f"    long/article full via fxtwitter: {full}/{len(long_ids)}; "
          f"short without fxtwitter: {short_no_fx}/{short_total}")
    assert full == len(long_ids), full
    assert short_no_fx >= short_total - 3, (short_no_fx, short_total)  # 경계 표본(unknown 3건) 허용


if __name__ == "__main__":
    _failed = 0
    names = [n for n in sorted(globals()) if n.startswith("t_")]
    if os.environ.get("INSANE_TEST_NETWORK") == "1":
        names.append("n_live_remeasure")
    original = phase0._cffi_get
    for name in names:
        try:
            globals()[name](); print(f"  ✓ {name}")
        except AssertionError as e:
            _failed += 1; print(f"  ✗ {name}: {e}")
        except Exception as e:
            _failed += 1; print(f"  ✗ {name}: {type(e).__name__}: {e}")
        finally:
            phase0._cffi_get = original
    print("FAIL" if _failed else "OK")
    sys.exit(1 if _failed else 0)
