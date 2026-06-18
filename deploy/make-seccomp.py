#!/usr/bin/env python3
"""Seccomp BPF generator (#119e) — shrink the jail's kernel attack surface.

bwrap applies a classic-BPF seccomp filter from a file descriptor (``--seccomp FD``).
This emits such a program: a small DENYLIST that returns EPERM for a curated set of
rarely-needed, high-blast-radius syscalls (module load, kexec, ptrace, bpf, key
management, mount, time-set, …). It is a DENYLIST (default = allow) precisely so it
cannot break ordinary code work (node/git/python/gcc use none of these); the goal is
to lower the residual userns/kernel-escape risk, not to allowlist syscalls.

Output is the raw ``struct sock_filter`` array (8 bytes each: ``<HBBI``) that bwrap
reads from the fd, computing the instruction count from the file size — exactly what
``seccomp(2)`` expects. x86_64 only; on any other arch this writes NOTHING and exits 0
(the launcher then simply skips ``--seccomp``), so the filter never mis-fires on an
arch whose syscall numbers differ.

Usage: make-seccomp.py <out-path>   (writes the blob; prints a one-line summary)
"""

import platform
import struct
import sys

# BPF opcodes (linux/bpf_common.h) and seccomp ABI constants (linux/seccomp.h).
BPF_LD, BPF_W, BPF_ABS = 0x00, 0x00, 0x20
BPF_JMP, BPF_JEQ, BPF_K = 0x05, 0x10, 0x00
BPF_RET = 0x06
AUDIT_ARCH_X86_64 = 0xC000003E
SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_ERRNO = 0x00050000
EPERM = 1
# Offsets into struct seccomp_data: nr (the syscall number) at 0, arch at 4.
OFF_NR, OFF_ARCH = 0, 4

# x86_64 syscall numbers to refuse. Each is something a sandboxed dev workload never
# legitimately needs but which materially widens the host attack surface if allowed.
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
    """Assemble: verify arch == x86_64 (else ALLOW), then a per-syscall JEQ chain
    where a MATCH jumps to DENY and a miss falls through to the next check; after the
    last check the program falls through to ALLOW. ALLOW is therefore the fall-through
    sink and DENY is reached ONLY by an explicit jump — get this order wrong (DENY as
    the fall-through) and every non-denied syscall returns EPERM and the process dies.
    Jump offsets are PC-relative, counted from the NEXT instruction."""
    nrs = sorted(deny)
    m = len(nrs)
    # Layout: [0]=LD arch [1]=JEQ x86_64 [2]=LD nr [3..2+m]=checks [3+m]=ALLOW [4+m]=DENY
    allow_idx = 3 + m
    deny_idx = 4 + m
    prog = bytearray()
    prog += _stmt(BPF_LD | BPF_W | BPF_ABS, OFF_ARCH)
    # arch != x86_64 → fall through to ALLOW (we only know x86_64 numbers); else continue.
    prog += _jeq(AUDIT_ARCH_X86_64, 0, allow_idx - 2)
    prog += _stmt(BPF_LD | BPF_W | BPF_ABS, OFF_NR)
    for i, nr in enumerate(nrs):
        k = 3 + i                                   # this instruction's index
        prog += _jeq(nr, deny_idx - (k + 1), 0)     # match → DENY, miss → next check
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
        sys.stderr.write(f"[seccomp] arch {mach!r} unsupported — skipping (no filter)\n")
        return 0
    blob = build(DENY_X86_64)
    with open(out, "wb") as fh:
        fh.write(blob)
    sys.stderr.write(f"[seccomp] wrote {out} ({len(blob)//8} insns, "
                     f"{len(DENY_X86_64)} syscalls denied)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
