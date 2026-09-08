import base64
import json
import anthropic
from mdnotes.cache import TranscriptionCache, page_hash
from mdnotes.config import anthropic_key

MODEL = "claude-haiku-4-5"
# bump whenever MODEL or PROMPT changes so cached transcriptions invalidate
TRANSCRIBE_VERSION = 3

_CONTEXT_MARKER = "===SEARCH_CONTEXT==="

PROMPT = (
    "Transcribe all handwritten content from this note page into clean Markdown. "
    "Preserve headings, bullet points, and numbered lists in their original structure. "
    "Render math in LaTeX: inline math as $...$, standalone/displayed equations as $$...$$. "
    "Render tabular content as GitHub-flavored Markdown tables. "
    "Describe diagrams in a short bracketed note, e.g. [diagram: labeled triangle]. "
    "If a section is illegible, write [illegible].\n"
    f"After the Markdown, output a line containing exactly {_CONTEXT_MARKER} and then a short "
    "search aid for this page: one or two plain-English sentences summarizing what the page is "
    "about, followed by the key concepts and any expanded notation (e.g. 'ker' -> kernel, "
    "'G/H' -> quotient group). Use only concepts present or directly implied on this page; do "
    "not invent facts. Output nothing else."
)


class TranscribeError(Exception):
    pass


def _unpack(cached: str) -> tuple[str, str]:
    # cache stores {"md","ctx"}; tolerate a legacy plain-markdown string
    try:
        obj = json.loads(cached)
        if isinstance(obj, dict) and "md" in obj:
            return obj["md"], obj.get("ctx", "")
    except (json.JSONDecodeError, ValueError):
        pass
    return cached, ""


def read_cached(cache: TranscriptionCache, cache_key: str) -> tuple[str, str] | None:
    """Return (markdown, search_context) if this page is cached, else None."""
    v = cache.get(cache_key)
    return _unpack(v) if v is not None else None


def _split_response(text: str) -> tuple[str, str]:
    if _CONTEXT_MARKER in text:
        md, _, ctx = text.partition(_CONTEXT_MARKER)
        return md.strip(), ctx.strip()
    return text.strip(), ""


def transcribe_page(
    image_bytes: bytes,
    cache: TranscriptionCache,
    client: anthropic.Anthropic | None = None,
    cache_key: str | None = None,
) -> tuple[str, str]:
    """
    Return (markdown, search_context) for a single page image.

    markdown is the faithful transcription shown to the user; search_context is a
    hidden, grounded plain-language aid indexed for retrieval only (bridges terse
    math notation and natural-language queries). Uses cache to skip the API call.
    cache_key: if provided, use this hash instead of hashing image_bytes.
    """
    if client is None:
        client = anthropic.Anthropic(api_key=anthropic_key())

    h = cache_key if cache_key is not None else page_hash(image_bytes)
    cached = cache.get(h)
    if cached is not None:
        return _unpack(cached)

    encoded = base64.standard_b64encode(image_bytes).decode()
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": encoded},
                },
                {"type": "text", "text": PROMPT},
            ],
        }],
    )
    if response.stop_reason == "max_tokens":
        # truncated: caching it would permanently freeze a half-transcribed page
        raise TranscribeError(f"transcription hit max_tokens for page (cache_key={h})")
    text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    raw = "".join(text_blocks).strip()
    if not raw:
        raise TranscribeError(f"empty transcription response (cache_key={h})")
    markdown, context = _split_response(raw)
    if not markdown:
        raise TranscribeError(f"empty transcription markdown (cache_key={h})")
    cache.set(h, json.dumps({"md": markdown, "ctx": context}))
    return markdown, context
