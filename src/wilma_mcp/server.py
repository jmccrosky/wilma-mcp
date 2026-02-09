"""Wilma MCP Server - FastMCP server for Finnish school platform."""

import os
from datetime import date, datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastmcp import FastMCP

from .client import WilmaClient, WilmaAuthError, WilmaAPIError
from .models import DaySchedule, Lesson, Message, MessageSummary, Recipient

# Load environment variables
load_dotenv()

# Create FastMCP server
mcp = FastMCP(
    "Wilma MCP",
    instructions="MCP server for Wilma - Finnish school communication platform. Provides access to school schedules, messages, and more.",
)

# Global client instance (initialized on first use)
_client: Optional[WilmaClient] = None


def _get_client() -> WilmaClient:
    """Get or create the Wilma client."""
    global _client
    if _client is None:
        base_url = os.getenv("WILMA_BASE_URL")
        username = os.getenv("WILMA_USERNAME")
        password = os.getenv("WILMA_PASSWORD")

        if not all([base_url, username, password]):
            raise WilmaAuthError(
                "Missing Wilma credentials. Please set WILMA_BASE_URL, "
                "WILMA_USERNAME, and WILMA_PASSWORD environment variables."
            )

        _client = WilmaClient(base_url, username, password)  # type: ignore
    return _client


def _format_lesson(lesson: Lesson) -> str:
    """Format a lesson for display."""
    parts = [f"{lesson.start_time}-{lesson.end_time}: {lesson.subject}"]
    if lesson.room:
        parts.append(f"(Room: {lesson.room})")
    if lesson.teacher:
        parts.append(f"- {lesson.teacher}")
    if lesson.notes:
        parts.append(f"[{lesson.notes}]")
    return " ".join(parts)


def _format_schedule(schedule: DaySchedule) -> str:
    """Format a day's schedule for display."""
    if not schedule.lessons:
        return f"No classes scheduled for {schedule.date.strftime('%A, %B %d, %Y')}"

    lines = [f"Schedule for {schedule.date.strftime('%A, %B %d, %Y')}:", ""]
    for lesson in schedule.lessons:
        lines.append(f"  {_format_lesson(lesson)}")
    return "\n".join(lines)


def _format_message_summary(msg: MessageSummary) -> str:
    """Format a message summary for display."""
    read_status = "📖" if msg.is_read else "📬"
    return (
        f"{read_status} [{msg.id}] {msg.subject}\n"
        f"   From: {msg.sender} | {msg.timestamp.strftime('%Y-%m-%d %H:%M')}"
    )


def _format_message(msg: Message) -> str:
    """Format a full message for display."""
    lines = [
        f"Subject: {msg.subject}",
        f"From: {msg.sender}",
        f"Date: {msg.timestamp.strftime('%Y-%m-%d %H:%M')}",
    ]
    if msg.recipients:
        lines.append(f"To: {', '.join(msg.recipients)}")
    if msg.attachments:
        lines.append(f"Attachments: {', '.join(msg.attachments)}")
    lines.extend(["", "---", "", msg.content])
    return "\n".join(lines)


def _parse_date(date_str: str) -> date:
    """Parse a date string, supporting various formats."""
    date_str = date_str.lower().strip()

    # Handle relative dates
    today = date.today()
    if date_str in ("today", "tänään"):
        return today
    if date_str in ("tomorrow", "huomenna"):
        return today + timedelta(days=1)
    if date_str in ("yesterday", "eilen"):
        return today - timedelta(days=1)

    # Handle weekday names
    weekdays = {
        "monday": 0, "maanantai": 0,
        "tuesday": 1, "tiistai": 1,
        "wednesday": 2, "keskiviikko": 2,
        "thursday": 3, "torstai": 3,
        "friday": 4, "perjantai": 4,
        "saturday": 5, "lauantai": 5,
        "sunday": 6, "sunnuntai": 6,
    }
    if date_str in weekdays:
        target_weekday = weekdays[date_str]
        current_weekday = today.weekday()
        days_ahead = target_weekday - current_weekday
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        return today + timedelta(days=days_ahead)

    # Try parsing as date
    formats = [
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d.%m.",
        "%m/%d/%Y",
        "%d/%m/%Y",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=today.year)
            return parsed.date()
        except ValueError:
            continue

    raise ValueError(f"Could not parse date: {date_str}")


