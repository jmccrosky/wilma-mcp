# Wilma MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server for [Wilma](https://www.visma.com/wilma) - the Finnish school communication platform by Visma. This allows Claude and other MCP-compatible AI assistants to interact with school data including schedules, messages, and more.

## Features

- **Schedule** - View daily or weekly timetables with subjects, times, and teachers
- **Messages** - Read inbox messages with read/unread status, view full content, mark as read
- **Recipients** - List available message recipients (teachers, staff)
- **Send Messages** - Compose and send messages to teachers

## Prerequisites

- Python 3.11 or higher
- A Wilma account (student, guardian, or teacher)
- Your school's Wilma URL (e.g., `https://yourschool.inschool.fi`)

## Installation

```bash
# Clone the repository
git clone https://github.com/jessemc98/wilma-mcp.git
cd wilma-mcp

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install the package
pip install -e .
```

## Configuration

Create a `.env` file with your Wilma credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```
WILMA_BASE_URL=https://yourschool.inschool.fi
WILMA_USERNAME=your_username
WILMA_PASSWORD=your_password
```

> **Security Note**: Never commit your `.env` file to version control.

## Usage with OpenClaw

If you use [OpenClaw](https://openclaw.ai/), this project includes a `SKILL.md` that automatically teaches your agent how to use the Wilma MCP tools.

1. Complete the [Installation](#installation) and [Configuration](#configuration) steps above.
2. Add the MCP server to your Claude Code settings (`~/.claude.json` or project `.mcp.json`):

```json
{
  "mcpServers": {
    "wilma": {
      "command": "/path/to/wilma-mcp/venv/bin/python",
      "args": ["-m", "wilma_mcp.server"],
      "cwd": "/path/to/wilma-mcp"
    }
  }
}
```

3. Place or symlink the `SKILL.md` into your OpenClaw skills directory so the agent can discover it.

## Usage with Claude Desktop

Add the server to your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "wilma": {
      "command": "/path/to/wilma-mcp/venv/bin/python",
      "args": ["-m", "wilma_mcp.server"],
      "cwd": "/path/to/wilma-mcp"
    }
  }
}
```

Restart Claude Desktop after updating the configuration.

## Available Tools

### `get_schedule`
Get the school schedule for a specific date.

**Parameters:**
- `date_str` (optional): Date to get schedule for. Defaults to "today".
  - Supports: "today", "tomorrow", "yesterday"
  - Weekday names: "monday", "tuesday", etc. (English or Finnish)
  - Date formats: "2024-03-15", "15.3.2024"

**Example:** "What's my schedule for Monday?"

### `get_week_schedule`
Get the schedule for a full week.

**Parameters:**
- `start_date` (optional): Start date of the week. Defaults to today.

**Example:** "Show me next week's schedule"

### `get_messages`
Get list of messages from inbox. Each message shows a read/unread indicator (📖 read, 📬 unread).

**Parameters:**
- `folder` (optional): Folder name - "inbox", "sent", "archive", or "drafts". Defaults to "inbox".
- `limit` (optional): Maximum messages to return. Defaults to 20.

For "sent" and "drafts" the listing shows the **recipient** ("To:") rather than the sender.

**Example:** "Check my messages" / "Show my sent messages"

### `get_message`
Read a specific message with full content. Note: viewing a message automatically marks it as read on the Wilma server.

**Parameters:**
- `message_id`: The ID of the message to read.

**Example:** "Read message 12345"

### `set_message_read`
Explicitly mark a message as read. Useful for marking messages as read without reading their full content. Wilma does not support marking messages as unread — this is a platform limitation.

**Parameters:**
- `message_id`: The ID of the message to mark as read.

**Example:** "Mark message 12345 as read"

### `get_recipients`
Get list of available message recipients (teachers, staff, guardians).

**Parameters:**
- `query` (optional): Case-insensitive name filter (e.g. a teacher's surname). Handy because a school's full recipient list can be long.

Each returned recipient has an `id` string (e.g. `r_guardian=11876_2893&n_class=33`) that you can pass straight to `send_message`.

**Example:** "Who can I send messages to?" / "Find the recipient for Mr. Smith"

### `send_message`
Send a new message to any recipient (teacher, staff member, or guardian).

**Parameters:**
- `recipient`: Who to send to — either a person's **name** (e.g. `"Galiana Fatima"`, resolved automatically against the recipient list) or a recipient **id** from `get_recipients` (e.g. `"r_guardian=11876_2893&n_class=33"`). To address several people, join their ids with `&`.
- `subject`: Message subject
- `body`: Message body/content

If a name matches more than one person, the tool returns the list of matches so you can pick a specific id (it will not guess).

**Example:** "Send a message to Mr. Smith about homework"

> To reply to an existing message, use `reply_to_message` instead — it resolves the recipient automatically from the original message.

### `reply_to_message`
Reply to an existing message. This is the preferred way to reply since it handles recipient resolution automatically via Wilma's reply form, without needing to look up recipient IDs.

**Parameters:**
- `message_id`: ID of the message to reply to (from `get_messages`)
- `body`: Reply message body/content

**Example:** "Reply to message 12345 saying I'll attend"

## Example Conversations

Once configured, you can ask Claude:

- "What's my schedule today?"
- "Do I have any classes on Friday?"
- "Show me my unread messages"
- "Read the message from my teacher"
- "What time does school start tomorrow?"

## Technical Notes

- Wilma has no official public API. This server reverse-engineers the web interface.
- Authentication uses session cookies obtained via the login flow.
- Schedule data is extracted from embedded JavaScript in the schedule page.
- Message lists use per-folder JSON endpoints (`/messages/list` for the inbox, `/messages/list/outbox` for sent, `/messages/list/archive`, `/messages/list/drafts`); individual messages require HTML parsing.
- **Read/unread tracking**: Wilma's JSON API includes a `Status` field per message — truthy means unread, falsy/absent means read. Viewing a message (GET request) marks it as read server-side. There is no API to mark a message as unread.
- **Sending messages**: Wilma does not expose recipients as `<option>` elements. The recipient picker (`/messages/recipients`) embeds each reachable person as a `.recipient-block` whose `data-source` link encodes a selector of the form `r_<type>=<id>` (e.g. `r_guardian`, `r_personnel`, `r_ownteachers`). To compose, the server GETs `/messages/compose?<selector>` (which returns the form with a fresh `formkey` and the recipient pre-added as a hidden `r_<type>` input), fills the `Subject` and `BodyText` fields, and POSTs with the `addsavebtn` "send" button. This is why new messages now work, not only replies.
- The server may need updates if Wilma's web interface changes.

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest
```

## Future Features (Planned)

- Grades and assessments
- Absence/attendance records
- Upcoming exams
- School news/announcements
- Course listings

## License

MIT License - see [LICENSE](LICENSE) file.

## Disclaimer

This is an unofficial project and is not affiliated with or endorsed by Visma. Use at your own risk. Be respectful of Wilma's terms of service and rate limits.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
