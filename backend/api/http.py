import json

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


def json_response(body: dict, status_code: int = 200) -> dict:
    return {
        "statusCode": status_code,
        "headers": HEADERS,
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }


def error_response(message: str, status_code: int = 400) -> dict:
    return json_response({"error": message}, status_code)


def parse_body(event: dict) -> dict:
    raw = event.get("body")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)


def request_method(event: dict) -> str:
    return (
        event.get("httpMethod")
        or event.get("requestContext", {}).get("http", {}).get("method")
        or ""
    )


def request_path(event: dict) -> str:
    return event.get("rawPath") or event.get("path") or ""


def match_template(template: str, path: str) -> dict | None:
    template_parts = [p for p in template.strip("/").split("/") if p != ""]
    path_parts = [p for p in path.strip("/").split("/") if p != ""]
    if len(template_parts) != len(path_parts):
        return None
    params = {}
    for expected, actual in zip(template_parts, path_parts):
        if expected.startswith("{") and expected.endswith("}"):
            params[expected[1:-1]] = actual
        elif expected != actual:
            return None
    return params
