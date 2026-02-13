"""Gmail email source for paper collection."""

import asyncio
import base64
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.config.settings import get_gmail_config
from src.models.responses import PaperItem, PaperSource
from src.sources.gmail_parser import GmailParser
from src.utils.dedup import deduplicate_papers
from src.utils.text import DOI_PATTERN

logger = logging.getLogger(__name__)


def _extract_html_body(message_obj: dict) -> str:
    payload = message_obj.get("payload", {})
    return _find_html_in_payload(payload)


def _find_html_in_payload(payload: dict) -> str:
    mime_type = payload.get("mimeType", "").upper()

    if mime_type == "TEXT/HTML":
        body_data = payload.get("body", {}).get("data", "")
        if body_data:
            try:
                return base64.urlsafe_b64decode(body_data).decode("utf-8")
            except Exception:
                return ""

    parts = payload.get("parts", [])
    for part in parts:
        html = _find_html_in_payload(part)
        if html:
            return html

    return ""


def _extract_sender_email(sender: Optional[str]) -> Optional[str]:
    if not sender or not isinstance(sender, str):
        return None
    match = re.search(r"<([^>]+)>", sender)
    email_addr = match.group(1).lower() if match else sender.lower().strip()
    return email_addr or None


def _parse_sender_filter(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    parts = re.split(r"[;,]", raw)
    return [p.strip().lower() for p in parts if p.strip()]


def _parse_sender_map(raw: Optional[str]) -> Dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("GMAIL_SENDER_MAP_JSON is invalid JSON; ignoring.")
        return {}
    if not isinstance(data, dict):
        logger.warning("GMAIL_SENDER_MAP_JSON must be a JSON object; ignoring.")
        return {}
    cleaned: Dict[str, str] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
            cleaned[k.strip().lower()] = v.strip()
    return cleaned


class GmailSource(PaperSource):
    """Paper source for Gmail email alerts."""

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
        trash_after_process: Optional[bool] = None,
        verify_trash_after_process: Optional[bool] = None,
        verify_trash_limit: Optional[int] = None,
    ):
        config = get_gmail_config()

        self.token_file = config.get("token_file", "feeds/token.json")
        self.credentials_file = config.get("credentials_file", "feeds/credentials.json")

        token_json = config.get("token_json")
        credentials_json = config.get("credentials_json")
        token_file_exists = Path(self.token_file).exists()
        credentials_file_exists = Path(self.credentials_file).exists()

        if not token_json and not token_file_exists:
            raise ValueError(
                "GMAIL_TOKEN_JSON is not set and token file not found. "
                f"Expected token file at: {self.token_file}"
            )
        if not credentials_json and not credentials_file_exists:
            raise ValueError(
                "GMAIL_CREDENTIALS_JSON is not set and credentials file not found. "
                f"Expected credentials file at: {self.credentials_file}"
            )

        self.sender_filter = _parse_sender_filter(config.get("sender_filter"))
        self.sender_map = _parse_sender_map(config.get("sender_map_json"))
        self.query = query or config.get("query") or self._default_query()
        self.source_name = source_name
        self.max_results = (
            max_results if max_results is not None else config.get("max_results", 50)
        )
        self.mark_as_read = (
            mark_as_read
            if mark_as_read is not None
            else config.get("mark_as_read", False)
        )
        self.auto_detect_source = auto_detect_source
        self.processed_label = processed_label or config.get("processed_label")
        self.trash_after_process = (
            trash_after_process
            if trash_after_process is not None
            else config.get("trash_after_process", True)
        )
        self.verify_trash_after_process = (
            verify_trash_after_process
            if verify_trash_after_process is not None
            else config.get("verify_trash_after_process", True)
        )
        self.verify_trash_limit = (
            verify_trash_limit
            if verify_trash_limit is not None
            else config.get("verify_trash_limit", 50)
        )
        self.parser = GmailParser()
        self._initialized = False

    def _ensure_init(self) -> None:
        if self._initialized:
            return

        try:
            import ezgmail
        except ImportError:
            raise ImportError(
                "EZGmail is required for GmailSource. "
                "Install it with: pip install feedder-mcp[gmail]"
            )

        self._write_json_configs()

        ezgmail.init(
            tokenFile=self.token_file,
            credentialsFile=self.credentials_file,
        )
        self._initialized = True

        email_addr = getattr(ezgmail, "EMAIL_ADDRESS", None)
        if email_addr:
            logger.info(f"GmailSource authenticated as {email_addr}")

    def _write_json_configs(self) -> None:
        config = get_gmail_config()

        token_json = config.get("token_json")
        if token_json and token_json.strip():
            token_json = self._normalize_token_json(token_json.strip())
            token_path = Path(self.token_file)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(token_json.strip(), encoding="utf-8")
            logger.debug("Wrote GMAIL_TOKEN_JSON → %s", token_path)

        credentials_json = config.get("credentials_json")
        if credentials_json and credentials_json.strip():
            cred_path = Path(self.credentials_file)
            cred_path.parent.mkdir(parents=True, exist_ok=True)
            cred_path.write_text(credentials_json.strip(), encoding="utf-8")
            logger.debug("Wrote GMAIL_CREDENTIALS_JSON → %s", cred_path)

    @staticmethod
    def _normalize_token_json(token_json: str) -> str:
        try:
            data = json.loads(token_json)
        except json.JSONDecodeError:
            logger.warning("GMAIL_TOKEN_JSON is not valid JSON; using as-is.")
            return token_json

        if isinstance(data, dict) and data.get("_module") and data.get("_class"):
            return token_json

        access_token = data.get("access_token") or data.get("token")
        if not access_token:
            logger.warning("GMAIL_TOKEN_JSON missing access token; using as-is.")
            return token_json

        token_expiry = data.get("token_expiry") or data.get("expiry")

        normalized = {
            "access_token": access_token,
            "client_id": data.get("client_id"),
            "client_secret": data.get("client_secret"),
            "refresh_token": data.get("refresh_token"),
            "token_expiry": token_expiry,
            "token_uri": data.get("token_uri"),
            "user_agent": "feedder-mcp/2.0",
            "revoke_uri": data.get("revoke_uri"),
            "id_token": data.get("id_token"),
            "token_response": data.get("token_response"),
            "scopes": data.get("scopes"),
            "token_info_uri": data.get("token_info_uri"),
            "invalid": bool(data.get("invalid", False)),
            "_module": "oauth2client.client",
            "_class": "OAuth2Credentials",
        }

        return json.dumps(normalized, ensure_ascii=False)

    def _default_query(self) -> str:
        senders = self.sender_filter or sorted(self.sender_map.keys())
        if not senders:
            return "in:inbox"
        sender_query = " OR ".join(f"from:{addr}" for addr in senders)
        return f"in:inbox ({sender_query})"

    async def fetch_papers(
        self, limit: Optional[int] = None, since: Optional[date] = None
    ) -> List[PaperItem]:
        import ezgmail

        papers: List[PaperItem] = []

        try:
            await asyncio.to_thread(self._ensure_init)

            max_results = self.max_results
            threads: list = await asyncio.to_thread(
                ezgmail.search, self.query, max_results
            )

            if not threads:
                logger.info(f"No emails found for query: {self.query}")
                return []

            logger.info(f"Found {len(threads)} email threads for query: {self.query}")

            for thread in threads:
                try:
                    marked_as_read = False
                    snippet = getattr(thread, "snippet", None)
                    if snippet:
                        logger.debug(
                            f"Processing thread {thread.id}: {snippet[:80]}..."
                        )

                    messages = await asyncio.to_thread(lambda t=thread: t.messages)

                    for message in messages:
                        if since and hasattr(message, "timestamp"):
                            msg_date = message.timestamp
                            if isinstance(msg_date, datetime):
                                msg_date = msg_date.date()
                            if msg_date < since:
                                continue

                        if self.sender_filter:
                            sender_email = _extract_sender_email(
                                getattr(message, "sender", None)
                            )
                            if not sender_email or sender_email not in self.sender_filter:
                                continue

                        effective_source = self.source_name
                        if self.auto_detect_source:
                            detected = self._detect_source_from_sender(message)
                            if detected:
                                effective_source = detected

                        html_body = _extract_html_body(message.messageObj)

                        if html_body:
                            email_subject = getattr(message, "subject", "")
                            items = self.parser.parse(
                                html_content=html_body,
                                source_name=effective_source,
                                email_id=message.id,
                                email_subject=email_subject,
                            )
                        else:
                            items = self._extract_from_plain_text(
                                message, effective_source
                            )

                        papers.extend(items)

                        if limit and len(papers) >= limit:
                            papers = papers[:limit]
                            break

                    if self.mark_as_read:
                        await asyncio.to_thread(thread.markAsRead)
                        marked_as_read = True

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

                    if self.trash_after_process:
                        try:
                            if hasattr(thread, "markAsRead") and not marked_as_read:
                                await asyncio.to_thread(thread.markAsRead)
                                marked_as_read = True
                        except Exception as read_err:
                            logger.warning(
                                f"Failed to mark thread {thread.id} as read before trash: {read_err}"
                            )
                        try:
                            await asyncio.to_thread(thread.trash)
                        except Exception as trash_err:
                            logger.warning(
                                f"Failed to trash thread {thread.id}: {trash_err}"
                            )

                except Exception as e:
                    logger.error(
                        f"Error processing thread {thread.id}: {e}",
                        exc_info=True,
                    )

                    try:
                        if hasattr(thread, "markAsUnread"):
                            await asyncio.to_thread(thread.markAsUnread)
                            logger.debug(
                                f"Marked thread {thread.id} as unread after error"
                            )
                    except Exception:
                        pass

                    continue

                if limit and len(papers) >= limit:
                    break

            papers, dedup_stats = deduplicate_papers(papers)
            logger.info(
                "Gmail fetch dedup stats: input=%d, unique=%d, dropped=%d, by_key=%s",
                dedup_stats["input_count"],
                dedup_stats["unique_count"],
                dedup_stats["dropped_count"],
                dedup_stats["duplicates_by_key"],
            )

            logger.info(
                f"Extracted {len(papers)} unique papers from "
                f"{len(threads)} email threads"
            )

            if self.verify_trash_after_process:
                try:
                    verify_query = self._build_trash_query(self.query)
                    verify_threads: list = await asyncio.to_thread(
                        ezgmail.search, verify_query, self.verify_trash_limit
                    )
                    logger.info(
                        "Trash verification: %d threads matched query: %s",
                        len(verify_threads),
                        verify_query,
                    )
                except Exception as verify_err:
                    logger.warning(
                        "Trash verification failed: %s",
                        verify_err,
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
    def _build_trash_query(query: str) -> str:
        if "in:trash" in query:
            return query
        if "in:inbox" in query:
            return query.replace("in:inbox", "in:trash")
        return f"in:trash {query}".strip()

    def _detect_source_from_sender(self, message: object) -> Optional[str]:
        sender = getattr(message, "sender", None)
        email_addr = _extract_sender_email(sender)
        if not email_addr:
            return None

        if email_addr in self.sender_map:
            return self.sender_map[email_addr]

        if email_addr in self.sender_filter:
            local = email_addr.split("@")[0].replace("-", " ").replace("_", " ")
            return local.title() if local else None

        return None

    def _extract_from_plain_text(
        self, message: object, source_name: str
    ) -> List[PaperItem]:
        text = getattr(message, "originalBody", None)
        if not text:
            text = getattr(message, "body", None)
        if not text:
            logger.debug(f"No body content for message {getattr(message, 'id', '?')}")
            return []

        items: List[PaperItem] = []
        email_id = getattr(message, "id", "")
        email_subject = getattr(message, "subject", "")

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
                    extra={
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
        unique, _ = deduplicate_papers(papers)
        return unique

