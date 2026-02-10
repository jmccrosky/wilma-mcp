---
name: wilma-mcp
description: Access the Finnish school platform Wilma via MCP - view schedules, read and send messages to teachers, and list recipients. Use when the user asks about school schedules, classes, homework, or wants to communicate with teachers through Wilma.
homepage: https://github.com/jessemc98/wilma-mcp
metadata: {"openclaw":{"emoji":"🏫","requires":{"bins":["python3"],"env":["WILMA_BASE_URL","WILMA_USERNAME","WILMA_PASSWORD"]}}}
---

# Wilma MCP

Access the [Wilma](https://www.visma.com/wilma) Finnish school communication platform. View schedules, read messages, send messages to teachers, and more.

## Setup

### 1. Install the MCP server

```bash
git clone https://github.com/jessemc98/wilma-mcp.git
cd wilma-mcp
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

### 2. Configure credentials

Create a `.env` file in the `wilma-mcp` directory:

```
WILMA_BASE_URL=https://yourschool.inschool.fi
WILMA_USERNAME=your_username
WILMA_PASSWORD=your_password
```

### 3. Add MCP server to Claude Code

Add to your Claude Code MCP settings (`~/.claude.json` or project `.mcp.json`):

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

## Available Tools

### `get_schedule`
Get the school schedule for a specific date.
- `date_str` (optional): "today", "tomorrow", "yesterday", weekday names (English or Finnish), or dates like "2024-03-15" or "15.3.2024"

### `get_week_schedule`
Get the full week's schedule starting from a given date.
- `start_date` (optional): Start date of the week, defaults to today

### `get_messages`
List messages from a folder. Each message shows a read/unread indicator (📖 read, 📬 unread).
- `folder` (optional): "inbox", "sent", or "archive" (default: "inbox")
- `limit` (optional): Max messages to return (default: 20)

### `get_message`
Read a specific message with full content. Note: viewing a message automatically marks it as read on the Wilma server.
- `message_id` (required): ID of the message to read

### `set_message_read`
Explicitly mark a message as read. Wilma does not support marking messages as unread — this is a limitation of the platform, not this tool.
- `message_id` (required): ID of the message to mark as read

### `get_recipients`
List available message recipients (teachers, staff) and their IDs.

### `send_message`
Send a new message to a teacher or staff member.
- `recipient_id` (required): Recipient ID from `get_recipients`
- `subject` (required): Message subject
- `body` (required): Message content
- `reply_to_id` (optional): Message ID if replying

### `reply_to_message`
Reply to an existing message. This is the preferred way to reply since it handles recipient resolution automatically via Wilma's reply form.
- `message_id` (required): ID of the message to reply to (from `get_messages`)
- `body` (required): Reply message content

## Example Prompts

- "What's my schedule today?"
- "Show me next week's schedule"
- "Check my inbox for new messages"
- "Read message 12345"
- "Reply to message 12345 saying I'll be there"
- "Who can I send messages to?"
- "Send a message to my math teacher about tomorrow's homework"
- "Do I have any classes on Friday?"
- "What time does school start tomorrow?"

## Important Notes

- **Read/unread status**: Messages show as 📖 (read) or 📬 (unread) in `get_messages`. Viewing a message with `get_message` automatically marks it as read. You can also explicitly mark a message as read with `set_message_read`. Wilma does not support marking messages as unread.
- Use `reply_to_message` to reply to existing messages - it handles recipients automatically.
- Use `get_recipients` before `send_message` when composing new messages.
- Wilma has no official API; this uses reverse-engineered web endpoints that may change.
- Supports Finnish language date inputs: "tänään", "huomenna", "maanantai", etc.
