"""Offline unit tests for WilmaClient.

These tests use static HTML/JSON fixtures and a mocked ``_request`` so they run
without network access or credentials. They focus on the message-sending path
that was reverse-engineered from Wilma's compose flow: recipient-panel parsing,
name resolution, compose-form assembly, send-result detection, plus message-list
parsing and per-folder routing.
"""

import json

import httpx
import pytest

from wilma_mcp.client import WilmaAPIError, WilmaClient


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

# A trimmed-down copy of Wilma's /messages/recipients side panel. Recipients are
# clickable blocks whose data-source encodes the compose selector. Note the
# HTML-escaped ampersand and the duplicate Fatima block (appears in two tabs).
RECIPIENT_PANEL_HTML = """
<div role="document">
  <ul id="recipients-selected-container"></ul>
  <div id="recp-tab-common">
    <button class="recipient-block"
      data-source="/!0411876/messages/compose?r_guardian=11876_2893&amp;n_class=33">
      Galiana Fatima
    </button>
    <button class="recipient-block"
      data-source="/!0411876/messages/compose?r_ownteachers=11876"
      title="Opettajat: McCrosky Galiana Daniela, 3 C">
      Kaikki opettajat
    </button>
  </div>
  <div id="recp-tab-1">
    <button class="recipient-block"
      data-source="/!0411876/messages/compose?r_personnel=57&amp;n_schools=1">
      Kivi Pilvi (PK)
    </button>
    <button class="recipient-block"
      data-source="/!0411876/messages/compose?r_personnel=12&amp;n_schools=1">
      Kivinen Pekka (PK2)
    </button>
    <!-- duplicate of Fatima from another tab; must be de-duplicated -->
    <button class="recipient-block"
      data-source="/!0411876/messages/compose?r_guardian=11876_2893&amp;n_class=33">
      Galiana Fatima
    </button>
    <a href="/!0411876/help/something">Not a recipient</a>
  </div>
</div>
"""

# A trimmed compose page: a decoy logout form plus the real compose form with the
# recipient (r_guardian) pre-added as a hidden input.
COMPOSE_HTML = """
<html><body>
  <form action="/logout" method="post" id="logout-form">
    <input name="formkey" type="hidden" value="guardian:11876:LOGOUTKEY">
  </form>
  <form action="/!0411876/messages/compose" method="post" class="form-common dock">
    <input name="formkey" type="hidden" value="guardian:11876:REALKEY">
    <input name="wysiwyg" type="hidden" value="ckeditor">
    <input name="Subject" id="wff-Subject" type="text" value="">
    <input name="r_guardian" type="hidden" value="11876_2893">
    <textarea name="BodyText" id="wff-BodyText"></textarea>
    <input type="checkbox" name="ShowRecipients" value="true">
    <input type="checkbox" name="CollatedReplies" value="true" checked>
    <input name="addsavebtn" type="submit" value="Lähetä viesti">
    <input name="draftbtn" type="submit" value="Tallenna luonnos">
    <input name="cancelbtn" type="submit" value="Peruuta">
  </form>
</body></html>
"""

# A reply compose form: recipient is personnel and the subject is pre-filled.
REPLY_COMPOSE_HTML = """
<html><body>
  <form action="/!0411876/messages/compose" method="post">
    <input name="formkey" type="hidden" value="guardian:11876:REPLYKEY">
    <input name="Subject" id="wff-Subject" type="text" value="VS: Retki">
    <input name="r_personnel" type="hidden" value="57">
    <textarea name="BodyText"></textarea>
    <input name="addsavebtn" type="submit" value="Lähetä viesti">
    <input name="draftbtn" type="submit" value="Tallenna luonnos">
  </form>
</body></html>
"""


def make_response(status=200, url="https://school.inschool.fi/!0411876/messages",
                  text="", json_body=None):
    """Build a real httpx.Response whose .url is the given url."""
    if json_body is not None:
        content = json.dumps(json_body).encode()
        headers = {"content-type": "application/json"}
    else:
        content = text.encode()
        headers = {"content-type": "text/html"}
    request = httpx.Request("GET", url)
    return httpx.Response(status, request=request, content=content, headers=headers)


def make_client():
    """A client that is 'already authenticated' so _ensure_authenticated is a no-op."""
    client = WilmaClient("https://school.inschool.fi", "user", "pw")
    client._session_id = "SID"
    client._user_prefix = "/!0411876"
    return client


class Recorder:
    """Records calls and returns queued/branching responses for a mocked _request."""

    def __init__(self, handler):
        self.calls = []
        self._handler = handler

    async def __call__(self, method, path, **kwargs):
        self.calls.append({"method": method, "path": path, "data": kwargs.get("data")})
        return self._handler(method, path, kwargs)


