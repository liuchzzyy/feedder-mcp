"""Gmail email source for paper collection.

Uses EZGmail to search and fetch emails from Gmail (Google Scholar alerts,
journal TOC notifications, etc.), then parses HTML content to extract
academic paper information.

Requires the 'gmail' optional dependency: pip install paper-feed[gmail]
"""

import asyncio
import base64
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from paper_feed.core.base import PaperSource
from paper_feed.core.config import get_gmail_config
from paper_feed.core.models import PaperItem
from paper_feed.sources.gmail_parser import GmailParser
from paper_feed.utils.text import DOI_PATTERN

logger = logging.getLogger(__name__)


def _extract_html_body(message_obj: dict) -> str:
    """Extract HTML body from a raw Gmail API message object.

    EZGmail only extracts plain text body. This function walks the message
    payload to find TEXT/HTML parts for rich email parsing.

    Args:
        message_obj: Raw message dict from Gmail API (GmailMessage.messageObj).

    Returns:
        HTML body string, or empty string if not found.
    """
    payload = message_obj.get("payload", {})
    return _find_html_in_payload(payload)


def _find_html_in_payload(payload: dict) -> str:
    """Recursively search payload for HTML content.

    Args:
        payload: Gmail API message payload dict.

    Returns:
        Decoded HTML string, or empty string if not found.
    """
    mime_type = payload.get("mimeType", "").upper()

    # Direct HTML part
    if mime_type == "TEXT/HTML":
        body_data = payload.get("body", {}).get("data", "")
        if body_data:
            try:
                return base64.urlsafe_b64decode(body_data).decode("utf-8")
            except Exception:
                return ""

    # Multipart: recurse into parts
    parts = payload.get("parts", [])
    for part in parts:
        html = _find_html_in_payload(part)
        if html:
            return html

    return ""


# Known sender → source_name mapping for auto-detection
_SENDER_SOURCE_MAP: Dict[str, str] = {
    "scholaralerts-noreply@google.com": "Google Scholar",
    "scholar-alerts@google.com": "Google Scholar",
    "noreply@nature.com": "Nature",
    "alerts@nature.com": "Nature",
    "noreply@science.org": "Science",
    "noreply@cell.com": "Cell",
    "noreply@acs.org": "ACS",
    "noreply@wiley.com": "Wiley",
    "noreply@springer.com": "Springer",
    "noreply@elsevier.com": "Elsevier",
    "noreply@pnas.org": "PNAS",
    "noreply@biorxiv.org": "bioRxiv",
    "noreply@medrxiv.org": "medRxiv",
}


