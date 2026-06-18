"""Unit tests for permissions: the tool-approval input preview, focused on the
#204 workdir-relative path rendering."""

import permissions


CWD = "/var/lib/claude-tg-bot/workdirs/fca29e/work"


def test_rel_to_cwd_in_workdir_is_relativized():  # #204
    assert permissions._rel_to_cwd(f"{CWD}/readme.md", CWD) == "readme.md"
    assert permissions._rel_to_cwd(f"{CWD}/src/app.py", CWD) == "src/app.py"


def test_rel_to_cwd_outside_workdir_stays_absolute():  # #204
    # A tool reaching OUT of the sandbox must stay conspicuous (full path).
    assert permissions._rel_to_cwd("/etc/passwd", CWD) == "/etc/passwd"


def test_rel_to_cwd_no_cwd_or_relative_input_is_unchanged():  # #204
    assert permissions._rel_to_cwd("/etc/hosts", None) == "/etc/hosts"
    assert permissions._rel_to_cwd("already/relative.md", CWD) == "already/relative.md"


def test_preview_input_relativizes_edit_path_but_not_bash():  # #204
    assert permissions._preview_input(
        "Edit", {"file_path": f"{CWD}/readme.md"}, CWD
    ) == "readme.md"
    # Bash commands are previewed verbatim (paths inside a command are not rewritten).
    cmd = f"cat {CWD}/readme.md"
    assert permissions._preview_input("Bash", {"command": cmd}, CWD) == cmd
