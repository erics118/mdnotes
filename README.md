# mdnotes

Sync GoodNotes PDFs from Google Drive and transcribe handwriting to Markdown via Claude vision.

## Setup

### System dependency

```bash
brew install poppler
```

### Python

```bash
pip install -e .
```

### Google credentials

1. Create a project at https://console.cloud.google.com
2. Enable the Google Drive API
3. Create an OAuth 2.0 Desktop app client ID
4. Download the JSON and save to `credentials/client_secret.json`

### Anthropic API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
mdnotes sync                          # writes to ~/notes/
mdnotes sync --output-dir ./output
mdnotes sync --folder-name "GoodNotes 5" --dpi 200
```

## Cost

~$0.013 per 10-page notebook at 150 DPI (Claude Haiku vision pricing).
Transcriptions are cached by content hash — re-running is free for unchanged pages.
