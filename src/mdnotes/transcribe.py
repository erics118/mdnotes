import base64
import anthropic
from mdnotes.cache import TranscriptionCache, page_hash

MODEL = "claude-haiku-4-5"
PROMPT = (
    "Transcribe all handwritten content from this note page into clean Markdown. "
    "Preserve headings, bullet points, numbered lists, and diagrams described as text. "
    "For equations, use LaTeX fenced in $...$. "
    "If a section is illegible, write [illegible]. "
    "Output only the Markdown, no preamble."
)


def transcribe_page(
    image_bytes: bytes,
    cache: TranscriptionCache,
    client: anthropic.Anthropic | None = None,
    cache_key: str | None = None,
) -> str:
    """
    Return Markdown for a single page image.
    Uses cache to skip API call when content is unchanged.
    cache_key: if provided, use this hash instead of hashing image_bytes.
               Pass a PDF-content hash to get stable cache hits across re-downloads.
    """
    if client is None:
        client = anthropic.Anthropic()

    h = cache_key if cache_key is not None else page_hash(image_bytes)
    cached = cache.get(h)
    if cached is not None:
        return cached

    encoded = base64.standard_b64encode(image_bytes).decode()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
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
    markdown = response.content[0].text
    cache.set(h, markdown)
    return markdown
