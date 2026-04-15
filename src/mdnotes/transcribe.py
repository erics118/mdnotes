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
) -> str:
    """
    Return Markdown for a single page image.
    Uses cache to skip API call when content is unchanged.
    """
    if client is None:
        client = anthropic.Anthropic()

    h = page_hash(image_bytes)
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


def transcribe_pdf_pages(
    pages: list[tuple[int, bytes]],
    cache: TranscriptionCache,
    client: anthropic.Anthropic | None = None,
) -> str:
    """
    Transcribe all pages of a PDF and return stitched Markdown.
    pages: list of (page_number, image_bytes) tuples.
    """
    parts = [transcribe_page(img, cache=cache, client=client) for _, img in pages]
    return "\n\n---\n\n".join(parts)
