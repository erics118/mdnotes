import base64
import anthropic
from mdnotes.cache import TranscriptionCache, page_hash

MODEL = "claude-haiku-4-5"
# bump whenever MODEL or PROMPT changes so cached transcriptions invalidate
TRANSCRIBE_VERSION = 2
PROMPT = (
    "Transcribe all handwritten content from this note page into clean Markdown. "
    "Preserve headings, bullet points, and numbered lists in their original structure. "
    "Render math in LaTeX: inline math as $...$, standalone/displayed equations as $$...$$. "
    "Render tabular content as GitHub-flavored Markdown tables. "
    "Describe diagrams in a short bracketed note, e.g. [diagram: labeled triangle]. "
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
    markdown = response.content[0].text
    cache.set(h, markdown)
    return markdown