# --------------------------------------------------------------------------- #
# Recipient panel parsing
# --------------------------------------------------------------------------- #

def test_parse_recipient_panel_extracts_selectors_and_dedupes():
    client = make_client()
    recips = client._parse_recipient_panel(RECIPIENT_PANEL_HTML)

    by_name = {r.name: r for r in recips}
    # Fatima appears twice in the HTML but must be de-duplicated by selector.
    assert list(r.name for r in recips).count("Galiana Fatima") == 1

    fatima = by_name["Galiana Fatima"]
    assert fatima.id == "r_guardian=11876_2893&n_class=33"
    assert fatima.role == "Guardian"

    pilvi = by_name["Kivi Pilvi (PK)"]
    assert pilvi.id == "r_personnel=57&n_schools=1"
    assert pilvi.role == "Staff"

    teachers = by_name["Kaikki opettajat"]
    assert teachers.id == "r_ownteachers=11876"
    assert teachers.role == "Teachers"
    # Group blocks keep their descriptive title.
    assert "Daniela" in (teachers.school or "")

    # The plain <a> link is not a recipient.
    assert "Not a recipient" not in by_name


async def test_get_recipients_filters_by_query():
    client = make_client()
    client._request = Recorder(lambda *_: make_response(text=RECIPIENT_PANEL_HTML))

    matches = await client.get_recipients(query="pilvi")
    assert [r.name for r in matches] == ["Kivi Pilvi (PK)"]

    # Filter is a plain substring, case-insensitive.
    kivi = await client.get_recipients(query="kiv")
    assert {r.name for r in kivi} == {"Kivi Pilvi (PK)", "Kivinen Pekka (PK2)"}


# --------------------------------------------------------------------------- #
# Recipient resolution
# --------------------------------------------------------------------------- #

async def test_resolve_selector_passthrough_does_not_hit_network():
    client = make_client()
    # If this touched the network it would raise (no _request mock installed).
    sel = await client._resolve_recipient_selector("r_guardian=11876_2893&n_class=33")
    assert sel == "r_guardian=11876_2893&n_class=33"


async def test_resolve_by_exact_name(monkeypatch):
    client = make_client()
    client._request = Recorder(lambda *_: make_response(text=RECIPIENT_PANEL_HTML))
    sel = await client._resolve_recipient_selector("Galiana Fatima")
    assert sel == "r_guardian=11876_2893&n_class=33"


async def test_resolve_ambiguous_name_raises_with_candidates():
    client = make_client()
    client._request = Recorder(lambda *_: make_response(text=RECIPIENT_PANEL_HTML))
    with pytest.raises(WilmaAPIError) as exc:
        await client._resolve_recipient_selector("Kiv")  # matches Pilvi + Pekka
    msg = str(exc.value)
    assert "ambiguous" in msg.lower()
    assert "Kivi Pilvi (PK)" in msg and "Kivinen Pekka (PK2)" in msg


async def test_resolve_unknown_name_raises():
    client = make_client()
    client._request = Recorder(lambda *_: make_response(text=RECIPIENT_PANEL_HTML))
    with pytest.raises(WilmaAPIError) as exc:
        await client._resolve_recipient_selector("Nobody Here")
    assert "no recipient" in str(exc.value).lower()


# --------------------------------------------------------------------------- #
# Compose form assembly + send-result detection
# --------------------------------------------------------------------------- #

async def test_submit_compose_form_builds_correct_post():
    client = make_client()
    rec = Recorder(lambda *_: make_response(
        url="https://school.inschool.fi/!0411876/messages", text="ok"))
    client._request = rec

    ok = await client._submit_compose_form(
        COMPOSE_HTML, body="Hello there", subject="My subject")
    assert ok is True

    # Posted to the compose form's own action (not the logout form).
    assert rec.calls[0]["method"] == "POST"
    assert rec.calls[0]["path"] == "/!0411876/messages/compose"

    data = rec.calls[0]["data"]
    assert data["formkey"] == "guardian:11876:REALKEY"  # from compose form, not logout
    assert data["Subject"] == "My subject"
    assert data["BodyText"] == "Hello there"
    assert data["r_guardian"] == "11876_2893"
    assert data["wysiwyg"] == "ckeditor"
    # The "send" button must be included...
    assert data["addsavebtn"] == "Lähetä viesti"
    # ...but never the draft/cancel buttons.
    assert "draftbtn" not in data
    assert "cancelbtn" not in data
    # Unchecked checkbox is omitted; the checked one is included.
    assert "ShowRecipients" not in data
    assert data["CollatedReplies"] == "true"


