from app.services.youtube_service import parse_iso_8601_duration, parse_optional_int


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
