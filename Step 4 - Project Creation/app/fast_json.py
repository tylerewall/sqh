"""Fast JSON helpers — uses orjson (C extension, ~10x faster) with stdlib fallback."""

try:
    import orjson

    def dumps(obj) -> bytes:
        return orjson.dumps(obj)

    def dumps_str(obj) -> str:
        return orjson.dumps(obj).decode("utf-8")

    def loads(data):
        return orjson.loads(data)

    BACKEND = "orjson"

except ImportError:
    import json as _json

    def dumps(obj) -> bytes:
        return _json.dumps(obj, separators=(",", ":")).encode("utf-8")

    def dumps_str(obj) -> str:
        return _json.dumps(obj, separators=(",", ":"))

    def loads(data):
        return _json.loads(data)

    BACKEND = "stdlib"
