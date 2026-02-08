"""Unit tests for GmailSource with mocked EZGmail."""

import base64
import sys
from datetime import datetime, date
from unittest.mock import MagicMock, patch

import pytest

from paper_feed.sources.gmail import GmailSource, _extract_html_body


@pytest.fixture(autouse=True)
def set_gmail_env_vars(monkeypatch):
    """Set required Gmail JSON env vars for all tests."""
    monkeypatch.setenv(
        "GMAIL_TOKEN_JSON",
        '{"token": "test_token", "refresh_token": "test_refresh", "token_uri": "https://oauth2.googleapis.com/token", "client_id": "test_id", "client_secret": "test_secret", "scopes": ["https://www.googleapis.com/auth/gmail.modify"]}',
    )
    monkeypatch.setenv(
        "GMAIL_CREDENTIALS_JSON",
        '{"installed": {"client_id": "test_id", "project_id": "test_project", "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs", "client_secret": "test_secret", "redirect_uris": ["http://localhost"]}}',
    )
    monkeypatch.setenv("GMAIL_SENDER_FILTER", "")
    monkeypatch.setenv("GMAIL_SENDER_MAP_JSON", "{}")
    yield
    # Cleanup is handled by monkeypatch automatically


# ── _extract_html_body tests ────────────────────────────────────────


def _make_message_obj(html_content: str) -> dict:
    """Create a minimal Gmail API message object with HTML body."""
    encoded = base64.urlsafe_b64encode(html_content.encode("utf-8")).decode("ascii")
    return {
        "id": "msg_test",
        "threadId": "thread_test",
        "snippet": "test snippet",
        "historyId": "12345",
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "test@example.com"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": "Test Subject"},
                {"name": "Content-Type", "value": 'text/html; charset="UTF-8"'},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {
                        "data": base64.urlsafe_b64encode(b"Plain text body").decode(
                            "ascii"
                        )
                    },
                    "headers": [
                        {
                            "name": "Content-Type",
                            "value": 'text/plain; charset="UTF-8"',
                        }
                    ],
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": encoded},
                    "headers": [
                        {
                            "name": "Content-Type",
                            "value": 'text/html; charset="UTF-8"',
                        }
                    ],
                },
            ],
        },
    }


def test_extract_html_body_multipart():
    """Extracts HTML body from multipart message."""
    html = "<html><body><p>Hello</p></body></html>"
    msg_obj = _make_message_obj(html)
    result = _extract_html_body(msg_obj)
    assert result == html


def test_extract_html_body_direct():
    """Extracts HTML body from direct HTML payload."""
    html = "<p>Direct HTML</p>"
    encoded = base64.urlsafe_b64encode(html.encode("utf-8")).decode("ascii")
    msg_obj = {
        "payload": {
            "mimeType": "text/html",
            "body": {"data": encoded},
        }
    }
    result = _extract_html_body(msg_obj)
    assert result == html


def test_extract_html_body_empty():
    """Returns empty string when no HTML part found."""
    msg_obj = {
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": base64.urlsafe_b64encode(b"text").decode("ascii")},
        }
    }
    result = _extract_html_body(msg_obj)
    assert result == ""


def test_extract_html_body_no_payload():
    """Returns empty string when payload is missing."""
    assert _extract_html_body({}) == ""


# ── GmailSource unit tests ──────────────────────────────────────────


def test_gmail_source_init():
    """GmailSource initializes with correct defaults."""
    source = GmailSource(query="from:test@example.com")
    assert source.query == "from:test@example.com"
    assert source.source_name == "Gmail"
    assert source.source_type == "email"
    assert source.max_results == 50
    assert source.mark_as_read is False
    assert source._initialized is False


def test_gmail_source_custom_params():
    """GmailSource respects custom parameters."""
    source = GmailSource(
        query="label:INBOX",
        source_name="Google Scholar",
        max_results=10,
        mark_as_read=True,
    )
    assert source.source_name == "Google Scholar"
    assert source.max_results == 10
    assert source.mark_as_read is True


