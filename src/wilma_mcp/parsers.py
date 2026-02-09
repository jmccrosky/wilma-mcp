"""HTML parsers for Wilma responses."""

import re
from datetime import date, datetime
from typing import Optional

from bs4 import BeautifulSoup

from .models import (
    DaySchedule,
    Lesson,
    Message,
    MessageSummary,
    Recipient,
)


def parse_schedule_html(html: str, target_date: date) -> DaySchedule:
    """Parse schedule from HTML response.

    Args:
        html: Raw HTML response
        target_date: Date of the schedule

    Returns:
        DaySchedule object
    """
    soup = BeautifulSoup(html, "html.parser")
    lessons = []

    # Look for schedule table or list
    # Wilma uses various formats, try common patterns

    # Pattern 1: Table with class "schedule" or similar
    schedule_table = soup.find("table", class_=re.compile(r"schedule|timetable|aikataulu", re.I))
    if schedule_table:
        rows = schedule_table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                # Try to extract time and subject
                time_cell = cells[0].get_text(strip=True)
                subject_cell = cells[1].get_text(strip=True) if len(cells) > 1 else ""

                # Parse time range (e.g., "08:00-08:45")
                time_match = re.search(r"(\d{1,2}[:.]\d{2})\s*[-–]\s*(\d{1,2}[:.]\d{2})", time_cell)
                if time_match:
                    start_time = time_match.group(1).replace(".", ":")
                    end_time = time_match.group(2).replace(".", ":")

                    # Extract room if present
                    room = None
                    room_cell = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                    if room_cell:
                        room = room_cell

                    # Extract teacher
                    teacher = None
                    teacher_cell = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                    if teacher_cell:
                        teacher = teacher_cell

                    lesson = Lesson(
                        start_time=start_time,
                        end_time=end_time,
                        subject=subject_cell,
                        room=room,
                        teacher=teacher,
                    )
                    lessons.append(lesson)

    # Pattern 2: Div-based schedule
    if not lessons:
        schedule_divs = soup.find_all("div", class_=re.compile(r"lesson|event|tunti", re.I))
        for div in schedule_divs:
            text = div.get_text(strip=True)

            # Try to extract time
            time_match = re.search(r"(\d{1,2}[:.]\d{2})\s*[-–]\s*(\d{1,2}[:.]\d{2})", text)
            if time_match:
                start_time = time_match.group(1).replace(".", ":")
                end_time = time_match.group(2).replace(".", ":")

                # Remove time from text to get subject
                subject = re.sub(r"\d{1,2}[:.]\d{2}\s*[-–]\s*\d{1,2}[:.]\d{2}", "", text).strip()

                lesson = Lesson(
                    start_time=start_time,
                    end_time=end_time,
                    subject=subject,
                )
                lessons.append(lesson)

    # Pattern 3: List-based schedule
    if not lessons:
        schedule_list = soup.find("ul", class_=re.compile(r"schedule|lessons", re.I))
        if schedule_list:
            items = schedule_list.find_all("li")
            for item in items:
                text = item.get_text(strip=True)
                time_match = re.search(r"(\d{1,2}[:.]\d{2})\s*[-–]\s*(\d{1,2}[:.]\d{2})", text)
                if time_match:
                    start_time = time_match.group(1).replace(".", ":")
                    end_time = time_match.group(2).replace(".", ":")
                    subject = re.sub(r"\d{1,2}[:.]\d{2}\s*[-–]\s*\d{1,2}[:.]\d{2}", "", text).strip()

                    lesson = Lesson(
                        start_time=start_time,
                        end_time=end_time,
                        subject=subject,
                    )
                    lessons.append(lesson)

    return DaySchedule(date=target_date, lessons=lessons)


