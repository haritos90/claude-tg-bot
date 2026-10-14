#!/usr/bin/env python3
"""Seccomp BPF generator shrinking the jail's kernel attack surface.

- denylist returning EPERM for rarely needed risky syscalls
- default allow, so ordinary dev tools keep working
- emits raw `struct sock_filter` array for bwrap `--seccomp`
- x86_64 only; other arches write nothing and exit 0
- usage: `make-seccomp.py <out-path>`
"""

import contextlib
import os
import platform
import struct
import sys

# BPF opcodes and seccomp ABI constants.
BPF_LD, BPF_W, BPF_ABS = 0x00, 0x00, 0x20
BPF_JMP, BPF_JEQ, BPF_K = 0x05, 0x10, 0x00
BPF_RET = 0x06
AUDIT_ARCH_X86_64 = 0xC000003E
SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_ERRNO = 0x00050000
EPERM = 1
# Offsets in `struct seccomp_data`: nr at 0, arch at 4.
OFF_NR, OFF_ARCH = 0, 4

# x86_64 syscall numbers to refuse.
# - never needed by dev workloads
# - each materially widens the host attack surface
DENY_X86_64 = {
    101: "ptrace", 155: "pivot_root", 156: "_sysctl",
    159: "adjtimex", 163: "acct", 164: "settimeofday",
    165: "mount", 166: "umount2", 167: "swapon", 168: "swapoff", 169: "reboot",
    174: "create_module", 175: "init_module", 176: "delete_module",
    177: "get_kernel_syms", 178: "query_module", 179: "quotactl",
    227: "clock_settime", 246: "kexec_load", 248: "add_key", 249: "request_key",
    250: "keyctl", 298: "perf_event_open", 304: "open_by_handle_at",
    305: "clock_adjtime", 313: "finit_module", 320: "kexec_file_load",
    321: "bpf", 323: "userfaultfd",
}


def _stmt(code, k):
    return struct.pack("<HBBI", code, 0, 0, k)


def _jeq(k, jt, jf):
    return struct.pack("<HBBI", BPF_JMP | BPF_JEQ | BPF_K, jt, jf, k)


def build(deny) -> bytes:
    """Assemble the filter: arch check, JEQ chain, ALLOW, DENY.

    - a match jumps to DENY; a miss falls through
    - ALLOW must be the fall-through sink, DENY jump-only
    - wrong order makes every syscall return EPERM
    - jump offsets are PC-relative from the next instruction
    """
    nrs = sorted(deny)
    m = len(nrs)
    # Layout: [0]=LD arch [1]=JEQ x86_64 [2]=LD nr [3..2+m]=checks [3+m]=ALLOW [4+m]=DENY
    allow_idx = 3 + m
    deny_idx = 4 + m
    prog = bytearray()
    prog += _stmt(BPF_LD | BPF_W | BPF_ABS, OFF_ARCH)
    # Other arch: fall through to ALLOW (x86_64 numbers only).
    prog += _jeq(AUDIT_ARCH_X86_64, 0, allow_idx - 2)
    prog += _stmt(BPF_LD | BPF_W | BPF_ABS, OFF_NR)
    for i, nr in enumerate(nrs):
        k = 3 + i                                   # this instruction's index
        prog += _jeq(nr, deny_idx - (k + 1), 0)     # match: DENY, miss: next check
    prog += _stmt(BPF_RET, SECCOMP_RET_ALLOW)           # ALLOW (fall-through sink)
    prog += _stmt(BPF_RET, SECCOMP_RET_ERRNO | EPERM)   # DENY (jumped-to only)
    return bytes(prog)


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: make-seccomp.py <out-path>\n")
        return 2
    out = sys.argv[1]
    mach = platform.machine()
    if mach not in ("x86_64", "amd64"):
        # Remove a stale blob on non-x86_64 hosts.
        # - the launcher forwards any existing file
        # - an arch-mismatched filter must never be applied
        with contextlib.suppress(OSError):
            os.remove(out)
        sys.stderr.write(f"[seccomp] arch {mach!r} unsupported — skipping (no filter; "
                         f"removed any stale blob at {out})\n")
        return 0
    blob = build(DENY_X86_64)
    # Write atomically: temp file in same dir, then `os.replace`.
    # - a crash can't leave a truncated program for bwrap
    tmp = f"{out}.tmp.{os.getpid()}"
    with open(tmp, "wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, out)
    sys.stderr.write(f"[seccomp] wrote {out} ({len(blob)//8} insns, "
                     f"{len(DENY_X86_64)} syscalls denied)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
