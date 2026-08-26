"""Data models for Wilma MCP server."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class Lesson:
    """A single lesson/class in the schedule."""

    start_time: str
    end_time: str
    subject: str
    teacher: Optional[str] = None
    room: Optional[str] = None
    groups: list[str] = field(default_factory=list)
    notes: Optional[str] = None


@dataclass
class DaySchedule:
    """Schedule for a single day."""

    date: date
    lessons: list[Lesson] = field(default_factory=list)


@dataclass
class Recipient:
    """A message recipient (teacher, staff, etc.)."""

    id: str
    name: str
    role: Optional[str] = None
    school: Optional[str] = None


@dataclass
class MessageSummary:
    """Summary of a message in the inbox/folder list."""

    id: str
    subject: str
    sender: str
    timestamp: datetime
    is_read: bool = False
    folder: str = "inbox"
    reply_count: int = 0
    """Replies posted on the thread. ``sender`` is always the thread's *opener*
    and ``timestamp`` its *latest activity*, so a message you sent yourself
    reappears in the inbox when somebody answers it. A non-zero count is what
    distinguishes that from a genuinely new message."""


@dataclass
class MessageReply:
    """A single reply posted on a message thread.

    Covers both flavours Wilma renders in ``div.m-replybox``: answers to an
    ordinary one-to-one message, and comments on an open discussion thread
    (*avoin keskustelu*), which every recipient can see and add to.
    """

    sender: str
    content: str
    timestamp: Optional[datetime] = None
    timestamp_text: str = ""
    """Wilma's own wording, kept verbatim because it is sometimes relative
    ("tänään klo 18:50") and cannot always be resolved to an exact datetime."""
    is_own: bool = False
    """True when Wilma labelled it "Sinä vastasit" — i.e. the account owner."""


@dataclass
class Message:
    """Full message with content."""

    id: str
    subject: str
    sender: str
    timestamp: datetime
    content: str
    recipients: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    is_read: bool = False
    folder: str = "inbox"
    reply_to_id: Optional[str] = None
    replies: list["MessageReply"] = field(default_factory=list)


@dataclass
class Grade:
    """A grade/assessment entry."""

    course: str
    grade: str
    date: Optional[date] = None
    teacher: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class Absence:
    """An absence/attendance record."""

    date: date
    type: str  # e.g., "absent", "late", "excused"
    lessons: list[str] = field(default_factory=list)
    explanation: Optional[str] = None
    is_excused: bool = False


@dataclass
class Exam:
    """An upcoming exam."""

    date: date
    subject: str
    description: Optional[str] = None
    teacher: Optional[str] = None
    room: Optional[str] = None


@dataclass
class NewsItem:
    """A school news/announcement item."""

    id: str
    title: str
    content: str
    timestamp: datetime
    author: Optional[str] = None
