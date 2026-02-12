"""Wilma CLI - Command-line interface for the Wilma client.

Usage:
    python -m wilma_mcp.cli <command> [options]

Commands:
    schedule [date]              Get schedule for a date (default: today)
    week [start_date]            Get week schedule
    messages [--folder F] [--limit N]  List messages
    message <id>                 Read a specific message
    mark-read <id>               Mark a message as read
    recipients                   List message recipients
    send <recipient_id> <subject> <body>  Send a message
    reply <message_id> <body>    Reply to a message
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _load_env():
    """Load .env from the wilma-mcp project directory."""
    # Try the directory containing this file first, then walk up
    here = Path(__file__).resolve().parent
    for candidate in [here / ".env", here.parent / ".env", here.parent.parent / ".env"]:
        if candidate.exists():
            load_dotenv(candidate)
            return
    # Fallback: let dotenv search from cwd
    load_dotenv()


def _get_client():
    from .client import WilmaClient, WilmaAuthError

    base_url = os.getenv("WILMA_BASE_URL")
    username = os.getenv("WILMA_USERNAME")
    password = os.getenv("WILMA_PASSWORD")

    if not all([base_url, username, password]):
        print(
            "Error: Missing credentials. Set WILMA_BASE_URL, WILMA_USERNAME, "
            "and WILMA_PASSWORD environment variables or in .env file.",
            file=sys.stderr,
        )
        sys.exit(1)

    return WilmaClient(base_url, username, password)


def _parse_date(date_str: str):
    """Parse a date string using the same logic as the MCP server."""
    from datetime import date, datetime, timedelta

    date_str = date_str.lower().strip()

    today = date.today()
    if date_str in ("today", "tänään"):
        return today
    if date_str in ("tomorrow", "huomenna"):
        return today + timedelta(days=1)
    if date_str in ("yesterday", "eilen"):
        return today - timedelta(days=1)

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
        if days_ahead <= 0:
            days_ahead += 7
        return today + timedelta(days=days_ahead)

    for fmt in ["%Y-%m-%d", "%d.%m.%Y", "%d.%m.", "%m/%d/%Y", "%d/%m/%Y"]:
        try:
            parsed = datetime.strptime(date_str, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=today.year)
            return parsed.date()
        except ValueError:
            continue

    print(f"Error: Could not parse date: {date_str}", file=sys.stderr)
    sys.exit(1)


async def cmd_schedule(args):
    date_str = args[0] if args else "today"
    target_date = _parse_date(date_str)
    client = _get_client()
    try:
        schedule = await client.get_schedule(target_date)
        if not schedule.lessons:
            print(f"No classes scheduled for {schedule.date.strftime('%A, %B %d, %Y')}")
            return
        print(f"Schedule for {schedule.date.strftime('%A, %B %d, %Y')}:")
        for lesson in schedule.lessons:
            parts = [f"  {lesson.start_time}-{lesson.end_time}: {lesson.subject}"]
            if lesson.room:
                parts.append(f"(Room: {lesson.room})")
            if lesson.teacher:
                parts.append(f"- {lesson.teacher}")
            if lesson.notes:
                parts.append(f"[{lesson.notes}]")
            print(" ".join(parts))
    finally:
        await client.close()


async def cmd_week(args):
    date_str = args[0] if args else "today"
    target_date = _parse_date(date_str)
    client = _get_client()
    try:
        schedules = await client.get_week_schedule(target_date)
        print("Weekly Schedule")
        print("=" * 40)
        for schedule in schedules:
            print()
            if not schedule.lessons:
                print(f"No classes scheduled for {schedule.date.strftime('%A, %B %d, %Y')}")
            else:
                print(f"Schedule for {schedule.date.strftime('%A, %B %d, %Y')}:")
                for lesson in schedule.lessons:
                    parts = [f"  {lesson.start_time}-{lesson.end_time}: {lesson.subject}"]
                    if lesson.room:
                        parts.append(f"(Room: {lesson.room})")
                    if lesson.teacher:
                        parts.append(f"- {lesson.teacher}")
                    if lesson.notes:
                        parts.append(f"[{lesson.notes}]")
                    print(" ".join(parts))
    finally:
        await client.close()


async def cmd_messages(args):
    folder = "inbox"
    limit = 20
    i = 0
    while i < len(args):
        if args[i] in ("--folder", "-f") and i + 1 < len(args):
            folder = args[i + 1]
            i += 2
        elif args[i] in ("--limit", "-n") and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        else:
            # Positional: treat as folder
            folder = args[i]
            i += 1

    if folder not in ("inbox", "sent", "archive"):
        print(f"Error: Invalid folder '{folder}'. Use 'inbox', 'sent', or 'archive'.", file=sys.stderr)
        sys.exit(1)

    client = _get_client()
    try:
        messages = await client.get_messages(folder, limit)
        if not messages:
            print(f"No messages in {folder}.")
            return
        print(f"Messages in {folder} ({len(messages)} shown):")
        print()
        for msg in messages:
            status = "READ" if msg.is_read else "UNREAD"
            print(f"[{msg.id}] ({status}) {msg.subject}")
            print(f"   From: {msg.sender} | {msg.timestamp.strftime('%Y-%m-%d %H:%M')}")
            print()
    finally:
        await client.close()


async def cmd_message(args):
    if not args:
        print("Error: message_id is required", file=sys.stderr)
        sys.exit(1)
    message_id = args[0]
    client = _get_client()
    try:
        msg = await client.get_message(message_id)
        print(f"Subject: {msg.subject}")
        print(f"From: {msg.sender}")
        print(f"Date: {msg.timestamp.strftime('%Y-%m-%d %H:%M')}")
        if msg.recipients:
            print(f"To: {', '.join(msg.recipients)}")
        if msg.attachments:
            print(f"Attachments: {', '.join(msg.attachments)}")
        print()
        print("---")
        print()
        print(msg.content)
    finally:
        await client.close()


async def cmd_mark_read(args):
    if not args:
        print("Error: message_id is required", file=sys.stderr)
        sys.exit(1)
    message_id = args[0]
    client = _get_client()
    try:
        success = await client.mark_message_read(message_id)
        if success:
            print(f"Message {message_id} marked as read.")
        else:
            print(f"Failed to mark message {message_id} as read.", file=sys.stderr)
            sys.exit(1)
    finally:
        await client.close()


async def cmd_recipients(args):
    client = _get_client()
    try:
        recipients = await client.get_recipients()
        if not recipients:
            print("No recipients found.")
            return
        print("Available Recipients:")
        print()
        for rec in recipients:
            role_info = f" ({rec.role})" if rec.role else ""
            school_info = f" - {rec.school}" if rec.school else ""
            print(f"  [{rec.id}] {rec.name}{role_info}{school_info}")
    finally:
        await client.close()


async def cmd_send(args):
    if len(args) < 3:
        print("Error: requires <recipient_id> <subject> <body>", file=sys.stderr)
        sys.exit(1)
    recipient_id = args[0]
    subject = args[1]
    body = args[2]
    client = _get_client()
    try:
        success = await client.send_message(
            recipient_ids=[recipient_id],
            subject=subject,
            body=body,
        )
        if success:
            print(f"Message sent successfully to recipient {recipient_id}.")
        else:
            print("Failed to send message.", file=sys.stderr)
            sys.exit(1)
    finally:
        await client.close()


async def cmd_reply(args):
    if len(args) < 2:
        print("Error: requires <message_id> <body>", file=sys.stderr)
        sys.exit(1)
    message_id = args[0]
    body = args[1]
    client = _get_client()
    try:
        success = await client.reply_to_message(
            message_id=message_id,
            body=body,
        )
        if success:
            print(f"Reply sent successfully to message {message_id}.")
        else:
            print("Failed to send reply.", file=sys.stderr)
            sys.exit(1)
    finally:
        await client.close()


COMMANDS = {
    "schedule": cmd_schedule,
    "week": cmd_week,
    "messages": cmd_messages,
    "message": cmd_message,
    "mark-read": cmd_mark_read,
    "recipients": cmd_recipients,
    "send": cmd_send,
    "reply": cmd_reply,
}

USAGE = """\
Usage: python -m wilma_mcp.cli <command> [options]

Commands:
  schedule [date]                        Get schedule for a date (default: today)
  week [start_date]                      Get week schedule (default: this week)
  messages [--folder inbox|sent|archive] [--limit N]  List messages
  message <id>                           Read a specific message
  mark-read <id>                         Mark a message as read
  recipients                             List available message recipients
  send <recipient_id> <subject> <body>   Send a new message
  reply <message_id> <body>              Reply to a message

Date formats: today, tomorrow, yesterday, monday-sunday, YYYY-MM-DD, DD.MM.YYYY
Finnish dates also supported: tänään, huomenna, maanantai, etc."""


def main():
    _load_env()

    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE)
        sys.exit(0)

    command = args[0]
    if command not in COMMANDS:
        print(f"Error: Unknown command '{command}'", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    asyncio.run(COMMANDS[command](args[1:]))


if __name__ == "__main__":
    main()
