"""Tests for the #119 sandbox completion: seccomp filter (119e), egress proxy host
matching (119c), and the engine SBX_* env wiring (119c/119d/119e).

The seccomp test runs a tiny classic-BPF interpreter over the generated program: it
is the regression guard for the fall-through bug where DENY sat in the fall-through
position and EVERY non-denied syscall returned EPERM (the process then SIGSEGV'd).
"""

import importlib.util
from pathlib import Path

from app.core import engine

_DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


def _load(mod_file):
    spec = importlib.util.spec_from_file_location(mod_file.replace("-", "_"),
                                                  _DEPLOY / mod_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------- seccomp (119e)
mkseccomp = _load("make-seccomp.py")
egress = _load("egress-proxy.py")

ALLOW = 0x7FFF0000
ERRNO_EPERM = 0x00050000 | 1
X86_64 = 0xC000003E


def _decode(blob):
    import struct
    return [struct.unpack("<HBBI", blob[i:i + 8]) for i in range(0, len(blob), 8)]


def _run_bpf(ins, nr, arch):
    """Minimal classic-BPF seccomp interpreter for the opcodes the generator emits
    (LD_ABS of nr/arch, JEQ, RET). Returns the action constant the filter yields."""
    a, pc = 0, 0
    for _ in range(10_000):
        code, jt, jf, k = ins[pc]
        if code == 0x20:                 # BPF_LD|W|ABS
            a = arch if k == 4 else (nr if k == 0 else 0)
            pc += 1
        elif code == 0x15:               # BPF_JMP|JEQ|K
            pc += 1 + (jt if a == k else jf)
        elif code == 0x06:               # BPF_RET|K
            return k
        else:                            # pragma: no cover
            raise AssertionError(f"unknown opcode {code:#x}")
    raise AssertionError("no RET reached")  # pragma: no cover


def test_seccomp_blob_is_well_formed():
    blob = mkseccomp.build(mkseccomp.DENY_X86_64)
    assert len(blob) % 8 == 0
    ins = _decode(blob)
    # ALLOW must be the fall-through sink (second-to-last); DENY (ERRNO) the last,
    # reached only by an explicit jump. Get this wrong and everything returns EPERM.
    assert ins[-2] == (0x06, 0, 0, ALLOW)
    assert ins[-1] == (0x06, 0, 0, ERRNO_EPERM)


def test_seccomp_denies_only_the_denylist():
    ins = _decode(mkseccomp.build(mkseccomp.DENY_X86_64))
    # Common syscalls (write=1, mmap=9, getpid=39, execve=59) MUST be allowed —
    # the exact class the fall-through bug broke.
    for nr in (0, 1, 9, 10, 39, 59, 231, 257):
        assert _run_bpf(ins, nr, X86_64) == ALLOW, f"syscall {nr} wrongly denied"
    # Every denylisted syscall is refused with EPERM on x86_64.
    for nr in mkseccomp.DENY_X86_64:
        assert _run_bpf(ins, nr, X86_64) == ERRNO_EPERM, f"syscall {nr} not denied"
    # On a non-x86_64 arch we ALLOW (we only know x86_64 numbers).
    assert _run_bpf(ins, 248, 0xDEADBEEF) == ALLOW


# ----------------------------------------------------------- egress proxy (119c)
def test_host_allowlist_suffix_match():
    allow = frozenset({"github.com", "pypi.org"})
    assert egress._host_allowed("github.com", allow)
    assert egress._host_allowed("api.github.com", allow)       # dot-suffix
    assert egress._host_allowed("files.pypi.org", allow)
    assert not egress._host_allowed("evilgithub.com", allow)   # not a dot-suffix
    assert not egress._host_allowed("github.com.evil.com", allow)
    assert not egress._host_allowed("example.com", allow)


# --------------------------------------------------- engine SBX_* env (119c/d/e)
def _enabled_env(cwd, **kw):
    s = engine.ClaudeSession(mode="code", model="claude-opus-4-8", cwd=cwd,
                             sandbox=True, **kw)
    common = {}
    s._enable_sandbox(common)
    return common


def test_enable_sandbox_sets_egress_limits_seccomp(tmp_path):
    blob = tmp_path / "s.bpf"
    blob.write_bytes(b"\x00" * 8)
    cwd = str(tmp_path / "sid" / "work")
    common = _enabled_env(
        cwd, egress=True, egress_proxy_url="http://127.0.0.1:8790",
        sbx_mem_max="536870912", sbx_cpu_max="150000 100000", sbx_pids_max=256,
        seccomp_path=str(blob),
    )
    env = common["env"]
    assert env["SBX_EGRESS"] == "1"
    assert env["SBX_PROXY_URL"] == "http://127.0.0.1:8790"
    assert env["SBX_USE_CGROUP"] == "1"          # egress/limits need the cgroup
    assert env["SBX_MEM_MAX"] == "536870912"
    assert env["SBX_CPU_MAX"] == "150000 100000"
    assert env["SBX_PIDS_MAX"] == "256"
    assert env["SBX_SECCOMP"] == str(blob)
    # #119d: the per-session secrets file is ALWAYS pointed at <sid>/secrets.env.
    assert env["SBX_SECRETS_ENV"].endswith("/sid/secrets.env")
    assert common["cli_path"].endswith("sandbox-claude.sh")


def test_enable_sandbox_no_egress_no_cgroup(tmp_path):
    cwd = str(tmp_path / "sid" / "work")
    env = _enabled_env(cwd)["env"]
    assert "SBX_EGRESS" not in env
    assert "SBX_USE_CGROUP" not in env           # nothing requested → no cgroup placement
    assert "SBX_SECCOMP" not in env
    assert env["SBX_SECRETS_ENV"].endswith("/sid/secrets.env")  # still set (119d)


def test_enable_sandbox_seccomp_path_must_exist(tmp_path):
    cwd = str(tmp_path / "sid" / "work")
    env = _enabled_env(cwd, seccomp_path=str(tmp_path / "missing.bpf"))["env"]
    assert "SBX_SECCOMP" not in env              # a non-existent blob is not forwarded


def test_per_session_uid_deterministic_in_range(tmp_path):
    cwd = str(tmp_path / "abc123" / "work")   # 'abc123' parses as hex (a real sid digest)
    e1 = _enabled_env(cwd, per_session_uid=True, uid_base=700000, uid_range=1000)["env"]
    e2 = _enabled_env(cwd, per_session_uid=True, uid_base=700000, uid_range=1000)["env"]
    assert e1["SBX_HOST_UID"] == e2["SBX_HOST_UID"]      # stable per session (chown stays valid)
    assert e1["SBX_HOST_GID"] == e1["SBX_HOST_UID"]
    assert 700000 <= int(e1["SBX_HOST_UID"]) < 701000
    assert "SBX_HOST_UID" not in _enabled_env(cwd)["env"]  # off by default


def test_chat_session_skips_egress_but_keeps_broker(tmp_path):
    blob = tmp_path / "s.bpf"
    blob.write_bytes(b"\x00" * 8)
    s = engine.ClaudeSession(
        mode="chat", model="claude-opus-4-8", cwd=str(tmp_path / "sid" / "work"),
        sandbox=True, egress=True, egress_proxy_url="http://127.0.0.1:8790",
        sbx_mem_max="536870912", cred_broker_url="http://127.0.0.1:8789",
        seccomp_path=str(blob),
    )
    common = {}
    s._enable_sandbox(common)
    env = common["env"]
    # egress + cgroup limits are CODE-only (chat has no Bash exfil surface + needs WebFetch)
    assert "SBX_EGRESS" not in env
    assert "SBX_USE_CGROUP" not in env
    assert "SBX_MEM_MAX" not in env
    # the broker (token out of EVERY jail) + seccomp + secrets still apply to chat
    assert env["SBX_BROKER_URL"] == "http://127.0.0.1:8789"
    assert env["SBX_SECCOMP"] == str(blob)
    assert env["SBX_SECRETS_ENV"].endswith("/sid/secrets.env")


# ------------------------------------------------------ cred-broker path allowlist (119b)
_broker = _load("cred-broker.py")


def test_cred_broker_path_allowlist():
    """#234: the inbound path allowlist matches by path segment, not a bare prefix —
    only `/v1/messages` itself and `/v1/messages/...` sub-paths pass, never a sibling
    like `/v1/messages_evil`. The query string is ignored."""
    f = _broker._path_allowed
    # allowed: the exact path, sub-paths (e.g. count_tokens), and with a query string
    assert f("POST", "/v1/messages") is True
    assert f("POST", "/v1/messages/count_tokens") is True
    assert f("POST", "/v1/messages?beta=true") is True
    # blocked: a bare-prefix sibling that the old startswith() let through, a different
    # method, and an unrelated path
    assert f("POST", "/v1/messages_evil") is False
    assert f("POST", "/v1/messagesX") is False
    assert f("GET", "/v1/messages") is False
    assert f("POST", "/v1/other") is False
