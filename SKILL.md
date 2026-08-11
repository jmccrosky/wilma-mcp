---
name: wilma-mcp
description: Access the Finnish school platform Wilma via CLI - view schedules, read and send messages to teachers, and list recipients. Use when the user asks about school schedules, classes, homework, or wants to communicate with teachers through Wilma.
homepage: https://github.com/jessemc98/wilma-mcp
metadata: {"openclaw":{"emoji":"🏫","requires":{"bins":["python3"],"env":["WILMA_BASE_URL","WILMA_USERNAME","WILMA_PASSWORD"]}}}
---

# Wilma CLI

Access the [Wilma](https://www.visma.com/wilma) Finnish school communication platform. View schedules, read messages, send messages to teachers, and more.

## How to Use

Run commands using the `wilma-cli` entry point (or `python -m wilma_mcp.cli`):

```bash
cd /path/to/wilma-mcp && source venv/bin/activate && wilma-cli <command> [args]
```

Or in one line without activating the venv:

```bash
/path/to/wilma-mcp/venv/bin/python -m wilma_mcp.cli <command> [args]
```

The CLI reads credentials from environment variables or a `.env` file in the wilma-mcp directory.

## Commands

### Check schedule

```bash
# Today's schedule
wilma-cli schedule

# Specific date
wilma-cli schedule tomorrow
wilma-cli schedule monday
wilma-cli schedule 2026-03-15

# Full week
wilma-cli week
wilma-cli week monday
```

Output example:
```
Schedule for Wednesday, February 12, 2026:
  08:00-08:45: Math (Room: 204) - Smith J.
  09:00-09:45: English (Room: 301) - Johnson A.
```

### List messages

```bash
# Inbox (default)
wilma-cli messages

# Specific folder and limit
wilma-cli messages --folder sent      # sent/drafts show the recipient ("To:")
wilma-cli messages --folder archive
wilma-cli messages --folder drafts
wilma-cli messages --folder inbox --limit 5
```

Output example:
```
Messages in inbox (3 shown):

[12345] (UNREAD) Homework for Monday
   From: Smith J. | 2026-02-11 14:30

[12340] (READ) Field trip permission
   From: Johnson A. | 2026-02-10 09:15
```

### Read a message

```bash
wilma-cli message 12345
```

Output example:
```
Subject: Homework for Monday
From: Smith J.
Date: 2026-02-11 14:30

---

Please complete exercises 1-5 on page 42.
```

**Note:** Viewing a message automatically marks it as read on the Wilma server.

### Mark a message as read

```bash
wilma-cli mark-read 12345
```

### List recipients

```bash
# All recipients
wilma-cli recipients

# Filter by name (recommended - the full list can be long)
wilma-cli recipients Smith
```

Output example:
```
Available Recipients:

  Smith John (Teacher)
      id: r_personnel=101&n_schools=1
  Johnson Anna (Teacher)
      id: r_personnel=102&n_schools=1
```

The `id` string is what you pass to `send`.

### Send a message

```bash
wilma-cli send <recipient> <subject> <body>
```

`<recipient>` can be either a **name** or an **id** from `recipients`:

```bash
# By name (resolved automatically against the recipient list)
wilma-cli send "Smith John" "Question about homework" "Could you clarify exercise 3?"

# By id (unambiguous - use this if a name matches more than one person)
wilma-cli send "r_personnel=101&n_schools=1" "Question about homework" "Could you clarify exercise 3?"
```

If a name is ambiguous, the command lists the matches so you can pick a specific id. Tip: run `wilma-cli recipients <name>` first when unsure.

### Reply to a message

```bash
wilma-cli reply <message_id> <body>

# Example:
wilma-cli reply 12345 "Thank you, I understand now."
```

This is the preferred way to reply - it automatically handles recipient resolution.

## Setup

### 1. Install

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

### 3. Verify it works

```bash
source venv/bin/activate
wilma-cli schedule
```

## MCP Server (for Claude Code)

This project also provides an MCP server for direct integration with Claude Code. Add to your Claude Code MCP settings (`~/.claude.json` or project `.mcp.json`):

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

## Important Notes

- **Read/unread status**: Messages show as `(READ)` or `(UNREAD)` in `messages`. Viewing a message with `message <id>` automatically marks it as read. Wilma does not support marking messages as unread.
- Use `reply` to reply to existing messages - it handles recipients automatically.
- `send` accepts a recipient **name** or an **id** from `recipients`. Passing a name is convenient; passing an id is unambiguous. If a name matches more than one person, `send` lists the matches instead of guessing.
- Wilma has no official API; this uses reverse-engineered web endpoints that may change.
- Supports Finnish language date inputs: "tänään", "huomenna", "maanantai", etc.