SAMPLE_EMAIL_HTML = """
<html><body>
<table>
  <tr>
    <td><a href="https://doi.org/10.1021/acs.test.2024">
      Test Paper: Machine Learning for Chemistry
    </a></td>
    <td>Author A, Author B</td>
  </tr>
</table>
</body></html>
"""


@pytest.mark.asyncio
async def test_gmail_source_fetch_papers():
    """GmailSource.fetch_papers() returns PaperItem objects from mocked emails."""
    source = GmailSource(
        query="from:test@example.com",
        source_name="Test Alert",
    )
    source._initialized = True  # Skip init

    # Create mock message
    mock_message = MagicMock()
    mock_message.id = "msg_001"
    mock_message.subject = "New articles"
    mock_message.sender = "test@example.com"
    mock_message.timestamp = datetime(2024, 6, 15, 12, 0, 0)
    mock_message.body = "Plain text"
    mock_message.messageObj = _make_message_obj(SAMPLE_EMAIL_HTML)

    # Create mock thread
    mock_thread = MagicMock()
    mock_thread.id = "thread_001"
    mock_thread.messages = [mock_message]
    mock_thread.markAsRead = MagicMock()
    mock_thread.trash = MagicMock()

    # Patch ezgmail in sys.modules so 'import ezgmail' inside fetch_papers resolves to mock
    mock_ezgmail = MagicMock()
    mock_ezgmail.search.return_value = [mock_thread]

    with patch.dict(sys.modules, {"ezgmail": mock_ezgmail}):
        papers = await source.fetch_papers()

    assert len(papers) >= 1
    assert papers[0].source_type == "email"
    assert papers[0].source == "Test Alert"
    assert "Machine Learning" in papers[0].title


@pytest.mark.asyncio
async def test_gmail_source_fetch_papers_with_limit():
    """GmailSource respects limit parameter."""
    source = GmailSource(query="test", source_name="Test")
    source._initialized = True

    # Create 3 mock messages with papers
    messages = []
    for i in range(3):
        msg = MagicMock()
        msg.id = f"msg_{i}"
        msg.subject = "Papers"
        msg.timestamp = datetime(2024, 6, 15)
        msg.body = "text"
        html = f"""
        <html><body><table><tr>
          <td><a href="https://doi.org/10.1000/test.{i}">
            Paper Title Number {i} With Enough Length
          </a></td>
        </tr></table></body></html>
        """
        msg.messageObj = _make_message_obj(html)
        messages.append(msg)

    mock_thread = MagicMock()
    mock_thread.id = "thread_001"
    mock_thread.messages = messages
    mock_thread.trash = MagicMock()

    mock_ezgmail = MagicMock()
    mock_ezgmail.search.return_value = [mock_thread]

    with patch.dict(sys.modules, {"ezgmail": mock_ezgmail}):
        papers = await source.fetch_papers(limit=2)

    assert len(papers) <= 2


@pytest.mark.asyncio
async def test_gmail_source_fetch_papers_date_filter():
    """GmailSource filters by date."""
    source = GmailSource(query="test", source_name="Test")
    source._initialized = True

    # Create message with old date
    old_msg = MagicMock()
    old_msg.id = "msg_old"
    old_msg.subject = "Old"
    old_msg.timestamp = datetime(2020, 1, 1)
    old_msg.body = "text"
    old_msg.messageObj = _make_message_obj(
        '<html><body><table><tr><td><a href="https://doi.org/10.1/old">'
        "Old Paper From Long Ago That Should Be Filtered</a></td>"
        "</tr></table></body></html>"
    )

    # Create message with recent date
    new_msg = MagicMock()
    new_msg.id = "msg_new"
    new_msg.subject = "New"
    new_msg.timestamp = datetime(2024, 6, 15)
    new_msg.body = "text"
    new_msg.messageObj = _make_message_obj(
        '<html><body><table><tr><td><a href="https://doi.org/10.1/new">'
        "Recent Paper That Should Pass Date Filter</a></td>"
        "</tr></table></body></html>"
    )

    mock_thread = MagicMock()
    mock_thread.id = "thread_001"
    mock_thread.messages = [old_msg, new_msg]
    mock_thread.trash = MagicMock()

    mock_ezgmail = MagicMock()
    mock_ezgmail.search.return_value = [mock_thread]

    with patch.dict(sys.modules, {"ezgmail": mock_ezgmail}):
        papers = await source.fetch_papers(since=date(2024, 1, 1))

    # Only the recent paper should pass
    assert len(papers) == 1
    assert "Recent Paper" in papers[0].title


