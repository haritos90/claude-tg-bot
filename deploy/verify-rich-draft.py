#!/usr/bin/env python3
"""Live verifier for rich-message drafts, tables, and final handoff.

- calls the Bot API directly with stdlib `urllib`, no aiogram
- isolates draft behavior from the bot's streamer pipeline
- markdown tables need complete rows; partial is invalid
- `<tg-thinking>` is draft-only; final send is `sendRichMessage`
- usage: `python3 deploy/verify-rich-draft.py` with `--thinking`, `--html`, `--wide`
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

DRAFT_ID = 424242  # non-zero; reused so frames animate

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


# Table built the way the bot streams it.
# - intro prose, header, separator, then one row per frame
# - each frame is a valid markdown prefix
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
    # Header alone: no separator, so a plain text line.
    frames.append(f"{INTRO}\n\n{HEADER}")
    # Header plus separator: valid table with an empty body.
    # - the bot shows this state transiently
    # - confirm it renders header-only, not as broken text
    frames.append(f"{INTRO}\n\n{HEADER}\n{SEP}")
    # Add one complete row per frame.
    acc = f"{INTRO}\n\n{HEADER}\n{SEP}"
    for r in ROWS:
        acc = f"{acc}\n{r}"
        frames.append(acc)
    frames.append(f"{acc}\n\nDone — now finalized with sendRichMessage.")
    return frames


def _wide_markdown(ncols: int = 21) -> str:
    """Markdown table with `ncols` columns, default 21.

    - one over the documented 20-column limit
    - shows whether the client rejects, truncates or converts to image
    """
    header = "| " + " | ".join(f"C{i + 1}" for i in range(ncols)) + " |"
    sep = "|" + "|".join([":--"] * ncols) + "|"
    row1 = "| " + " | ".join(f"r1c{i + 1}" for i in range(ncols)) + " |"
    row2 = "| " + " | ".join(f"r2c{i + 1}" for i in range(ncols)) + " |"
    intro = f"Over-limit check — this table has **{ncols} columns** (limit is 20):"
    return f"{intro}\n\n{header}\n{sep}\n{row1}\n{row2}"


def _html_table() -> str:
    cells = "".join(f"<th>{h.strip()}</th>" for h in HEADER.strip("|").split("|"))
    rows = "<tr>" + cells + "</tr>"
    for r in ROWS:
        tds = "".join(f"<td>{c.strip()}</td>" for c in r.strip("|").split("|"))
        rows += "<tr>" + tds + "</tr>"
    return f"{INTRO}\n<table bordered striped>{rows}</table>\nDone — finalized."


def _math_markdown() -> str:
    """Reply mixing inline and block LaTeX math."""
    return (
        "Euler's identity: $e^{i\\pi}+1=0$.\n\n"
        "A definite integral as a block formula:\n"
        "$$\\int_0^1 x^2\\,dx = \\frac{1}{3}$$\n"
        "Done — finalized."
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", type=int, default=0, help="target chat id (default: OWNER_ID)")
    ap.add_argument("--step", type=float, default=0.7, help="seconds between draft frames")
    ap.add_argument("--math", action="store_true",
                    help="verify $…$ inline + $$…$$ block math (draft snap + parsed blocks)")
    ap.add_argument("--thinking", action="store_true",
                    help="open with a <tg-thinking> draft (draft-only block)")
    ap.add_argument("--html", action="store_true",
                    help="use the HTML <table> form instead of markdown")
    ap.add_argument("--wide", action="store_true",
                    help="send a >20-column table (default 21) to verify over-limit behavior")
    ap.add_argument("--cols", type=int, default=21, help="column count for --wide (default 21)")
    args = ap.parse_args()

    token = _env("TELEGRAM_BOT_TOKEN")
    chat = args.chat or int(_env("OWNER_ID"))
    print(f"Target chat: {chat}  step: {args.step}s  "
          f"form: {'html' if args.html else 'markdown'}  thinking: {args.thinking}")

    if args.thinking:
        # `<tg-thinking>` is valid only in drafts, never the final.
        print("thinking draft:")
        _draft(token, chat, markdown="<tg-thinking>Generating…</tg-thinking>")
        time.sleep(args.step)

    if args.math:
        # Inline `$…$` and block `$$…$$` map to math blocks.
        # - stream a partial frame with an unclosed `$$`
        # - expect literal text, then a snap to the formula
        # - dump server-parsed blocks to confirm the mapping
        full = _math_markdown()
        partial = full.split("$$")[0] + "$$\\int_0^1 x^2"   # unclosed block at the frontier
        print("math: partial (unclosed $$) draft, then the complete message:")
        _draft(token, chat, markdown=partial)
        time.sleep(args.step)
        _draft(token, chat, markdown=full)
        time.sleep(args.step)
        out = _call(token, "sendRichMessage",
                    {"chat_id": chat, "rich_message": {"markdown": full}})
        blocks = out.get("result", {}).get("rich_message", {}).get("blocks") if out.get("ok") else out
        print("parsed blocks:", json.dumps(blocks, ensure_ascii=False)[:700])
        print("expect: an inline 'mathematical_expression' in the first paragraph + a block one.")
        return

    if args.wide:
        # Send an over-20-column table draft and final.
        full = _wide_markdown(args.cols)
        print(f"wide table: {args.cols} columns (limit 20) — draft then final:")
        _draft(token, chat, markdown=full)
        time.sleep(args.step)
        _final(token, chat, markdown=full)
        print("done — report: did the API reject it, truncate to 20 columns, or show an image?")
        return

    if args.html:
        # HTML form streams the whole table per frame.
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