def parse_messages_html(html: str, folder: str, limit: int) -> list[MessageSummary]:
    """Parse messages list from HTML response.

    Args:
        html: Raw HTML response
        folder: Folder name
        limit: Maximum number of messages

    Returns:
        List of MessageSummary objects
    """
    soup = BeautifulSoup(html, "html.parser")
    messages = []

    # Look for message list/table
    message_rows = soup.find_all("tr", class_=re.compile(r"message|viesti", re.I))

    # If no specific class, try to find message links
    if not message_rows:
        message_links = soup.find_all("a", href=re.compile(r"/messages/\d+"))
        for link in message_links[:limit]:
            msg_id_match = re.search(r"/messages/(\d+)", link.get("href", ""))
            if msg_id_match:
                msg_id = msg_id_match.group(1)

                # Try to find parent row for more info
                parent = link.find_parent("tr")
                if parent:
                    cells = parent.find_all("td")
                    subject = link.get_text(strip=True)
                    sender = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                    timestamp_str = cells[2].get_text(strip=True) if len(cells) > 2 else ""

                    # Parse timestamp
                    timestamp = _parse_finnish_timestamp(timestamp_str)

                    # Check if read (usually indicated by class or style)
                    is_read = "unread" not in parent.get("class", []) and "lukematon" not in str(parent)

                    message = MessageSummary(
                        id=msg_id,
                        subject=subject,
                        sender=sender,
                        timestamp=timestamp,
                        is_read=is_read,
                        folder=folder,
                    )
                    messages.append(message)
                else:
                    # Just use the link text
                    message = MessageSummary(
                        id=msg_id,
                        subject=link.get_text(strip=True),
                        sender="",
                        timestamp=datetime.now(),
                        folder=folder,
                    )
                    messages.append(message)

    # Process table rows
    for row in message_rows[:limit]:
        cells = row.find_all("td")
        if cells:
            # Extract message ID from link
            link = row.find("a", href=re.compile(r"/messages/\d+"))
            if link:
                msg_id_match = re.search(r"/messages/(\d+)", link.get("href", ""))
                msg_id = msg_id_match.group(1) if msg_id_match else ""
            else:
                continue

            # Extract other fields
            subject = cells[0].get_text(strip=True) if cells else ""
            sender = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            timestamp_str = cells[2].get_text(strip=True) if len(cells) > 2 else ""

            timestamp = _parse_finnish_timestamp(timestamp_str)
            is_read = "unread" not in row.get("class", [])

            message = MessageSummary(
                id=msg_id,
                subject=subject,
                sender=sender,
                timestamp=timestamp,
                is_read=is_read,
                folder=folder,
            )
            messages.append(message)

    return messages


def parse_message_html(html: str, message_id: str) -> Message:
    """Parse a single message from HTML response.

    Args:
        html: Raw HTML response
        message_id: Message ID

    Returns:
        Message object
    """
    soup = BeautifulSoup(html, "html.parser")

    # Extract subject
    subject_elem = soup.find(class_=re.compile(r"subject|otsikko", re.I))
    if not subject_elem:
        subject_elem = soup.find("h1") or soup.find("h2")
    subject = subject_elem.get_text(strip=True) if subject_elem else ""

    # Extract sender
    sender_elem = soup.find(class_=re.compile(r"sender|from|lahettaja", re.I))
    sender = sender_elem.get_text(strip=True) if sender_elem else ""

    # Extract timestamp
    timestamp_elem = soup.find(class_=re.compile(r"date|time|aika", re.I))
    timestamp_str = timestamp_elem.get_text(strip=True) if timestamp_elem else ""
    timestamp = _parse_finnish_timestamp(timestamp_str)

    # Extract content/body
    content_elem = soup.find(class_=re.compile(r"body|content|message-body|sisalto", re.I))
    if not content_elem:
        # Try to find main content area
        content_elem = soup.find("div", class_=re.compile(r"message", re.I))
    content = content_elem.get_text(strip=True) if content_elem else ""

    # Extract attachments
    attachments = []
    attachment_links = soup.find_all("a", href=re.compile(r"attachment|liite", re.I))
    for link in attachment_links:
        attachments.append(link.get_text(strip=True))

    # Extract recipients
    recipients = []
    recipients_elem = soup.find(class_=re.compile(r"recipients|to|vastaanottaja", re.I))
    if recipients_elem:
        recipients = [r.strip() for r in recipients_elem.get_text().split(",")]

    return Message(
        id=message_id,
        subject=subject,
        sender=sender,
        timestamp=timestamp,
        content=content,
        recipients=recipients,
        attachments=attachments,
        is_read=True,
    )