@pytest.mark.asyncio
async def test_gmail_source_fetch_papers_no_results():
    """GmailSource returns empty list when no emails found."""
    source = GmailSource(query="test", source_name="Test")
    source._initialized = True

    mock_ezgmail = MagicMock()
    mock_ezgmail.search.return_value = []

    with patch.dict(sys.modules, {"ezgmail": mock_ezgmail}):
        papers = await source.fetch_papers()

    assert papers == []


@pytest.mark.asyncio
async def test_gmail_source_mark_as_read():
    """GmailSource marks threads as read when configured."""
    source = GmailSource(query="test", source_name="Test", mark_as_read=True)
    source._initialized = True

    mock_message = MagicMock()
    mock_message.id = "msg_001"
    mock_message.subject = "Test"
    mock_message.timestamp = datetime(2024, 6, 15)
    mock_message.body = "text"
    mock_message.messageObj = _make_message_obj(
        "<html><body><p>No articles here</p></body></html>"
    )

    mock_thread = MagicMock()
    mock_thread.id = "thread_001"
    mock_thread.messages = [mock_message]
    mock_thread.trash = MagicMock()

    mock_ezgmail = MagicMock()
    mock_ezgmail.search.return_value = [mock_thread]

    with patch.dict(sys.modules, {"ezgmail": mock_ezgmail}):
        await source.fetch_papers()

    mock_thread.markAsRead.assert_called_once()


@pytest.mark.asyncio
async def test_gmail_source_deduplication():
    """GmailSource deduplicates papers across messages."""
    source = GmailSource(query="test", source_name="Test")
    source._initialized = True

    # Two messages with same paper title
    html = """
    <html><body><table>
      <tr><td><a href="https://doi.org/10.1/dup">
        Duplicate Paper Title Across Emails
      </a></td></tr>
    </table></body></html>
    """
    messages = []
    for i in range(2):
        msg = MagicMock()
        msg.id = f"msg_{i}"
        msg.subject = "Test"
        msg.timestamp = datetime(2024, 6, 15)
        msg.body = "text"
        msg.messageObj = _make_message_obj(html)
        messages.append(msg)

    mock_thread = MagicMock()
    mock_thread.id = "thread_001"
    mock_thread.messages = messages
    mock_thread.trash = MagicMock()

    mock_ezgmail = MagicMock()
    mock_ezgmail.search.return_value = [mock_thread]

    with patch.dict(sys.modules, {"ezgmail": mock_ezgmail}):
        papers = await source.fetch_papers()

    assert len(papers) == 1


# ── _detect_source_from_sender tests ────────────────────────────────


