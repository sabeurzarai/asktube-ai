import math

import pytest

from app.schemas.chunks import TranscriptChunk
from app.services.vector_store.base import chunk_to_result, cosine_distance


def make_chunk(**overrides) -> TranscriptChunk:
    data = {
        "chunk_id": "vid1-0",
        "index": 0,
        "video_id": "vid1",
        "text": "hello world",
        "start_seconds": 0.0,
        "end_seconds": 5.0,
        "segment_indices": [0, 1],
        "token_estimate": 3,
        "metadata": {"source": "captions", "language": "en"},
        "embedding": [1.0, 0.0],
    }
    data.update(overrides)
    return TranscriptChunk(**data)


def test_identical_vectors_have_zero_distance():
    assert cosine_distance([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)


def test_orthogonal_vectors_have_distance_one():
    assert cosine_distance([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)


def test_opposite_vectors_have_distance_two():
    assert cosine_distance([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(2.0)


def test_magnitude_does_not_affect_distance():
    # Cosine compares direction only; a scaled vector must match exactly.
    assert cosine_distance([1.0, 2.0], [10.0, 20.0]) == pytest.approx(0.0)


def test_zero_vector_yields_max_distance_rather_than_dividing_by_zero():
    assert cosine_distance([0.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_dimension_mismatch_raises_clear_error():
    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine_distance([1.0, 0.0], [1.0, 0.0, 0.0])


def test_chunk_to_result_maps_fields_and_filters_metadata():
    chunk = make_chunk(metadata={"source": "captions", "bad": [1, 2]})
    result = chunk_to_result(chunk, 0.25)
    assert result.chunk_id == "vid1-0"
    assert result.video_id == "vid1"
    assert result.text == "hello world"
    assert result.start_seconds == 0.0
    assert result.end_seconds == 5.0
    assert result.segment_indices == [0, 1]
    assert result.distance == 0.25
    # VectorSearchResult.metadata only allows scalars; list values are dropped.
    assert result.metadata == {"source": "captions"}
