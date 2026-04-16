# tests/conftest.py
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_drive_service():
    svc = MagicMock()
    return svc
