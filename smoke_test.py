"""Stage 0 smoke test: text, tool calling, and image input against the real API."""
import base64
import json
import os
import struct
import sys
import urllib.error
import urllib.request
import zlib

import agent  # also loads .env

URL ="https://openrouter.ai/api/v1/chat/completions"
PRIMARY = os.environ.get("MODEL_PRIMARY", "google/gemma-4-31b-it:free")
FALLBACK = os.environ.get("MODEL_FALLBACK", "google/gemma-4-26b-a4b-it:free")


def red_png(size=16):
    """Build a solid red PNG by hand so no image library is needed."""
    def chunk(tag, data):
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    row = b"\x00" + b"\xff\x00\x00" * size
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(row * size))
    png += chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


def post(key, body):
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return {"http_error": exc.code, "detail": exc.read().decode(errors="replace")[:300]}
    except Exception as exc:
        return {"http_error": "network", "detail": str(exc)[:300]}


def message_of(data):
    if "http_error" in data:
        raise RuntimeError("HTTP %s: %s" % (data["http_error"], data["detail"]))
    return data["choices"][0]["message"]


def test_text(key, model):
    msg = message_of(post(key, {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
        "temperature": 0.2,
    }))
    text = msg.get("content") or ""
    return bool(text.strip()), text.strip()[:80]


def test_tools(key, model):
    schema = {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List the files in a folder.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }
    msg = message_of(post(key, {
        "model": model,
        "messages": [{"role": "user", "content": "Use the list_files tool on the folder downloads."}],
        "tools": [schema],
        "temperature": 0.2,
    }))
    calls = msg.get("tool_calls") or []
    if not calls:
        return False, "no tool_calls; content=%r" % (msg.get("content") or "")[:80]
    args = json.loads(calls[0]["function"]["arguments"])
    return calls[0]["function"]["name"] == "list_files", "args=%s" % args


def test_image(key, model):
    msg = message_of(post(key, {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "What color is this image? Reply with one word."},
            {"type": "image_url", "image_url": {"url": red_png()}},
        ]}],
        "temperature": 0.2,
    }))
    text = msg.get("content") or ""
    return "red" in text.lower(), text.strip()[:80]


def run_model(key, model):
    print("Model:", model)
    results = {}
    for name, test in (("text", test_text), ("tools", test_tools), ("image", test_image)):
        try:
            ok, detail = test(key, model)
        except Exception as exc:
            ok, detail = False, str(exc)
        results[name] = ok
        print("  %s %s: %s" % ("PASS" if ok else "FAIL", name, detail))
    return results


def main():
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("FAIL: OPENROUTER_API_KEY is not set.")
        return 2
    results = run_model(key, PRIMARY)
    if not results["tools"]:
        print("Primary failed tool calling, testing fallback.")
        results = run_model(key, FALLBACK)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
