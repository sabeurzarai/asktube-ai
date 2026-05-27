from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest


REQUEST_COUNT = Counter(
    "request_count",
    "Total HTTP requests handled by AskTube AI.",
    ["method", "path", "status_code"],
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
)
RAG_LATENCY = Histogram("rag_latency_seconds", "RAG answer latency in seconds.")
EMBEDDING_DURATION = Histogram("embedding_duration_seconds", "Embedding generation duration in seconds.")
VECTOR_QUERY_DURATION = Histogram("vector_query_duration_seconds", "Vector query duration in seconds.")
PROCESSING_DURATION = Histogram("processing_duration_seconds", "Video processing duration in seconds.")
WEBSOCKET_CONNECTIONS = Gauge("websocket_connections", "Active AskTube websocket connections.", ["endpoint"])
WEBSOCKET_FAILURES = Counter("websocket_failures", "Websocket failures.", ["endpoint"])


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
