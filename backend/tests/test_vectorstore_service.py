from app.schemas.chunks import TranscriptChunk
from app.services.vectorstore_service import parse_chroma_query_result, to_chroma_metadata


def make_chunk() -> TranscriptChunk:
    return TranscriptChunk(
        chunk_id="video123:0:abc",
        index=0,
        video_id="video123",
        text="A timestamped transcript chunk.",
        start_seconds=12.5,
        end_seconds=22.75,
        segment_indices=[3, 4, 5],
        token_estimate=5,
        metadata={
            "video_id": "video123",
            "source": "youtube_transcript_api",
            "language": "en",
            "chunk_index": 0,
            "start_seconds": 12.5,
            "end_seconds": 22.75,
            "segment_indices": [3, 4, 5],
        },
    )


def test_to_chroma_metadata_preserves_timestamps() -> None:
    metadata = to_chroma_metadata(make_chunk())

    assert metadata["video_id"] == "video123"
    assert metadata["start_seconds"] == 12.5
    assert metadata["end_seconds"] == 22.75
    assert metadata["segment_indices"] == "[3, 4, 5]"
    assert metadata["source"] == "youtube_transcript_api"


def test_parse_chroma_query_result() -> None:
    results = parse_chroma_query_result(
        {
            "ids": [["video123:0:abc"]],
            "documents": [["A timestamped transcript chunk."]],
            "metadatas": [
                [
                    {
                        "video_id": "video123",
                        "start_seconds": 12.5,
                        "end_seconds": 22.75,
                        "segment_indices": "[3, 4, 5]",
                        "source": "youtube_transcript_api",
                    }
                ]
            ],
            "distances": [[0.12]],
        }
    )

    assert len(results) == 1
    assert results[0].chunk_id == "video123:0:abc"
    assert results[0].segment_indices == [3, 4, 5]
    assert results[0].distance == 0.12