class GmailSource(PaperSource):
    """Paper source for Gmail email alerts.

    Fetches papers from Gmail by searching for emails matching a query
    (e.g., Google Scholar alerts, journal TOC emails) and parsing the
    HTML content to extract paper information.

    Uses EZGmail for Gmail API access. Requires OAuth2 credentials.

    Attributes:
        source_name: Name of this source (e.g., "Google Scholar").
        source_type: Always "email" for this class.
        query: Gmail search query string.
        max_results: Maximum number of email threads to fetch.
        auto_detect_source: Whether to infer source_name from sender address.
        processed_label: Optional Gmail label to apply to processed threads.
    """

    source_name: str = "Gmail"
    source_type: str = "email"

    def __init__(
        self,
        query: Optional[str] = None,
        source_name: str = "Gmail",
        max_results: Optional[int] = None,
        mark_as_read: Optional[bool] = None,
        auto_detect_source: bool = True,
        processed_label: Optional[str] = None,
    ):
        """Initialize Gmail source.

        Args:
            query: Gmail search query (same syntax as Gmail search box).
                Examples:
                - "from:scholaralerts-noreply@google.com"
                - "subject:new articles"
                - "label:UNREAD from:scholar"
                Defaults to GMAIL_QUERY env var or "label:UNREAD".
            source_name: Source name for PaperItem objects.
            max_results: Maximum email threads to process.
                Defaults to GMAIL_MAX_RESULTS env var or 50.
            mark_as_read: Whether to mark processed emails as read.
                Defaults to GMAIL_MARK_AS_READ env var or False.
            auto_detect_source: Whether to auto-detect source_name from
                the sender's email address (overrides source_name per-message
                when a known sender is detected).
            processed_label: Optional Gmail label name to apply to processed
                threads (e.g. "paper-feed/processed"). None = no labelling.
                Defaults to GMAIL_PROCESSED_LABEL env var or None.

        Raises:
            ValueError: If GMAIL_TOKEN_JSON or GMAIL_CREDENTIALS_JSON
                environment variables are not set.
        """
        config = get_gmail_config()

        # Validate that inline JSON credentials are provided
        if not config.get("token_json"):
            raise ValueError(
                "GMAIL_TOKEN_JSON environment variable must be set. "
                "This is required for OAuth2 authentication with Gmail."
            )
        if not config.get("credentials_json"):
            raise ValueError(
                "GMAIL_CREDENTIALS_JSON environment variable must be set. "
                "This is required for OAuth2 authentication with Gmail."
            )

        self.query = query or config.get("query", "label:UNREAD")
        self.source_name = source_name
        self.max_results = (
            max_results if max_results is not None else config.get("max_results", 50)
        )
        # Fixed file paths for EZGmail compatibility
        self.token_file = "token.json"
        self.credentials_file = "credentials.json"
        self.mark_as_read = (
            mark_as_read
            if mark_as_read is not None
            else config.get("mark_as_read", False)
        )
        self.auto_detect_source = auto_detect_source
        self.processed_label = processed_label or config.get("processed_label")
        self.parser = GmailParser()
        self._initialized = False

    def _ensure_init(self) -> None:
        """Ensure EZGmail is initialized. Called lazily on first use.

        Writes GMAIL_TOKEN_JSON / GMAIL_CREDENTIALS_JSON env vars to
        fixed file paths (token.json / credentials.json) for EZGmail
        compatibility. This allows env-only deployment without
        pre-existing OAuth2 files on disk.

        Raises:
            ImportError: If ezgmail is not installed.
            Exception: If OAuth2 authentication fails.
        """
        if self._initialized:
            return

        try:
            import ezgmail
        except ImportError:
            raise ImportError(
                "EZGmail is required for GmailSource. "
                "Install it with: pip install paper-feed[gmail]"
            )

        # Write inline JSON to files if provided
        self._write_json_configs()

        ezgmail.init(
            tokenFile=self.token_file,
            credentialsFile=self.credentials_file,
        )
        self._initialized = True

        # Log authenticated account for debugging
        email_addr = getattr(ezgmail, "EMAIL_ADDRESS", None)
        if email_addr:
            logger.info(f"GmailSource authenticated as {email_addr}")

    def _write_json_configs(self) -> None:
        """Write inline JSON env vars to fixed file paths for EZGmail.

        Writes GMAIL_TOKEN_JSON to token.json and GMAIL_CREDENTIALS_JSON
        to credentials.json for EZGmail compatibility.
        """
        config = get_gmail_config()

        token_json = config.get("token_json")
        if token_json and token_json.strip():
            token_path = Path(self.token_file)
            token_path.write_text(token_json.strip(), encoding="utf-8")
            logger.debug("Wrote GMAIL_TOKEN_JSON → %s", token_path)

        credentials_json = config.get("credentials_json")
        if credentials_json and credentials_json.strip():
            cred_path = Path(self.credentials_file)
            cred_path.write_text(credentials_json.strip(), encoding="utf-8")
            logger.debug("Wrote GMAIL_CREDENTIALS_JSON → %s", cred_path)

    async def fetch_papers(
        self, limit: Optional[int] = None, since: Optional[date] = None
    ) -> List[PaperItem]:
        """Fetch papers from Gmail email alerts.

        Searches Gmail for matching emails, extracts HTML bodies, and
        parses them to find paper items. Falls back to plain-text body
        when no HTML is available. Also extracts attachment info for
        PDF discovery.

        Args:
            limit: Maximum number of papers to return (None = no limit).
            since: Only return papers from emails after this date (None = no filter).

        Returns:
            List of PaperItem objects extracted from email content.
        """
        import ezgmail

        papers: List[PaperItem] = []

        try:
            # Initialize EZGmail (lazy, synchronous)
            await asyncio.to_thread(self._ensure_init)

            # Search for emails (synchronous call wrapped in thread)
            max_results = self.max_results
            threads: list = await asyncio.to_thread(
                ezgmail.search, self.query, max_results
            )

            if not threads:
                logger.info(f"No emails found for query: {self.query}")
                return []

            logger.info(f"Found {len(threads)} email threads for query: {self.query}")

            # Process each thread
            for thread in threads:
                try:
                    # Log snippet for debugging context
                    snippet = getattr(thread, "snippet", None)
                    if snippet:
                        logger.debug(
                            f"Processing thread {thread.id}: {snippet[:80]}..."
                        )

                    # Access messages (lazy-loaded, triggers API call)
                    messages = await asyncio.to_thread(lambda t=thread: t.messages)

                    for message in messages:
                        # Apply date filter on email timestamp
                        if since and hasattr(message, "timestamp"):
                            msg_date = message.timestamp
                            if isinstance(msg_date, datetime):
                                msg_date = msg_date.date()
                            if msg_date < since:
                                continue

                        # Auto-detect source name from sender
                        effective_source = self.source_name
                        if self.auto_detect_source:
                            detected = self._detect_source_from_sender(message)
                            if detected:
                                effective_source = detected

                        # Extract HTML body from raw message object
                        html_body = _extract_html_body(message.messageObj)

                        if html_body:
                            # Parse HTML to extract paper items
                            email_subject = getattr(message, "subject", "")
                            items = self.parser.parse(
                                html_content=html_body,
                                source_name=effective_source,
                                email_id=message.id,
                                email_subject=email_subject,
                            )
                        else:
                            # Fallback: try originalBody or body for link extraction
                            items = self._extract_from_plain_text(
                                message, effective_source
                            )

                        # Enrich items with attachment info (PDF discovery)
                        attachment_urls = self._extract_attachment_info(message)
                        if attachment_urls:
                            for item in items:
                                if not item.pdf_url and attachment_urls:
                                    item.pdf_url = attachment_urls[0]
                                # Store all attachment info in metadata
                                if "attachments" not in item.metadata:
                                    item.metadata["attachments"] = attachment_urls

                        papers.extend(items)

                        # Apply limit
                        if limit and len(papers) >= limit:
                            papers = papers[:limit]
                            break

                    # Mark as read if configured
                    if self.mark_as_read:
                        await asyncio.to_thread(thread.markAsRead)

                    # Apply processed label if configured
                    if self.processed_label:
                        try:
                            first_msg = messages[0] if messages else None
                            if first_msg and hasattr(first_msg, "addLabel"):
                                await asyncio.to_thread(
                                    first_msg.addLabel, self.processed_label
                                )
                        except Exception as label_err:
                            logger.warning(
                                f"Failed to apply label "
                                f"'{self.processed_label}': {label_err}"
                            )

                except Exception as e:
                    logger.error(
                        f"Error processing thread {thread.id}: {e}",
                        exc_info=True,
                    )

                    # Mark as unread on failure so it can be retried
                    try:
                        if hasattr(thread, "markAsUnread"):
                            await asyncio.to_thread(thread.markAsUnread)
                            logger.debug(
                                f"Marked thread {thread.id} as unread after error"
                            )
                    except Exception:
                        pass  # Best-effort recovery

                    continue

                # Check limit after each thread
                if limit and len(papers) >= limit:
                    break

            # Deduplicate across all emails by (title, doi)
            papers = self._deduplicate(papers)

            logger.info(
                f"Extracted {len(papers)} unique papers from "
                f"{len(threads)} email threads"
            )

        except ImportError:
            raise
        except Exception as e:
            logger.error(
                f"Error fetching emails for query '{self.query}': {e}",
                exc_info=True,
            )

        return papers

    @staticmethod
    def _detect_source_from_sender(message: object) -> Optional[str]:
        """Detect source name from the message sender address.

        Checks the sender against a map of known academic alert senders.

        Args:
            message: EZGmail message object.

        Returns:
            Detected source name, or None if sender is unknown.
        """
        sender = getattr(message, "sender", None)
        if not sender or not isinstance(sender, str):
            return None

        # Extract email address from "Name <email>" format
        match = re.search(r"<([^>]+)>", sender)
        email_addr = match.group(1).lower() if match else sender.lower().strip()

        return _SENDER_SOURCE_MAP.get(email_addr)

    @staticmethod
    def _extract_attachment_info(message: object) -> List[str]:
        """Extract PDF attachment filenames from a message.

        Uses ezgmail's ``_attachmentsInfo`` to discover PDF attachments
        without downloading them. Returns filenames that can serve as
        indicators that a PDF is available.

        Args:
            message: EZGmail message object.

        Returns:
            List of PDF attachment filename strings.
        """
        pdf_names: List[str] = []

        # Try _attachmentsInfo (list of dicts with 'filename', 'id', 'size')
        attachments_info = getattr(message, "_attachmentsInfo", None)
        if attachments_info and isinstance(attachments_info, list):
            for att in attachments_info:
                filename = ""
                if isinstance(att, dict):
                    filename = att.get("filename", "")
                elif hasattr(att, "filename"):
                    filename = getattr(att, "filename", "")
                if filename and filename.lower().endswith(".pdf"):
                    pdf_names.append(filename)

        # Fallback: try attachments property (list of filename strings)
        if not pdf_names:
            attachments = getattr(message, "attachments", None)
            if attachments and isinstance(attachments, list):
                for att in attachments:
                    if isinstance(att, str) and att.lower().endswith(".pdf"):
                        pdf_names.append(att)

        return pdf_names

    def _extract_from_plain_text(
        self, message: object, source_name: str
    ) -> List[PaperItem]:
        """Extract paper items from plain text body as a fallback.

        When HTML parsing is unavailable, scans the plain text body
        (preferring ``originalBody`` over ``body``) for DOI links and
        URLs pointing to known publisher domains.

        Args:
            message: EZGmail message object.
            source_name: Source name for PaperItem objects.

        Returns:
            List of PaperItem objects found in the text.
        """
        # Prefer originalBody (full text without quoted parts removed)
        text = getattr(message, "originalBody", None)
        if not text:
            text = getattr(message, "body", None)
        if not text:
            logger.debug(f"No body content for message {getattr(message, 'id', '?')}")
            return []

        items: List[PaperItem] = []
        email_id = getattr(message, "id", "")
        email_subject = getattr(message, "subject", "")

        # Find DOIs in plain text
        doi_matches = DOI_PATTERN.findall(text)
        seen_dois: set = set()
        for doi in doi_matches:
            if doi.lower() in seen_dois:
                continue
            seen_dois.add(doi.lower())
            items.append(
                PaperItem(
                    title=f"Paper (DOI: {doi})",
                    authors=[],
                    abstract="",
                    published_date=None,
                    doi=doi,
                    url=f"https://doi.org/{doi}",
                    pdf_url=None,
                    source=source_name,
                    source_id=email_id or None,
                    source_type="email",
                    metadata={
                        "email_id": email_id,
                        "email_subject": email_subject,
                        "extracted_from": "plain_text",
                    },
                )
            )

        if not items:
            logger.debug(
                f"No HTML body for message {email_id}, "
                f"plain text fallback found no DOIs"
            )

        return items

    @staticmethod
    def _deduplicate(papers: List[PaperItem]) -> List[PaperItem]:
        """Deduplicate papers by title (case-insensitive).

        Args:
            papers: List of PaperItem objects.

        Returns:
            Deduplicated list preserving first occurrence order.
        """
        seen: set = set()
        unique: List[PaperItem] = []
        for paper in papers:
            key = paper.title.lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(paper)
        return unique