class TestDetectSourceFromSender:
    """Tests for GmailSource._detect_source_from_sender()."""

    def test_detect_known_sender_plain_email(self, monkeypatch):
        """Known plain email address maps to correct source."""
        monkeypatch.setenv(
            "GMAIL_SENDER_MAP_JSON",
            '{"scholaralerts-noreply@google.com": "Google Scholar"}',
        )
        source = GmailSource(query="test")
        msg = MagicMock()
        msg.sender = "scholaralerts-noreply@google.com"
        assert source._detect_source_from_sender(msg) == "Google Scholar"

    def test_detect_known_sender_name_format(self, monkeypatch):
        """Known sender in 'Name <email>' format is detected."""
        monkeypatch.setenv(
            "GMAIL_SENDER_MAP_JSON",
            '{"noreply@nature.com": "Nature"}',
        )
        source = GmailSource(query="test")
        msg = MagicMock()
        msg.sender = "Nature Alerts <noreply@nature.com>"
        assert source._detect_source_from_sender(msg) == "Nature"

    def test_detect_unknown_sender(self):
        """Unknown sender returns None."""
        source = GmailSource(query="test")
        msg = MagicMock()
        msg.sender = "random@example.com"
        assert source._detect_source_from_sender(msg) is None

    def test_detect_no_sender_attribute(self):
        """Message without sender attribute returns None."""
        source = GmailSource(query="test")
        msg = MagicMock(spec=[])
        assert source._detect_source_from_sender(msg) is None


# ── _extract_from_plain_text tests ──────────────────────────────────


class TestExtractFromPlainText:
    """Tests for GmailSource._extract_from_plain_text()."""

    def test_extract_dois_from_plain_text(self):
        """Finds multiple DOIs in originalBody and creates PaperItems."""
        source = GmailSource(query="test")
        msg = MagicMock(spec=[])
        msg.originalBody = (
            "Check this paper: 10.1021/acs.test.2024 and also 10.1038/nature12345"
        )
        msg.id = "msg_pt_1"
        msg.subject = "Papers"

        items = source._extract_from_plain_text(msg, "TestSource")
        assert len(items) == 2
        dois = {item.doi for item in items}
        assert "10.1021/acs.test.2024" in dois
        assert "10.1038/nature12345" in dois
        for item in items:
            assert item.source_type == "email"
            assert item.source == "TestSource"
            assert item.extra["extracted_from"] == "plain_text"

    def test_plain_text_deduplicates_dois(self):
        """Duplicate DOIs in text produce only one PaperItem."""
        source = GmailSource(query="test")
        msg = MagicMock(spec=[])
        msg.originalBody = "10.1021/acs.test.2024 and again 10.1021/acs.test.2024"
        msg.id = "msg_pt_2"
        msg.subject = "Dup"

        items = source._extract_from_plain_text(msg, "Test")
        assert len(items) == 1

    def test_plain_text_fallback_to_body(self):
        """Falls back to message.body when originalBody is absent."""
        source = GmailSource(query="test")
        msg = MagicMock(spec=[])
        msg.body = "See 10.1038/s41586-024-00001-x for details."
        msg.id = "msg_pt_3"
        msg.subject = "Body"

        items = source._extract_from_plain_text(msg, "Test")
        assert len(items) == 1
        assert items[0].doi == "10.1038/s41586-024-00001-x"

    def test_plain_text_no_dois(self):
        """Returns empty list when no DOIs found in text."""
        source = GmailSource(query="test")
        msg = MagicMock(spec=[])
        msg.body = "No DOIs here, just regular text."
        msg.id = "msg_pt_4"
        msg.subject = "Nothing"

        items = source._extract_from_plain_text(msg, "Test")
        assert items == []


# ── GmailSource.__init__ new params tests ───────────────────────────


class TestGmailSourceInitNewParams:
    """Tests for new __init__ parameters."""

    def test_init_default_new_params(self):
        """New params have correct defaults."""
        source = GmailSource(query="test")
        assert source.auto_detect_source is True
        assert source.processed_label is None
        assert source.trash_after_process is True
        assert source.verify_trash_after_process is True
        assert source.verify_trash_limit == 50

    def test_init_custom_new_params(self):
        """New params accept custom values."""
        source = GmailSource(
            query="test",
            auto_detect_source=False,
            processed_label="paper-feed/done",
            trash_after_process=False,
            verify_trash_after_process=False,
            verify_trash_limit=10,
        )
        assert source.auto_detect_source is False
        assert source.processed_label == "paper-feed/done"
        assert source.trash_after_process is False
        assert source.verify_trash_after_process is False
        assert source.verify_trash_limit == 10


