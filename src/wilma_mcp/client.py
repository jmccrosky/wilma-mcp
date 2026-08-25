"""Wilma HTTP client for authentication and API requests."""

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qsl, urlsplit

import httpx

from .models import (
    DaySchedule,
    Lesson,
    Message,
    MessageSummary,
    Recipient,
)


class WilmaAuthError(Exception):
    """Raised when authentication fails."""

    pass


class WilmaAPIError(Exception):
    """Raised when an API request fails."""

    pass


# Friendly labels for Wilma recipient "types" (the r_<type> field key).
_RECIPIENT_ROLE_LABELS = {
    "guardian": "Guardian",
    "personnel": "Staff",
    "teacher": "Teacher",
    "ownteachers": "Teachers",
    "schoolteacher": "Teacher",
    "schoolpersonnel": "Staff",
    "student": "Student",
    "class": "Class",
    "group": "Group",
    "classguardian": "Class guardians",
    "groupguardian": "Group guardians",
}


class WilmaClient:
    """HTTP client for interacting with Wilma."""

    def __init__(self, base_url: str, username: str, password: str):
        """Initialize the Wilma client.

        Args:
            base_url: Base URL of the Wilma instance (e.g., https://school.inschool.fi)
            username: Wilma username
            password: Wilma password
        """
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._client: Optional[httpx.AsyncClient] = None
        self._session_id: Optional[str] = None
        self._user_prefix: Optional[str] = None  # e.g., "/!0411876"

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                follow_redirects=True,
                timeout=30.0,
                headers={
                    "User-Agent": "WilmaMCP/0.1.0",
                    "Accept": "application/json, text/html",
                },
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def login(self) -> None:
        """Authenticate with Wilma and establish a session.

        Raises:
            WilmaAuthError: If authentication fails
        """
        client = await self._get_client()

        # Step 1: Get SessionID from index_json endpoint
        try:
            index_response = await client.get("/index_json")
            index_response.raise_for_status()
            index_data = index_response.json()
            session_token = index_data.get("SessionID")
            if not session_token:
                raise WilmaAuthError("No SessionID received from index_json")
        except httpx.HTTPError as e:
            raise WilmaAuthError(f"Failed to get session token: {e}")
        except ValueError as e:
            raise WilmaAuthError(f"Failed to parse index_json response: {e}")

        # Step 2: Perform login with the session token
        login_data = {
            "Login": self.username,
            "Password": self.password,
            "SESSIONID": session_token,
        }

        try:
            response = await client.post(
                "/login",
                data=login_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as e:
            raise WilmaAuthError(f"Login request failed: {e}")

        # Check for Wilma2SID cookie (indicates successful login)
        self._session_id = client.cookies.get("Wilma2SID")
        if not self._session_id:
            raise WilmaAuthError("Login failed - no session cookie received")

        # Extract user prefix from redirect URL (e.g., /!0411876)
        final_url = str(response.url)
        prefix_match = re.search(r"(/!\d+)", final_url)
        if prefix_match:
            self._user_prefix = prefix_match.group(1)
        else:
            # Try to find it in the page content
            prefix_match = re.search(r'href="(/!\d+)', response.text)
            if prefix_match:
                self._user_prefix = prefix_match.group(1)
            else:
                raise WilmaAuthError("Could not determine user prefix after login")

    async def _ensure_authenticated(self) -> None:
        """Ensure we have a valid session, re-authenticating if needed."""
        if self._session_id is None or self._user_prefix is None:
            await self.login()

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an authenticated request to Wilma.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path (will be prefixed with user prefix if not absolute)
            **kwargs: Additional arguments for httpx

        Returns:
            httpx.Response object

        Raises:
            WilmaAPIError: If the request fails
        """
        await self._ensure_authenticated()
        client = await self._get_client()

        # Prepend user prefix if path doesn't start with /! or /preferences
        if not path.startswith("/!") and not path.startswith("/preferences"):
            path = f"{self._user_prefix}{path}"

        try:
            response = await client.request(method, path, **kwargs)

            # Check if session expired (redirected to login)
            if "/login" in str(response.url).lower():
                # Re-authenticate and retry
                self._session_id = None
                await self.login()
                response = await client.request(method, path, **kwargs)

            return response

        except httpx.HTTPError as e:
            raise WilmaAPIError(f"Request to {path} failed: {e}")

    async def get_schedule(self, target_date: Optional[date] = None) -> DaySchedule:
        """Get the schedule for a specific date.

        Args:
            target_date: Date to get schedule for (defaults to today)

        Returns:
            DaySchedule object with lessons for the day
        """
        if target_date is None:
            target_date = date.today()

        # Format date for Wilma
        date_str = target_date.strftime("%d.%m.%Y")

        # Get schedule page - contains embedded JavaScript with eventsJSON
        response = await self._request("GET", f"/schedule?date={date_str}")

        return self._parse_schedule_from_html(response.text, target_date)

    def _parse_schedule_from_html(self, html: str, target_date: date) -> DaySchedule:
        """Parse schedule from HTML with embedded eventsJSON."""
        lessons = []

        # Extract Events array directly - it's already valid JSON
        # The array starts after "Events : [" and we need to find the matching ]
        events_start = html.find("Events : [")
        if events_start == -1:
            events_start = html.find("Events: [")
        if events_start == -1:
            return DaySchedule(date=target_date, lessons=[])

        # Find the start of the array
        array_start = html.find("[", events_start)
        if array_start == -1:
            return DaySchedule(date=target_date, lessons=[])

        # Find matching closing bracket by counting brackets
        bracket_count = 0
        array_end = -1
        for i in range(array_start, len(html)):
            if html[i] == "[":
                bracket_count += 1
            elif html[i] == "]":
                bracket_count -= 1
                if bracket_count == 0:
                    array_end = i + 1
                    break

        if array_end == -1:
            return DaySchedule(date=target_date, lessons=[])

        events_str = html[array_start:array_end]

        try:
            events = json.loads(events_str)
            target_date_str = target_date.strftime("%d.%m.%Y")

            for event in events:
                # Filter by date
                event_date = event.get("Date", "")
                if event_date != target_date_str:
                    continue

                # Convert start/end from minutes since midnight to HH:MM
                start_mins = event.get("Start", 0)
                end_mins = event.get("End", 0)
                start_time = f"{start_mins // 60:02d}:{start_mins % 60:02d}"
                end_time = f"{end_mins // 60:02d}:{end_mins % 60:02d}"

                # Get subject from Text field (it's a dict with index keys)
                text_dict = event.get("Text", {})
                subject = text_dict.get("0", "") if isinstance(text_dict, dict) else str(text_dict)

                # Get additional info from LongText
                long_text_dict = event.get("LongText", {})
                notes = long_text_dict.get("0", "") if isinstance(long_text_dict, dict) else None

                # Get teacher info from Opet
                opet_dict = event.get("Opet", {})
                teacher = opet_dict.get("0", "") if isinstance(opet_dict, dict) else None
                if teacher:
                    # Clean up teacher string (remove "O: " prefix)
                    teacher = re.sub(r"^O:\s*", "", teacher)

                lesson = Lesson(
                    start_time=start_time,
                    end_time=end_time,
                    subject=subject,
                    teacher=teacher,
                    notes=notes,
                )
                lessons.append(lesson)

        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        # Sort lessons by start time
        lessons.sort(key=lambda x: x.start_time)

        return DaySchedule(date=target_date, lessons=lessons)

    async def get_week_schedule(
        self, start_date: Optional[date] = None
    ) -> list[DaySchedule]:
        """Get the schedule for a full week.

        Args:
            start_date: Start date of the week (defaults to today)

        Returns:
            List of DaySchedule objects for each day
        """
        if start_date is None:
            start_date = date.today()

        # Get schedule page - it shows a full week by default
        date_str = start_date.strftime("%d.%m.%Y")
        response = await self._request("GET", f"/schedule?date={date_str}")

        return self._parse_week_schedule_from_html(response.text, start_date)

    def _parse_week_schedule_from_html(
        self, html: str, start_date: date
    ) -> list[DaySchedule]:
        """Parse week schedule from HTML with embedded eventsJSON."""
        # Extract DayCount
        day_count_match = re.search(r"DayCount\s*:\s*(\d+)", html)
        day_count = int(day_count_match.group(1)) if day_count_match else 5

        # Extract Events array directly
        events_start = html.find("Events : [")
        if events_start == -1:
            events_start = html.find("Events: [")
        if events_start == -1:
            return [DaySchedule(date=start_date + timedelta(days=i), lessons=[]) for i in range(day_count)]

        array_start = html.find("[", events_start)
        if array_start == -1:
            return [DaySchedule(date=start_date + timedelta(days=i), lessons=[]) for i in range(day_count)]

        # Find matching closing bracket
        bracket_count = 0
        array_end = -1
        for i in range(array_start, len(html)):
            if html[i] == "[":
                bracket_count += 1
            elif html[i] == "]":
                bracket_count -= 1
                if bracket_count == 0:
                    array_end = i + 1
                    break

        if array_end == -1:
            return [DaySchedule(date=start_date + timedelta(days=i), lessons=[]) for i in range(day_count)]

        events_str = html[array_start:array_end]

        try:
            events = json.loads(events_str)

            # Group events by date
            schedules_by_date: dict[str, list[Lesson]] = {}

            for event in events:
                event_date = event.get("Date", "")
                if not event_date:
                    continue

                start_mins = event.get("Start", 0)
                end_mins = event.get("End", 0)
                start_time = f"{start_mins // 60:02d}:{start_mins % 60:02d}"
                end_time = f"{end_mins // 60:02d}:{end_mins % 60:02d}"

                text_dict = event.get("Text", {})
                subject = text_dict.get("0", "") if isinstance(text_dict, dict) else str(text_dict)

                long_text_dict = event.get("LongText", {})
                notes = long_text_dict.get("0", "") if isinstance(long_text_dict, dict) else None

                opet_dict = event.get("Opet", {})
                teacher = opet_dict.get("0", "") if isinstance(opet_dict, dict) else None
                if teacher:
                    teacher = re.sub(r"^O:\s*", "", teacher)

                lesson = Lesson(
                    start_time=start_time,
                    end_time=end_time,
                    subject=subject,
                    teacher=teacher,
                    notes=notes,
                )

                if event_date not in schedules_by_date:
                    schedules_by_date[event_date] = []
                schedules_by_date[event_date].append(lesson)

            # Build list of DaySchedules
            schedules = []
            for i in range(day_count):
                day = start_date + timedelta(days=i)
                day_str = day.strftime("%d.%m.%Y")
                lessons = schedules_by_date.get(day_str, [])
                lessons.sort(key=lambda x: x.start_time)
                schedules.append(DaySchedule(date=day, lessons=lessons))

            return schedules

        except (json.JSONDecodeError, KeyError, TypeError):
            return [DaySchedule(date=start_date + timedelta(days=i), lessons=[]) for i in range(5)]

    async def get_messages(
        self, folder: str = "inbox", limit: int = 20
    ) -> list[MessageSummary]:
        """Get list of messages from a folder.

        Args:
            folder: Folder name (inbox, sent, archive, drafts)
            limit: Maximum number of messages to return

        Returns:
            List of MessageSummary objects
        """
        # Each folder is a distinct list endpoint. Wilma builds these as
        # /messages/list[/<box>] (the inbox has no box suffix); "sent" maps to
        # Wilma's "outbox" box.
        folder_paths = {
            "inbox": "/messages/list/index_json",
            "sent": "/messages/list/outbox",
            "outbox": "/messages/list/outbox",
            "archive": "/messages/list/archive",
            "drafts": "/messages/list/drafts",
        }
        path = folder_paths.get(folder)
        if path is None:
            raise WilmaAPIError(
                f"Unknown folder '{folder}'. "
                "Use inbox, sent, archive, or drafts."
            )

        response = await self._request("GET", path)

        try:
            data = response.json()
            return self._parse_messages_json(data, folder, limit)
        except ValueError:
            raise WilmaAPIError("Failed to parse messages response")

    def _parse_messages_json(
        self, data: dict, folder: str, limit: int
    ) -> list[MessageSummary]:
        """Parse messages list from JSON response."""
        messages = []
        msg_list = data.get("Messages", [])

        # In the sent/drafts folders the account owner is the Sender, so the
        # useful counterparty is the Recipient instead.
        show_recipient = folder in ("sent", "outbox", "drafts")

        for msg in msg_list[:limit]:
            # Parse timestamp (format: "2026-02-08 11:42")
            timestamp_str = msg.get("TimeStamp", "")
            try:
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M")
            except ValueError:
                timestamp = datetime.now()

            if show_recipient:
                counterparty = msg.get("Recipient") or msg.get("Sender") or ""
            else:
                counterparty = msg.get("Sender") or msg.get("Recipient") or ""

            # Status field: truthy (e.g. 1) = unread/new, falsy/missing = read
            # Wilma's frontend uses Status to show bold "Uusi" (New) badge
            message = MessageSummary(
                id=str(msg.get("Id", "")),
                subject=msg.get("Subject", ""),
                sender=counterparty,
                timestamp=timestamp,
                is_read=not msg.get("Status"),
                folder=msg.get("Folder", folder),
            )
            messages.append(message)

        return messages

    async def get_message(self, message_id: str) -> Message:
        """Get a specific message with full content.

        Args:
            message_id: Message ID

        Returns:
            Message object with full content
        """
        # Single messages require HTML parsing
        path = f"/messages/{message_id}"
        response = await self._request("GET", path)

        return self._parse_message_from_html(response.text, message_id)

    def _parse_message_from_html(self, html: str, message_id: str) -> Message:
        """Parse a single message from HTML response.

        Wilma's message view carries the metadata (sender, recipients, sent
        time) in a small ``label: value`` table and the body in a
        ``div.ckeditor`` container. We read those directly, which avoids the
        modal-dialog and navigation text that bleeds in when scraping the whole
        panel. A best-effort fallback handles older/rare layouts.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Subject from the <title> ("Subject - Wilma").
        title_tag = soup.find("title")
        subject = ""
        if title_tag:
            title_text = title_tag.get_text(strip=True)
            if " - Wilma" in title_text:
                subject = title_text.rsplit(" - Wilma", 1)[0].strip()

        # Metadata table: each row is a "Label:" cell followed by a value cell.
        meta: dict[str, str] = {}
        for tr in soup.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) >= 2:
                label = cells[0].get_text(" ", strip=True).rstrip(":").casefold()
                if label and label not in meta:
                    meta[label] = cells[1].get_text(" ", strip=True)

        sender = meta.get("lähettäjä", "")

        # Recipients ("Piilotettu" = hidden) - only keep if a real value.
        recipients: list[str] = []
        rcpt_raw = meta.get("vastaanottajat", "")
        if rcpt_raw and rcpt_raw.casefold() != "piilotettu":
            recipients = [r.strip() for r in rcpt_raw.split(",") if r.strip()]

        # Sent timestamp, e.g. "7.8.2026 klo 16:53".
        timestamp = datetime.now()
        time_match = re.search(
            r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s*(?:klo\s*)?(\d{1,2})[.:](\d{2})",
            meta.get("lähetetty", ""),
        )
        if time_match:
            day, month, year = (int(time_match.group(i)) for i in (1, 2, 3))
            hour, minute = int(time_match.group(4)), int(time_match.group(5))
            timestamp = datetime(year, month, day, hour, minute)

        # Body lives in the CKEditor content container; join its lines so
        # paragraph breaks are preserved.
        content = ""
        body_el = soup.find("div", class_="ckeditor")
        if body_el:
            content = "\n".join(body_el.stripped_strings).strip()

        if not content:
            # Fallback: scrape the panel body and strip metadata/modal cruft.
            panel_body = soup.find("div", class_="panel-body")
            if panel_body:
                full_text = panel_body.get_text(separator="\n", strip=True)
                parts = re.split(
                    r"\d{1,2}\.\d{1,2}\.\d{4}\s*(?:klo\s*)?\d{1,2}[.:]\d{2}",
                    full_text,
                )
                content = (parts[-1] if len(parts) > 1 else full_text).strip()
            content = re.sub(r"×\s*Varmistus\s*Jatka\s*Peruuta", "", content)
            content = re.sub(r"Vastaa viestin lähettäjälle", "", content).strip()

        return Message(
            id=message_id,
            subject=subject,
            sender=sender,
            timestamp=timestamp,
            content=content,
            recipients=recipients,
            is_read=True,
        )

    async def mark_message_read(self, message_id: str) -> bool:
        """Mark a message as read by viewing it.

        Wilma marks messages as read when they are viewed (GET request).
        There is no separate API endpoint for this.

        Args:
            message_id: Message ID to mark as read

        Returns:
            True if the request succeeded
        """
        path = f"/messages/{message_id}"
        response = await self._request("GET", path)
        # A successful page load (not a redirect to login or error) means read
        return response.status_code == 200

    async def get_recipients(self, query: Optional[str] = None) -> list[Recipient]:
        """Get available message recipients.

        Wilma does not expose recipients as ``<option>`` elements. Instead the
        compose flow opens a side panel (``/messages/recipients``) that embeds
        every reachable recipient as a clickable ``.recipient-block`` button.
        Each button carries a ``data-source`` link of the form
        ``/messages/compose?r_<type>=<id>[&n_class=<c>]`` which is exactly the
        selector needed to address that recipient. We parse those blocks; the
        selector querystring becomes the recipient's ``id`` so it can be passed
        straight back to :meth:`send_message`.

        Args:
            query: Optional case-insensitive substring to filter by name.

        Returns:
            List of Recipient objects.
        """
        response = await self._request("GET", "/messages/recipients")
        recipients = self._parse_recipient_panel(response.text)

        if query:
            q = query.casefold()
            recipients = [r for r in recipients if q in r.name.casefold()]

        return recipients

    def _parse_recipient_panel(self, html: str) -> list[Recipient]:
        """Parse recipients from the ``/messages/recipients`` side panel HTML."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        recipients: list[Recipient] = []
        seen: set[str] = set()

        for block in soup.select("[data-source]"):
            source = block.get("data-source", "")
            if "messages/compose" not in source:
                continue

            selector = urlsplit(source).query  # e.g. "r_guardian=11876_2893&n_class=33"
            if not selector:
                continue

            # Identify the recipient type from the r_<type>/s_<type> parameter.
            rtype: Optional[str] = None
            for key, _value in parse_qsl(selector):
                if key.startswith(("r_", "s_")):
                    rtype = key[2:]
                    break
            if rtype is None:
                continue

            if selector in seen:
                continue
            seen.add(selector)

            name = " ".join(block.get_text(" ", strip=True).split())
            # Group blocks (e.g. "all teachers") often carry the descriptive
            # member list in the title attribute.
            title = block.get("title") or None
            if not name:
                name = title or selector

            role = _RECIPIENT_ROLE_LABELS.get(rtype, rtype)
            recipients.append(
                Recipient(id=selector, name=name, role=role, school=title)
            )

        return recipients

    async def _resolve_recipient_selector(self, recipient: str) -> str:
        """Resolve a recipient reference to a compose selector querystring.

        Accepts either a selector token already produced by
        :meth:`get_recipients` (e.g. ``"r_guardian=11876_2893&n_class=33"``) or a
        display name to look up in the recipient panel.

        Raises:
            WilmaAPIError: If the name matches zero or several recipients.
        """
        recipient = recipient.strip()

        # Already a selector token (contains an r_/s_ parameter)?
        if re.search(r"(?:^|&)[rs]_[a-z]+=", recipient):
            return recipient

        matches = await self.get_recipients(query=recipient)
        if not matches:
            raise WilmaAPIError(
                f"No recipient found matching '{recipient}'. "
                "Use get_recipients to see who is available."
            )

        # Prefer a single exact (case-insensitive) name match if one exists.
        exact = [m for m in matches if m.name.casefold() == recipient.casefold()]
        if len(exact) == 1:
            return exact[0].id
        if len(matches) == 1:
            return matches[0].id

        candidates = ", ".join(f"'{m.name}'" for m in matches[:10])
        raise WilmaAPIError(
            f"Recipient '{recipient}' is ambiguous - it matches: {candidates}. "
            "Please be more specific or pass the recipient id from get_recipients."
        )

    def _find_compose_form(self, soup: Any) -> Any:
        """Locate the message compose form (the one with a body textarea)."""
        for candidate in soup.find_all("form"):
            action = (candidate.get("action") or "").lower()
            if "logout" in action:
                continue
            if candidate.find("textarea"):
                return candidate
        return None

    async def _submit_compose_form(
        self,
        html: str,
        body: str,
        subject: Optional[str] = None,
    ) -> bool:
        """Build and POST a Wilma compose form.

        Collects the form's existing fields (formkey/CSRF token, wysiwyg mode,
        pre-filled recipient ``r_<type>`` hidden inputs, and any pre-filled
        Subject) from the given compose HTML, fills in the subject/body, adds the
        "send" submit button, and posts the form.

        Args:
            html: HTML of a compose page (new message or reply form).
            body: Message body text.
            subject: Subject to set. If None, any pre-filled subject (e.g. the
                "VS:"/"Re:" of a reply) is left untouched.

        Returns:
            True if the message appears to have been sent.

        Raises:
            WilmaAPIError: If the form can't be found or the send fails.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        form = self._find_compose_form(soup)
        if form is None:
            raise WilmaAPIError("Could not locate the compose form")

        data: dict[str, str] = {}
        subject_field: Optional[str] = None
        send_button: Optional[tuple[str, str]] = None

        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            itype = (inp.get("type") or "text").lower()
            value = inp.get("value") or ""

            if itype in ("hidden", "text"):
                # Carries formkey, wysiwyg, recipient r_* fields, Subject, etc.
                data[name] = value
                if name.casefold() == "subject":
                    subject_field = name
            elif itype == "checkbox":
                # Only submit checkboxes that are checked by default.
                if inp.has_attr("checked"):
                    data[name] = value or "true"
            elif itype == "submit":
                # Remember the "send" button; ignore draft/cancel buttons so we
                # never accidentally save a draft or discard the message.
                if name == "addsavebtn":
                    send_button = (name, value)
                elif send_button is None and name not in ("draftbtn", "cancelbtn"):
                    send_button = (name, value)

        # Determine the body textarea field name.
        textarea = form.find("textarea")
        body_field = (
            textarea.get("name") if textarea and textarea.get("name") else "BodyText"
        )

        # Verify a recipient is present before sending.
        if not any(k.startswith(("r_", "s_")) for k in data):
            raise WilmaAPIError(
                "Compose form has no recipient - refusing to send. "
                "The recipient selector may be invalid."
            )

        if subject is not None:
            data[subject_field or "Subject"] = subject
        data[body_field] = body

        if send_button is not None:
            data[send_button[0]] = send_button[1]

        # Never submit the draft/cancel actions.
        data.pop("draftbtn", None)
        data.pop("cancelbtn", None)

        action = form.get("action") or "/messages/compose"
        response = await self._request(
            "POST",
            action,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return self._check_send_result(response)

    def _check_send_result(self, response: httpx.Response) -> bool:
        """Interpret the response to a compose POST.

        On success Wilma redirects away from the compose page back to the
        messages listing. If the compose form is redisplayed, the send was
        rejected (e.g. validation error).
        """
        final_url = str(response.url).lower()

        if "/messages" in final_url and "/compose" not in final_url:
            return True

        if "/compose" in final_url:
            # Compose form redisplayed - surface any error text if we can find it.
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(response.text, "html.parser")
            alert = soup.find(class_=re.compile(r"\balert\b", re.I))
            detail = ""
            if alert:
                detail = " ".join(alert.get_text(" ", strip=True).split())[:200]
            raise WilmaAPIError(
                "Message was not sent - Wilma redisplayed the compose form"
                + (f": {detail}" if detail else " (possible validation error).")
            )

        # Some instances render the sent-confirmation at a 200 without a
        # /messages URL; check the body as a fallback.
        text = response.text.lower()
        if "viesti on lähetetty" in text or "message has been sent" in text:
            return True

        raise WilmaAPIError(
            "Unexpected response after sending message - could not confirm delivery."
        )

    async def send_message(
        self,
        recipient: str,
        subject: str,
        body: str,
    ) -> bool:
        """Send a new message to a recipient.

        Args:
            recipient: Either a display name (looked up in the recipient panel)
                or a selector id returned by :meth:`get_recipients`
                (e.g. ``"r_guardian=11876_2893&n_class=33"``). To address several
                recipients, join their selector ids with ``&``.
            subject: Message subject.
            body: Message body.

        Returns:
            True if the message was sent successfully.

        Raises:
            WilmaAPIError: If the recipient can't be resolved or sending fails.
        """
        selector = await self._resolve_recipient_selector(recipient)

        # GET the compose form with the recipient preselected. This mirrors the
        # no-JavaScript path of clicking a recipient block: Wilma returns the
        # compose form with a fresh formkey and the recipient added as a hidden
        # r_<type> input.
        compose_response = await self._request("GET", f"/messages/compose?{selector}")

        return await self._submit_compose_form(
            compose_response.text, body=body, subject=subject
        )

    async def reply_to_message(self, message_id: str, body: str) -> bool:
        """Reply to a message by ID.

        Handles both kinds of thread Wilma serves:

        * **Open / collated threads** (the teacher ticked "avoin keskustelu", so
          every recipient sees every answer). These carry an inline quick-reply
          form posting to ``/messages/collatedreply/<id>``; the reply becomes a
          comment on the shared thread. Preferred when present, because it is
          what the sender asked for by opening the discussion.
        * **Ordinary messages**, which link to a compose form with the recipient
          and subject pre-filled. The reply goes to the sender alone.

        Args:
            message_id: ID of the message to reply to
            body: Reply message body

        Returns:
            True if reply was sent successfully

        Raises:
            WilmaAPIError: If sending fails
        """
        from bs4 import BeautifulSoup

        # Step 1: Fetch the original message page to find the reply route.
        msg_response = await self._request("GET", f"/messages/{message_id}")
        msg_soup = BeautifulSoup(msg_response.text, "html.parser")

        # Step 2: An open discussion thread answers via its quick-reply form.
        quickreply = msg_soup.find("form", id="quickreply-form")
        if quickreply and quickreply.get("action"):
            data = {
                inp["name"]: inp.get("value") or ""
                for inp in quickreply.find_all("input")
                if inp.get("name")
            }
            data["bodytext"] = body
            await self._request("POST", quickreply["action"], data=data)
            return True

        # Step 3: Otherwise fall back to the separate-message compose form.
        # Skip in-page anchors (e.g. "#quickreply"), which are not fetchable.
        reply_link = None
        for candidate in msg_soup.find_all("a", string=re.compile(r"Vastaa", re.I)):
            href = candidate.get("href") or ""
            if href and not href.startswith("#"):
                reply_link = candidate
                break
        if not reply_link:
            reply_link = msg_soup.find(
                "a", href=re.compile(r"compose.*(?:answer|reply|replyid)", re.I)
            )
        if not reply_link or not reply_link.get("href"):
            raise WilmaAPIError(
                f"Could not find reply link on message {message_id}"
            )

        # Subject is left as None so Wilma's pre-filled "VS:" subject is kept.
        compose_response = await self._request("GET", reply_link["href"])
        return await self._submit_compose_form(
            compose_response.text, body=body, subject=None
        )
