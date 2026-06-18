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


# --- #212: Bash risk classifier for the relaxed acceptEdits default ----------
# Must auto-run ordinary in-jail work, still prompt push-class / outbound-with-creds
# and destructive ops, and fail SAFE — the #119 jail backstops whatever slips past.

_SAFE = [
    "ls -la", "cat readme.md", "grep -rn foo .", "pytest -q",
    "python -m py_compile bot.py", "python bot.py", "npm test", "npm install",
    "make build", "git status", "git diff HEAD~1", "git log --oneline -20",
    "git add -A", 'git commit -m "wip"',
    "git checkout -b feature",            # new branch — not a discard
    "git clean -n",                       # dry run only
    "rm -f scratch.txt",                  # single-file force-remove, no recursion
    "mkdir -p build && cd build",
    "curl http://127.0.0.1:8000/health",  # loopback — egress backstops the rest
    "rsync -a ./src ./dst",               # local rsync
    "echo done", "", "   ",
]

_DANGEROUS = [
    # push-class / outbound with the user's credentials
    "git push", "git push --force origin main", "cd repo && git push",
    "gh pr create --fill", "gh release upload v1 ./dist/x", "npm publish",
    "pnpm publish --access public", "twine upload dist/x", "docker push reg/img:tag",
    "ssh user@host 'echo hi'", "scp ./secret user@host:/tmp/",
    "rsync -a ./ user@host:/backup",      # remote target
    # destructive: irreversible loss of in-workdir work
    "rm -rf build", "rm -fr node_modules", "sudo rm -r /var/lib/x",
    "git reset --hard origin/main", "git clean -fd", "git restore .",
    "git checkout -- src/app.py", "git checkout .",
    "dd if=/dev/zero of=disk.img", "mkfs.ext4 /dev/sdb", "truncate -s 0 important.log",
]


def test_safe_commands_auto_run():  # #212
    for cmd in _SAFE:
        assert permissions._bash_needs_approval(cmd) is False, f"should auto-run: {cmd!r}"


def test_dangerous_commands_prompt():  # #212
    for cmd in _DANGEROUS:
        assert permissions._bash_needs_approval(cmd) is True, f"should prompt: {cmd!r}"


def test_none_and_empty_do_not_prompt():  # #212
    assert permissions._bash_needs_approval(None) is False
    assert permissions._bash_needs_approval("") is False
