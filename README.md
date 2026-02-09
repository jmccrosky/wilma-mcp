# Wilma MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server for [Wilma](https://www.visma.com/wilma) - the Finnish school communication platform by Visma. This allows Claude and other MCP-compatible AI assistants to interact with school data including schedules, messages, and more.

## Features

- **Schedule** - View daily or weekly timetables with subjects, times, and teachers
- **Messages** - Read inbox messages and view full message content
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
Get list of messages from inbox.

**Parameters:**
- `folder` (optional): Folder name - "inbox", "sent", or "archive". Defaults to "inbox".
- `limit` (optional): Maximum messages to return. Defaults to 20.

**Example:** "Check my messages"

### `get_message`
Read a specific message with full content.

**Parameters:**
- `message_id`: The ID of the message to read.

**Example:** "Read message 12345"

### `get_recipients`
Get list of available message recipients (teachers, staff).

**Example:** "Who can I send messages to?"

### `send_message`
Send a message to a teacher or staff member.

**Parameters:**
- `recipient_id`: ID of the recipient (use `get_recipients` to find IDs)
- `subject`: Message subject
- `body`: Message body/content
- `reply_to_id` (optional): Message ID if this is a reply

**Example:** "Send a message to teacher 123 about homework"

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
- Message lists use a JSON endpoint; individual messages require HTML parsing.
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