async def test_submit_compose_form_preserves_reply_subject():
    client = make_client()
    rec = Recorder(lambda *_: make_response(
        url="https://school.inschool.fi/!0411876/messages", text="ok"))
    client._request = rec

    # subject=None => keep Wilma's pre-filled "VS:" reply subject.
    await client._submit_compose_form(REPLY_COMPOSE_HTML, body="Reply body", subject=None)
    data = rec.calls[0]["data"]
    assert data["Subject"] == "VS: Retki"
    assert data["BodyText"] == "Reply body"
    assert data["r_personnel"] == "57"


async def test_submit_compose_form_without_recipient_refuses():
    client = make_client()
    client._request = Recorder(lambda *_: make_response())
    html = """
    <form action="/!0411876/messages/compose" method="post">
      <input name="formkey" type="hidden" value="k">
      <input name="Subject" type="text" value="">
      <textarea name="BodyText"></textarea>
      <input name="addsavebtn" type="submit" value="Send">
    </form>
    """
    with pytest.raises(WilmaAPIError) as exc:
        await client._submit_compose_form(html, body="x", subject="y")
    assert "no recipient" in str(exc.value).lower()


def test_check_send_result_success_on_messages_redirect():
    client = make_client()
    resp = make_response(url="https://school.inschool.fi/!0411876/messages")
    assert client._check_send_result(resp) is True


def test_check_send_result_raises_on_compose_redisplay_with_alert():
    client = make_client()
    resp = make_response(
        url="https://school.inschool.fi/!0411876/messages/compose",
        text='<div class="alert alert-danger"><span>Anna aihe</span></div>',
    )
    with pytest.raises(WilmaAPIError) as exc:
        client._check_send_result(resp)
    assert "Anna aihe" in str(exc.value)


# --------------------------------------------------------------------------- #
# send_message end-to-end (mocked network)
# --------------------------------------------------------------------------- #

async def test_send_message_end_to_end_with_selector():
    client = make_client()

    def handler(method, path, kwargs):
        if method == "GET":
            # GET /messages/compose?<selector> returns the pre-filled form.
            assert "r_guardian=11876_2893" in path
            return make_response(text=COMPOSE_HTML)
        return make_response(url="https://school.inschool.fi/!0411876/messages", text="ok")

    rec = Recorder(handler)
    client._request = rec

    ok = await client.send_message(
        recipient="r_guardian=11876_2893&n_class=33",
        subject="Hi", body="Body")
    assert ok is True

    # First a GET to load the compose form, then a POST to send.
    assert rec.calls[0]["method"] == "GET"
    assert rec.calls[1]["method"] == "POST"
    assert rec.calls[1]["data"]["Subject"] == "Hi"
    assert rec.calls[1]["data"]["r_guardian"] == "11876_2893"


# --------------------------------------------------------------------------- #
# Message list parsing + folder routing
# --------------------------------------------------------------------------- #

def test_parse_messages_json_inbox_shows_sender():
    client = make_client()
    data = {"Messages": [
        {"Id": 1, "Subject": "Hi", "Sender": "Kivi Pilvi (PK)",
         "Recipient": "Me", "TimeStamp": "2026-08-07 08:00", "Status": 1},
    ]}
    msgs = client._parse_messages_json(data, "inbox", 20)
    assert msgs[0].sender == "Kivi Pilvi (PK)"
    assert msgs[0].is_read is False  # Status truthy => unread


def test_parse_messages_json_sent_shows_recipient():
    client = make_client()
    data = {"Messages": [
        {"Id": 2, "Subject": "Re", "Sender": "McCrosky Jesse",
         "Recipient": "Galiana Fatima", "TimeStamp": "2026-08-11 10:24"},
    ]}
    msgs = client._parse_messages_json(data, "sent", 20)
    # In sent folder the counterparty shown is the recipient, not the owner.
    assert msgs[0].sender == "Galiana Fatima"
    assert msgs[0].is_read is True  # no Status => read


async def test_get_messages_routes_folders_to_correct_endpoint():
    client = make_client()
    rec = Recorder(lambda *_: make_response(json_body={"Messages": [], "Status": 0}))
    client._request = rec

    await client.get_messages("inbox")
    await client.get_messages("sent")
    await client.get_messages("archive")
    await client.get_messages("drafts")

    paths = [c["path"] for c in rec.calls]
    assert paths == [
        "/messages/list/index_json",
        "/messages/list/outbox",
        "/messages/list/archive",
        "/messages/list/drafts",
    ]


async def test_get_messages_unknown_folder_raises():
    client = make_client()
    client._request = Recorder(lambda *_: make_response(json_body={"Messages": []}))
    with pytest.raises(WilmaAPIError):
        await client.get_messages("bogus")