def parse_recipients_html(html: str) -> list[Recipient]:
    """Parse recipients list from HTML response.

    Args:
        html: Raw HTML response

    Returns:
        List of Recipient objects
    """
    soup = BeautifulSoup(html, "html.parser")
    recipients = []

    # Look for recipient list/options
    options = soup.find_all("option")
    for option in options:
        value = option.get("value", "")
        if value and value != "0":
            name = option.get_text(strip=True)

            # Try to extract role from the text (e.g., "Teacher Name (Math)")
            role = None
            role_match = re.search(r"\(([^)]+)\)", name)
            if role_match:
                role = role_match.group(1)
                name = re.sub(r"\s*\([^)]+\)", "", name).strip()

            recipient = Recipient(
                id=value,
                name=name,
                role=role,
            )
            recipients.append(recipient)

    # If no select options, try list items
    if not recipients:
        list_items = soup.find_all("li", class_=re.compile(r"recipient|teacher|opettaja", re.I))
        for item in list_items:
            link = item.find("a")
            if link:
                href = link.get("href", "")
                id_match = re.search(r"/(\d+)", href)
                if id_match:
                    recipient = Recipient(
                        id=id_match.group(1),
                        name=link.get_text(strip=True),
                    )
                    recipients.append(recipient)

    # Also try data attributes
    if not recipients:
        elements = soup.find_all(attrs={"data-id": True})
        for elem in elements:
            recipient = Recipient(
                id=elem.get("data-id", ""),
                name=elem.get_text(strip=True),
            )
            if recipient.id:
                recipients.append(recipient)

    return recipients


def _parse_finnish_timestamp(timestamp_str: str) -> datetime:
    """Parse a Finnish-format timestamp.

    Args:
        timestamp_str: Timestamp string (e.g., "15.3.2024 14:30")

    Returns:
        datetime object
    """
    if not timestamp_str:
        return datetime.now()

    # Common Finnish date formats
    formats = [
        "%d.%m.%Y %H:%M",  # 15.3.2024 14:30
        "%d.%m.%Y %H.%M",  # 15.3.2024 14.30
        "%d.%m.%Y",  # 15.3.2024
        "%d.%m. %H:%M",  # 15.3. 14:30
        "%d.%m.",  # 15.3.
        "%Y-%m-%d %H:%M:%S",  # ISO format
        "%Y-%m-%d",  # ISO date only
    ]

    # Clean up the string
    timestamp_str = timestamp_str.strip()

    for fmt in formats:
        try:
            parsed = datetime.strptime(timestamp_str, fmt)
            # If year is missing, use current year
            if parsed.year == 1900:
                parsed = parsed.replace(year=datetime.now().year)
            return parsed
        except ValueError:
            continue

    # If no format matched, try to extract date components
    date_match = re.search(r"(\d{1,2})\.(\d{1,2})\.?(\d{2,4})?", timestamp_str)
    time_match = re.search(r"(\d{1,2})[.:](\d{2})", timestamp_str)

    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year = int(date_match.group(3)) if date_match.group(3) else datetime.now().year
        if year < 100:
            year += 2000

        hour = int(time_match.group(1)) if time_match else 0
        minute = int(time_match.group(2)) if time_match else 0

        return datetime(year, month, day, hour, minute)

    return datetime.now()