# ── GmailSource auto-detect integration tests ──────────────────────


@pytest.mark.asyncio
async def test_fetch_papers_auto_detect_source(monkeypatch):
    """Auto-detect overrides source_name when known sender is found."""
    monkeypatch.setenv(
        "GMAIL_SENDER_MAP_JSON",
        '{"noreply@nature.com": "Nature"}',
    )
    source = GmailSource(
        query="test",
        source_name="Gmail",
        auto_detect_source=True,
    )
    source._initialized = True

    mock_message = MagicMock()
    mock_message.id = "msg_ad_1"
    mock_message.subject = "New articles from Nature"
    mock_message.sender = "Nature Alerts <noreply@nature.com>"
    mock_message.timestamp = datetime(2024, 6, 15, 12, 0, 0)
    mock_message.body = "Plain text"
    mock_message.messageObj = _make_message_obj(SAMPLE_EMAIL_HTML)
    mock_message._attachmentsInfo = None
    mock_message.attachments = []

    mock_thread = MagicMock()
    mock_thread.id = "thread_ad_1"
    mock_thread.messages = [mock_message]
    mock_thread.snippet = "Nature articles"
    mock_thread.trash = MagicMock()

    mock_ezgmail = MagicMock()
    mock_ezgmail.search.return_value = [mock_thread]

    with patch.dict(sys.modules, {"ezgmail": mock_ezgmail}):
        papers = await source.fetch_papers()

    assert len(papers) >= 1
    # Source should be auto-detected as "Nature", not the default "Gmail"
    assert papers[0].source == "Nature"


# ── GmailSource processed_label tests ──────────────────────────────


@pytest.mark.asyncio
async def test_fetch_papers_applies_processed_label():
    """Processed label is applied to message after processing."""
    source = GmailSource(
        query="test",
        source_name="Test",
        processed_label="paper-feed/done",
    )
    source._initialized = True

    mock_message = MagicMock()
    mock_message.id = "msg_pl_1"
    mock_message.subject = "Test"
    mock_message.sender = "test@example.com"
    mock_message.timestamp = datetime(2024, 6, 15)
    mock_message.body = "text"
    mock_message.messageObj = _make_message_obj(
        "<html><body><p>No articles here</p></body></html>"
    )
    mock_message._attachmentsInfo = None
    mock_message.attachments = []
    mock_message.addLabel = MagicMock()

    mock_thread = MagicMock()
    mock_thread.id = "thread_pl_1"
    mock_thread.messages = [mock_message]
    mock_thread.snippet = "test"
    mock_thread.trash = MagicMock()

    mock_ezgmail = MagicMock()
    mock_ezgmail.search.return_value = [mock_thread]

    with patch.dict(sys.modules, {"ezgmail": mock_ezgmail}):
        await source.fetch_papers()

    mock_message.addLabel.assert_called_once_with("paper-feed/done")


# ── GmailSource error recovery tests ───────────────────────────────


@pytest.mark.asyncio
async def test_fetch_papers_marks_unread_on_error():
    """Thread is marked unread when processing fails."""
    source = GmailSource(query="test", source_name="Test")
    source._initialized = True

    mock_thread = MagicMock()
    mock_thread.id = "thread_err_1"
    mock_thread.snippet = "error thread"
    mock_thread.markAsUnread = MagicMock()

    # Make accessing messages raise an error
    type(mock_thread).messages = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("API error"))
    )

    mock_ezgmail = MagicMock()
    mock_ezgmail.search.return_value = [mock_thread]

    with patch.dict(sys.modules, {"ezgmail": mock_ezgmail}):
        papers = await source.fetch_papers()

    # Should recover gracefully and return empty
    assert papers == []
    mock_thread.markAsUnread.assert_called()
