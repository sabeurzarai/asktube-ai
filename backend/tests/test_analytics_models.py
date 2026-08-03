from sqlalchemy.dialects import postgresql, sqlite

from app.analytics.models import AnalyticsEvent, ChatMetric, RAGMetric, VideoMetric


def test_metadata_json_compiles_to_jsonb_on_postgres():
    for model in (AnalyticsEvent, VideoMetric, ChatMetric, RAGMetric):
        column = model.__table__.c.metadata_json
        compiled = column.type.compile(dialect=postgresql.dialect())
        assert compiled == "JSONB", f"{model.__name__} should use JSONB on postgres"


def test_metadata_json_stays_json_on_sqlite():
    column = AnalyticsEvent.__table__.c.metadata_json
    assert column.type.compile(dialect=sqlite.dialect()) == "JSON"
