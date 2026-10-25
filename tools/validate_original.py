"""Execute original update function offline; compare every HID call to our port.

No USB access: HID reads/writes, allocator, memcpy, and stdout are emulated.
"""

import argparse
import hashlib
import struct
from pathlib import Path

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_64, Uc
from unicorn.x86_const import (
    UC_X86_REG_R8,
    UC_X86_REG_RAX,
    UC_X86_REG_RCX,
    UC_X86_REG_RDI,
    UC_X86_REG_RDX,
    UC_X86_REG_RIP,
    UC_X86_REG_RSI,
    UC_X86_REG_RSP,
)

from d3v_linux.protocol import packets

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--binary", required=True, type=Path, help="x86_64 Mach-O slice of updater 1.0.0"
)
parser.add_argument("--firmware", required=True, type=Path)
args = parser.parse_args()
binary = args.binary.read_bytes()
firmware = args.firmware.read_bytes()
if (
    hashlib.sha256(binary).hexdigest()
    != "f14aa21e702f422f7485987078d3b3a2d6ff1d1771c332b81f68794dd4e9f719"
):
    parser.error("This harness supports only the analyzed updater 1.0.0 x86_64 binary")


def validate(data):
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    uc.mem_map(0x100000000, 0x1000000)
    pos = 32
    for _ in range(struct.unpack_from("<I", binary, 16)[0]):
        cmd, size = struct.unpack_from("<II", binary, pos)
        if cmd == 0x19:
            addr, vmsize, off, length = struct.unpack_from("<QQQQ", binary, pos + 24)
            if length:
                uc.mem_write(addr, binary[off : off + length])
        pos += size
    uc.mem_map(0x200000000, 0x1000000)
    uc.mem_map(0x300000000, 0x1000000)
    heap = 0x300100000
    stack = 0x200FFFFF8
    sentinel = 0x100FFFFFF
    out, dev, source = 0x300000000, 0x300000100, 0x300001000
    uc.mem_write(source, data)
    uc.mem_write(stack, struct.pack("<Q", sentinel))
    for reg, val in [
        (UC_X86_REG_RSP, stack),
        (UC_X86_REG_RDI, out),
        (UC_X86_REG_RSI, dev),
        (UC_X86_REG_RDX, source),
        (UC_X86_REG_RCX, len(data)),
    ]:
        uc.reg_write(reg, val)
    expected = list(packets(data))
    index, pending = 0, None
    hooks = {
        0x1000DEAF0,
        0x1000DEB20,
        0x1000DEB00,
        0x100350234,
        0x10030F1F0,
        0x1000E0EB0,
        0x1000E0EE0,
    }

    def hook(u, address, size, userdata):
        nonlocal heap, index, pending
        if address not in hooks:
            return
        rdi, rsi, rdx, rcx, r8 = [
            u.reg_read(r)
            for r in [UC_X86_REG_RDI, UC_X86_REG_RSI, UC_X86_REG_RDX, UC_X86_REG_RCX, UC_X86_REG_R8]
        ]
        if address in (0x1000DEAF0, 0x1000DEB20):
            u.reg_write(UC_X86_REG_RAX, heap)
            u.mem_write(heap, bytes(rdi))
            heap += (rdi + 15) & ~15
        elif address == 0x100350234:
            u.mem_write(rdi, bytes(u.mem_read(rsi, rdx)))
            u.reg_write(UC_X86_REG_RAX, rdi)
        elif address == 0x1000E0EB0:
            assert pending is None
            p = bytes(u.mem_read(rdx, rcx))
            assert p == expected[index][0], (index, p.hex(), expected[index][0].hex())
            pending = p
            u.mem_write(rdi, struct.pack("<QQ", 0x8000000000000008, len(p)))
        elif address == 0x1000E0EE0:
            assert pending is not None
            _, acklen, seq = expected[index]
            assert rcx == acklen, (index, rcx, acklen)
            assert r8 == 5000
            response = struct.pack("<II", sum(pending), seq).ljust(acklen, b"\0")
            u.mem_write(rdx, response)
            u.mem_write(rdi, struct.pack("<QQ", 0x8000000000000008, acklen))
            pending = None
            index += 1
        rsp = u.reg_read(UC_X86_REG_RSP)
        target = struct.unpack("<Q", u.mem_read(rsp, 8))[0]
        u.reg_write(UC_X86_REG_RSP, rsp + 8)
        u.reg_write(UC_X86_REG_RIP, target)

    uc.hook_add(UC_HOOK_CODE, hook)
    uc.emu_start(0x1000DED00, sentinel, count=10000000)
    assert uc.reg_read(UC_X86_REG_RIP) == sentinel
    assert struct.unpack("<Q", uc.mem_read(out, 8))[0] == 5
    assert index == len(expected)
    print(f"PASS: {len(data)} bytes, {index} original HID writes and ACKs match Linux port")


for length in [1, 47, 48, 49, 103, 104, 105]:
    validate(bytes(range(length)))
validate(firmware)
