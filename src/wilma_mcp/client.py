"""Wilma HTTP client for authentication and API requests."""

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

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
            folder: Folder name (inbox, sent, archive)
            limit: Maximum number of messages to return

        Returns:
            List of MessageSummary objects
        """
        # Use the JSON endpoint
        path = "/messages/list/index_json"

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

        for msg in msg_list[:limit]:
            # Parse timestamp (format: "2026-02-08 11:42")
            timestamp_str = msg.get("TimeStamp", "")
            try:
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M")
            except ValueError:
                timestamp = datetime.now()

            message = MessageSummary(
                id=str(msg.get("Id", "")),
                subject=msg.get("Subject", ""),
                sender=msg.get("Sender", ""),
                timestamp=timestamp,
                is_read=msg.get("Status", 0) != 0,
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
        """Parse a single message from HTML response."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Extract subject from title
        title_tag = soup.find("title")
        subject = ""
        if title_tag:
            # Title format: "Subject - Wilma"
            title_text = title_tag.get_text(strip=True)
            if " - Wilma" in title_text:
                subject = title_text.rsplit(" - Wilma", 1)[0].strip()

        # Extract sender - look for "Lähettäjä:" label
        sender = ""
        sender_label = soup.find(string=re.compile(r"Lähettäjä", re.I))
        if sender_label:
            # The sender name is in the next sibling or parent's next element
            parent = sender_label.find_parent()
            if parent:
                next_elem = parent.find_next_sibling()
                if next_elem:
                    sender = next_elem.get_text(strip=True)

        # Extract timestamp
        timestamp = datetime.now()
        sent_label = soup.find(string=re.compile(r"Lähetetty", re.I))
        if sent_label:
            parent = sent_label.find_parent()
            if parent:
                next_elem = parent.find_next_sibling()
                if next_elem:
                    time_text = next_elem.get_text(strip=True)
                    # Parse format like "8.2.2026 klo 11:42"
                    time_match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s*(?:klo\s*)?(\d{1,2})[.:](\d{2})", time_text)
                    if time_match:
                        day, month, year = int(time_match.group(1)), int(time_match.group(2)), int(time_match.group(3))
                        hour, minute = int(time_match.group(4)), int(time_match.group(5))
                        timestamp = datetime(year, month, day, hour, minute)

        # Extract message content - find the panel-body and get text after metadata
        content = ""
        panel_body = soup.find("div", class_="panel-body")
        if panel_body:
            # Get full text and extract content after "Lähetetty:" timestamp
            full_text = panel_body.get_text(separator="\n", strip=True)
            # Split at the timestamp pattern and take everything after
            parts = re.split(r"\d{1,2}\.\d{1,2}\.\d{4}\s*(?:klo\s*)?\d{1,2}[.:]\d{2}", full_text)
            if len(parts) > 1:
                content = parts[-1].strip()
            else:
                content = full_text

        # Clean up content - remove modal dialogs and UI elements
        content = re.sub(r"×\s*Varmistus\s*Jatka\s*Peruuta", "", content)
        content = re.sub(r"Vastaa viestin lähettäjälle", "", content)
        content = content.strip()

        return Message(
            id=message_id,
            subject=subject,
            sender=sender,
            timestamp=timestamp,
            content=content,
            is_read=True,
        )

    async def get_recipients(self) -> list[Recipient]:
        """Get list of available message recipients.

        Tries multiple strategies since Wilma may load recipients
        dynamically via JavaScript rather than server-side HTML.

        Returns:
            List of Recipient objects (teachers, staff, etc.)
        """
        # Get the compose page
        path = "/messages/compose"
        response = await self._request("GET", path)
        html = response.text

        # Strategy 1: Parse from <option> elements (server-rendered)
        recipients = self._parse_recipients_from_html(html)
        if recipients:
            return recipients

        # Strategy 2: Extract from embedded JavaScript data
        # (Wilma may embed recipient data in JS variables for dynamic loading)
        recipients = self._parse_recipients_from_js(html)
        if recipients:
            return recipients

        return []

    def _parse_recipients_from_html(self, html: str) -> list[Recipient]:
        """Parse recipients from compose page HTML <option> elements."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        recipients = []

        # Look for select options or recipient list
        options = soup.find_all("option")
        for option in options:
            value = option.get("value", "")
            if value and value != "0" and value != "":
                name = option.get_text(strip=True)
                if name:
                    # Extract role from parentheses if present
                    role = None
                    role_match = re.search(r"\(([^)]+)\)$", name)
                    if role_match:
                        role = role_match.group(1)
                        name = name.rsplit("(", 1)[0].strip()

                    recipient = Recipient(
                        id=value,
                        name=name,
                        role=role,
                    )
                    recipients.append(recipient)

        return recipients

    def _parse_recipients_from_js(self, html: str) -> list[Recipient]:
        """Extract recipient data from embedded JavaScript in compose page.

        Wilma may embed recipient data in JavaScript variables or
        widget initialization data (e.g., select2/chosen dropdowns).
        """
        recipients = []

        # Pattern 1: select2/chosen widget data - data: [{id: "...", text: "..."}]
        data_match = re.search(
            r"data\s*:\s*(\[(?:[^[\]]*|\[(?:[^[\]]*|\[[^[\]]*\])*\])*\])",
            html,
        )
        if data_match:
            try:
                data = json.loads(data_match.group(1))
                recipients = self._recipients_from_json_list(data)
                if recipients:
                    return recipients
            except (json.JSONDecodeError, TypeError):
                pass

        # Pattern 2: Variable assignments with recipient arrays
        # e.g., var recipients = [...] or recipientData = [...]
        for pattern in [
            r"(?:recipients|vastaanottajat|rcptList|recipientData)\s*=\s*(\[.*?\])\s*;",
            r"JSON\.parse\(\s*['\"](\[.*?\])['\"]",
        ]:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    recipients = self._recipients_from_json_list(data)
                    if recipients:
                        return recipients
                except (json.JSONDecodeError, TypeError):
                    pass

        return recipients

    def _recipients_from_json_list(self, data: list) -> list[Recipient]:
        """Convert a JSON list of recipient objects to Recipient models."""
        recipients = []
        for item in data:
            if not isinstance(item, dict):
                continue
            rid = str(
                item.get("id", item.get("Id", item.get("ID", "")))
            )
            name = str(
                item.get("text", item.get("name", item.get("Name", "")))
            )
            if not rid or not name:
                continue
            # Extract role from parentheses if present
            role = None
            role_match = re.search(r"\(([^)]+)\)$", name)
            if role_match:
                role = role_match.group(1)
                name = name.rsplit("(", 1)[0].strip()
            recipients.append(Recipient(id=rid, name=name, role=role))
        return recipients

    async def send_message(
        self,
        recipient_ids: list[str],
        subject: str,
        body: str,
        reply_to_id: Optional[str] = None,
    ) -> bool:
        """Send a message.

        Args:
            recipient_ids: List of recipient IDs
            subject: Message subject
            body: Message body
            reply_to_id: Optional message ID if this is a reply

        Returns:
            True if message was sent successfully

        Raises:
            WilmaAPIError: If sending fails
        """
        # First, get the compose form to obtain formkey
        compose_response = await self._request("GET", "/messages/compose")

        # Extract formkey
        formkey_match = re.search(
            r'name="formkey"\s+value="([^"]*)"', compose_response.text
        )
        if not formkey_match:
            formkey_match = re.search(
                r'value="([^"]*)"\s+name="formkey"', compose_response.text
            )
        formkey = formkey_match.group(1) if formkey_match else ""

        # Prepare message data
        data = {
            "formkey": formkey,
            "rcpt": ",".join(recipient_ids),
            "subject": subject,
            "body": body,
        }

        if reply_to_id:
            data["replyto"] = reply_to_id

        response = await self._request(
            "POST",
            "/messages/compose",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        # Check for success - should redirect to messages list
        if "messages" in str(response.url).lower():
            return True

        # Check for error messages in response
        if "error" in response.text.lower() or "virhe" in response.text.lower():
            raise WilmaAPIError("Failed to send message - server returned an error")

        return True

    async def reply_to_message(self, message_id: str, body: str) -> bool:
        """Reply to a message by ID.

        Uses Wilma's reply compose form, which handles recipient resolution
        server-side based on the original message. This avoids the need to
        look up recipient IDs separately (which fails when the recipient
        list is loaded dynamically via JavaScript).

        Args:
            message_id: ID of the message to reply to
            body: Reply message body

        Returns:
            True if reply was sent successfully

        Raises:
            WilmaAPIError: If sending fails
        """
        from bs4 import BeautifulSoup

        # Get the reply compose form - Wilma pre-fills recipient info
        reply_path = f"/messages/compose?answer={message_id}"
        compose_response = await self._request("GET", reply_path)
        html = compose_response.text

        # Extract formkey (CSRF token)
        formkey_match = re.search(
            r'name="formkey"\s+value="([^"]*)"', html
        )
        if not formkey_match:
            formkey_match = re.search(
                r'value="([^"]*)"\s+name="formkey"', html
            )
        if not formkey_match:
            raise WilmaAPIError(
                "Could not extract formkey from reply compose form"
            )
        formkey = formkey_match.group(1)

        # Parse the form to collect all hidden fields
        # These may include recipient, subject, and reply reference fields
        # that Wilma pre-fills for replies
        soup = BeautifulSoup(html, "html.parser")
        form = soup.find("form")

        data: dict[str, str] = {"formkey": formkey}

        if form:
            # Collect all hidden inputs (may include rcpt, answer, subject, etc.)
            for hidden_input in form.find_all("input", {"type": "hidden"}):
                name = hidden_input.get("name", "")
                value = hidden_input.get("value", "")
                if name and name != "formkey":
                    data[name] = value

            # Find the textarea name for the message body field
            textarea = form.find("textarea")
            body_field = textarea.get("name", "body") if textarea else "body"
        else:
            body_field = "body"

        # Set the reply body
        data[body_field] = body

        # Ensure reply reference is included
        if "answer" not in data and "replyto" not in data:
            data["answer"] = message_id

        # Determine POST URL from form action, fall back to compose endpoint
        post_url = "/messages/compose"
        if form and form.get("action"):
            action = form["action"]
            if action.startswith("/"):
                post_url = action

        response = await self._request(
            "POST",
            post_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        # Check for success - should redirect to messages list
        if "messages" in str(response.url).lower():
            return True

        # Check for error messages in response
        if "error" in response.text.lower() or "virhe" in response.text.lower():
            raise WilmaAPIError("Failed to send reply - server returned an error")

        return True
