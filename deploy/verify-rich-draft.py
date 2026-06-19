#!/usr/bin/env python3
"""#237 — live verifier for rich-message drafts, tables, and the draft→final handoff.

Calls the Telegram Bot API DIRECTLY (stdlib urllib — NO aiogram, NO streamer.py, NO the
/test demo), so it isolates the rich-draft/table behavior from the rest of the bot:

  - if a glitch (empty table body, a full disappear→reappear at finalize) reproduces HERE,
    it is the draft model / client / our message SHAPE — NOT aiogram or our streamer/clip;
  - if it does NOT reproduce here but does in the bot, the bug is in our pipeline.

Ground truth: see ../rich-message-spec.md (extracted verbatim from the official docs).
Key facts this exercises:
  - sendRichMessageDraft: ephemeral ~30s preview; draft_id MUST be non-zero; same draft_id
    animates; private chat only. InputRichMessage = exactly one of {"markdown"} / {"html"}.
  - This bot streams + persists with the MARKDOWN form ({"markdown": …}); HTML is only for
    menus + the native-table fallback. So we test the markdown form by default.
  - A markdown table needs header + separator (|:--|) + COMPLETE rows; a partial row is
    invalid GFM (renders as the header line alone) — hence we only ever send valid prefixes.
  - <tg-thinking>…</tg-thinking> (RichBlockThinking) is draft-ONLY; never in the final send.
  - finish = sendRichMessage with the COMPLETE message (the draft does not persist itself).

Usage (run on the host; reads TELEGRAM_BOT_TOKEN + OWNER_ID from ../.env):
    python3 deploy/verify-rich-draft.py                 # markdown table, draft→final
    python3 deploy/verify-rich-draft.py --thinking      # open with a <tg-thinking> draft
    python3 deploy/verify-rich-draft.py --html          # same table via the HTML <table> form
    python3 deploy/verify-rich-draft.py --wide          # #243: a 21-column table (over the 20 limit)
    python3 deploy/verify-rich-draft.py --wide --cols 25
    python3 deploy/verify-rich-draft.py --chat 12345    # target chat (default: OWNER_ID)
    python3 deploy/verify-rich-draft.py --step 0.7      # seconds between draft frames

Watch the chat and report: does the table fill ROW-BY-ROW, and does the message stay put at
finalize (no disappear→reappear)?  Sending via the bot token while the service polls is fine
(only getUpdates conflicts, not sendMessage).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

DRAFT_ID = 424242  # non-zero; reused so Telegram animates successive frames

_ENV = Path(__file__).resolve().parent.parent / ".env"


def _env(key: str) -> str:
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{key} not found in {_ENV}")


def _call(token: str, method: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _draft(token: str, chat: int, markdown: str | None = None, html: str | None = None) -> None:
    rich = {"markdown": markdown} if markdown is not None else {"html": html}
    out = _call(token, "sendRichMessageDraft",
                {"chat_id": chat, "draft_id": DRAFT_ID, "rich_message": rich})
    print(f"  draft -> ok={out.get('ok')} {('' if out.get('ok') else out)}")


def _final(token: str, chat: int, markdown: str | None = None, html: str | None = None) -> None:
    rich = {"markdown": markdown} if markdown is not None else {"html": html}
    out = _call(token, "sendRichMessage", {"chat_id": chat, "rich_message": rich})
    print(f"  FINAL sendRichMessage -> ok={out.get('ok')} {('' if out.get('ok') else out)}")


# A small table built up the way the bot streams it: intro prose, then header, then the
# separator, then one COMPLETE data row at a time (each frame a valid markdown prefix).
HEADER = "| Address | Opcode | Mnemonic |"
SEP = "|:--------|:-------|:---------|"
ROWS = [
    "| 0x401000 | 55       | push ebp |",
    "| 0x401001 | 8B EC    | mov ebp,esp |",
    "| 0x401003 | 83 EC 10 | sub esp,0x10 |",
]
INTRO = "Rich-draft verifier — the table below should fill in **row by row**:"


def _markdown_frames() -> list[str]:
    frames = [INTRO]
    # header alone (no separator yet → not a valid table; renders as a text line)
    frames.append(f"{INTRO}\n\n{HEADER}")
    # header + separator → a valid but EMPTY-body table (this is the state the bot shows
    # transiently; confirm it renders as a header-only table, not as broken text)
    frames.append(f"{INTRO}\n\n{HEADER}\n{SEP}")
    # add one complete row per frame
    acc = f"{INTRO}\n\n{HEADER}\n{SEP}"
    for r in ROWS:
        acc = f"{acc}\n{r}"
        frames.append(acc)
    frames.append(f"{acc}\n\nDone — now finalized with sendRichMessage.")
    return frames


def _wide_markdown(ncols: int = 21) -> str:
    """#243: a markdown table with `ncols` columns (default 21 — one over the documented
    20-column limit). Use this to verify what the client does with an over-limit table:
    reject the send, truncate to 20, or auto-convert to an image."""
    header = "| " + " | ".join(f"C{i + 1}" for i in range(ncols)) + " |"
    sep = "|" + "|".join([":--"] * ncols) + "|"
    row1 = "| " + " | ".join(f"r1c{i + 1}" for i in range(ncols)) + " |"
    row2 = "| " + " | ".join(f"r2c{i + 1}" for i in range(ncols)) + " |"
    intro = f"#243 over-limit check — this table has **{ncols} columns** (limit is 20):"
    return f"{intro}\n\n{header}\n{sep}\n{row1}\n{row2}"


def _html_table() -> str:
    cells = "".join(f"<th>{h.strip()}</th>" for h in HEADER.strip("|").split("|"))
    rows = "<tr>" + cells + "</tr>"
    for r in ROWS:
        tds = "".join(f"<td>{c.strip()}</td>" for c in r.strip("|").split("|"))
        rows += "<tr>" + tds + "</tr>"
    return f"{INTRO}\n<table bordered striped>{rows}</table>\nDone — finalized."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", type=int, default=0, help="target chat id (default: OWNER_ID)")
    ap.add_argument("--step", type=float, default=0.7, help="seconds between draft frames")
    ap.add_argument("--thinking", action="store_true",
                    help="open with a <tg-thinking> draft (draft-only block)")
    ap.add_argument("--html", action="store_true",
                    help="use the HTML <table> form instead of markdown")
    ap.add_argument("--wide", action="store_true",
                    help="#243: send a >20-column table (default 21) to verify over-limit behavior")
    ap.add_argument("--cols", type=int, default=21, help="column count for --wide (default 21)")
    args = ap.parse_args()

    token = _env("TELEGRAM_BOT_TOKEN")
    chat = args.chat or int(_env("OWNER_ID"))
    print(f"Target chat: {chat}  step: {args.step}s  "
          f"form: {'html' if args.html else 'markdown'}  thinking: {args.thinking}")

    if args.thinking:
        # <tg-thinking> is valid ONLY in a draft; it must NOT appear in the final message.
        print("thinking draft:")
        _draft(token, chat, markdown="<tg-thinking>Generating…</tg-thinking>")
        time.sleep(args.step)

    if args.wide:
        # #243: send an over-limit (>20-col) table draft + final and report what the client does.
        full = _wide_markdown(args.cols)
        print(f"wide table: {args.cols} columns (limit 20) — draft then final:")
        _draft(token, chat, markdown=full)
        time.sleep(args.step)
        _final(token, chat, markdown=full)
        print("done — report: did the API reject it, truncate to 20 columns, or show an image?")
        return

    if args.html:
        # HTML form streams the whole <table> as one valid block per frame.
        full = _html_table()
        print("html drafts (whole table grows is not row-wise here — sent once):")
        _draft(token, chat, html=full)
        time.sleep(args.step)
        print("finalizing:")
        _final(token, chat, html=full)
        return

    frames = _markdown_frames()
    print(f"streaming {len(frames)} markdown draft frames:")
    for i, f in enumerate(frames):
        last = f.split("\n")[-1][:48]
        print(f"  [{i + 1}/{len(frames)}] …{last!r}")
        _draft(token, chat, markdown=f)
        time.sleep(args.step)
    print("finalizing (sendRichMessage with the complete message):")
    _final(token, chat, markdown=frames[-1])
    print("done — watch the chat: did the table fill row-by-row and stay put at finalize?")


if __name__ == "__main__":
    sys.exit(main())