@mcp.tool()
async def get_schedule(date_str: str = "today") -> str:
    """Get the school schedule for a specific date.

    Args:
        date_str: Date to get schedule for. Supports:
            - "today", "tomorrow", "yesterday"
            - Weekday names: "monday", "tuesday", etc.
            - Date formats: "2024-03-15", "15.3.2024", "15.3."

    Returns:
        Formatted schedule showing all classes for the day.
    """
    try:
        target_date = _parse_date(date_str)
    except ValueError as e:
        return str(e)

    try:
        client = _get_client()
        schedule = await client.get_schedule(target_date)
        return _format_schedule(schedule)
    except WilmaAuthError as e:
        return f"Authentication error: {e}"
    except WilmaAPIError as e:
        return f"API error: {e}"


@mcp.tool()
async def get_week_schedule(start_date: str = "today") -> str:
    """Get the school schedule for a full week.

    Args:
        start_date: Start date of the week. Defaults to today.

    Returns:
        Formatted schedule showing all classes for each day of the week.
    """
    try:
        target_date = _parse_date(start_date)
    except ValueError as e:
        return str(e)

    try:
        client = _get_client()
        schedules = await client.get_week_schedule(target_date)

        lines = ["Weekly Schedule", "=" * 40]
        for schedule in schedules:
            lines.append("")
            lines.append(_format_schedule(schedule))
        return "\n".join(lines)
    except WilmaAuthError as e:
        return f"Authentication error: {e}"
    except WilmaAPIError as e:
        return f"API error: {e}"


@mcp.tool()
async def get_messages(folder: str = "inbox", limit: int = 20) -> str:
    """Get list of messages from a folder.

    Args:
        folder: Folder to read from. Options: "inbox", "sent", "archive"
        limit: Maximum number of messages to return (default 20)

    Returns:
        List of messages with ID, subject, sender, and timestamp.
    """
    if folder not in ("inbox", "sent", "archive"):
        return f"Invalid folder: {folder}. Use 'inbox', 'sent', or 'archive'."

    try:
        client = _get_client()
        messages = await client.get_messages(folder, limit)

        if not messages:
            return f"No messages in {folder}."

        lines = [f"Messages in {folder} ({len(messages)} shown):", ""]
        for msg in messages:
            lines.append(_format_message_summary(msg))
            lines.append("")
        return "\n".join(lines)
    except WilmaAuthError as e:
        return f"Authentication error: {e}"
    except WilmaAPIError as e:
        return f"API error: {e}"


@mcp.tool()
async def get_message(message_id: str) -> str:
    """Read a specific message with full content.

    Args:
        message_id: The ID of the message to read.

    Returns:
        Full message content including subject, sender, date, and body.
    """
    try:
        client = _get_client()
        message = await client.get_message(message_id)
        return _format_message(message)
    except WilmaAuthError as e:
        return f"Authentication error: {e}"
    except WilmaAPIError as e:
        return f"API error: {e}"


@mcp.tool()
async def get_recipients() -> str:
    """Get list of available message recipients (teachers, staff).

    Returns:
        List of recipients with their IDs and roles.
    """
    try:
        client = _get_client()
        recipients = await client.get_recipients()

        if not recipients:
            return "No recipients found."

        lines = ["Available Recipients:", ""]
        for rec in recipients:
            role_info = f" ({rec.role})" if rec.role else ""
            school_info = f" - {rec.school}" if rec.school else ""
            lines.append(f"  [{rec.id}] {rec.name}{role_info}{school_info}")
        return "\n".join(lines)
    except WilmaAuthError as e:
        return f"Authentication error: {e}"
    except WilmaAPIError as e:
        return f"API error: {e}"


@mcp.tool()
async def send_message(
    recipient_id: str,
    subject: str,
    body: str,
    reply_to_id: Optional[str] = None,
) -> str:
    """Send a message to a teacher or staff member.

    Args:
        recipient_id: ID of the recipient (use get_recipients to find IDs)
        subject: Message subject
        body: Message body/content
        reply_to_id: Optional message ID if this is a reply

    Returns:
        Confirmation message or error.
    """
    if not recipient_id.strip():
        return "Error: recipient_id is required"
    if not subject.strip():
        return "Error: subject is required"
    if not body.strip():
        return "Error: message body is required"

    try:
        client = _get_client()
        success = await client.send_message(
            recipient_ids=[recipient_id],
            subject=subject,
            body=body,
            reply_to_id=reply_to_id,
        )
        if success:
            return f"Message sent successfully to recipient {recipient_id}."
        return "Failed to send message."
    except WilmaAuthError as e:
        return f"Authentication error: {e}"
    except WilmaAPIError as e:
        return f"API error: {e}"


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
