# tests/conftest.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir(tmp_path):
    return tmp_path


@pytest.fixture
def mock_drive_service():
    svc = MagicMock()
    return svc
