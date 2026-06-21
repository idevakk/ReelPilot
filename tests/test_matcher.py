"""Pure-logic tests (no API keys, no network)."""

from shortmaker import matcher
from shortmaker.hooks import CATALOG, Hook, by_name


def test_keyword_score_direct_overlap():
    snow = Hook(name="Snowball-Splash", url="x", description="x", tags=["snow", "splash"])
    other = Hook(name="Wedding-Cry", url="x", description="x", tags=["wedding", "cry"])
    assert matcher.keyword_score("snowball fight", snow) > matcher.keyword_score("snowball fight", other)


def test_keyword_score_tag_substring():
    snow = Hook(name="Snowball-Splash", url="x", description="x", tags=["snow", "winter"])
    beach = Hook(name="Front-Flip-Sand", url="x", description="x", tags=["beach"])
    assert matcher.keyword_score("snow", snow) > matcher.keyword_score("snow", beach)


def test_rank_orders_by_score():
    ranked = matcher.rank("splash fail prank")
    names = [h.name for h, _ in ranked]
    assert names[0] == "Snowball-Splash"


def test_best_returns_top():
    hook = matcher.best("wedding moment")
    assert hook.name == "Wedding-Cry"


def test_by_name_normalizes_case_and_separators():
    assert by_name("snowball_splash").name == "Snowball-Splash"
    assert by_name("WEDDING-CRY").name == "Wedding-Cry"


def test_by_name_unknown_raises():
    import pytest
    with pytest.raises(KeyError):
        by_name("nope")


def test_catalog_has_nine_hooks():
    assert len(CATALOG) == 9


def test_rerank_returns_input_when_no_key():
    out = matcher.rerank_with_llm("topic", list(CATALOG[:3]),
                                   api_key=None, base_url=None, model=None)
    assert out == list(CATALOG[:3])