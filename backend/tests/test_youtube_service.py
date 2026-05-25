from app.services.youtube_service import (
    duration_matches_filter,
    parse_iso_8601_duration,
    parse_optional_int,
)


def test_parse_iso_8601_duration() -> None:
    assert parse_iso_8601_duration("PT1H2M3S") == 3723
    assert parse_iso_8601_duration("PT15M") == 900
    assert parse_iso_8601_duration("PT45S") == 45
    assert parse_iso_8601_duration("P1DT2H") == 93600
    assert parse_iso_8601_duration("not-a-duration") is None


def test_parse_optional_int() -> None:
    assert parse_optional_int("123") == 123
    assert parse_optional_int(None) is None
    assert parse_optional_int("hidden") is None


def test_duration_matches_filter() -> None:
    assert duration_matches_filter(9 * 60, "under_10") is True
    assert duration_matches_filter(10 * 60, "under_10") is False
    assert duration_matches_filter(29 * 60, "under_30") is True
    assert duration_matches_filter(30 * 60, "under_30") is False
    assert duration_matches_filter(59 * 60, "under_60") is True
    assert duration_matches_filter(60 * 60, "under_60") is False
    assert duration_matches_filter(60 * 60, "over_60") is True
    assert duration_matches_filter(None, "under_10") is False
    assert duration_matches_filter(None, "any") is True
