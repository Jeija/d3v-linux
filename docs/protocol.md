# D3V update protocol

These notes describe ADAM's updater 1.0.0 and the official D3V firmware 1.7 package.
They are based on static analysis, offline execution of the original updater,
and a successful installation on one D3V using Linux. They are not a vendor
specification.

## Device identity

Normal USB audio uses `08bb:2704` with product string `ADAM Audio D3V`. The ID
alone is insufficient: other PCM2704 audio devices use it too.

Update mode uses `0416:3f00` and product string `WPM USB`. This is a generic Nuvoton
bootloader identity. The project first identifies the speaker in normal mode,
remembers its physical USB topology, then requires the bootloader on that same
port. It also checks this report descriptor:

```text
0600ff0901a10119012940150026ff00750895408100190129409100c0
```

The descriptor declares unnumbered 64-byte input and output reports. Writes to
Linux `hidraw` include a leading zero report-ID byte, making the write buffer
65 bytes long. Replies have no leading report-ID byte. See the
[Linux hidraw documentation](https://www.kernel.org/doc/html/latest/hid/hidraw.html).

## Wire format

All integer fields are unsigned 32-bit little-endian values. Offsets below are
relative to the 64-byte payload, excluding the zero report-ID byte. Unused bytes
are zero-filled.

| Message | Offset 0 | Offset 4 | Offset 8 | Offset 12 | Firmware data |
| --- | --- | --- | --- | --- | --- |
| Handshake | `0xa6` | `1` | `1` | zero | none |
| First firmware packet | `0xa0` | `3` | start address `0` | complete file length | up to 48 bytes at offset 16 |
| Subsequent packet | `0` | `5`, `7`, … | data starts here | data continues | up to 56 bytes at offset 8 |

The handshake is named `SYNC_PACKNO` in the original updater. Despite the name,
the tested bootloader did **not** reset its counter when this message was sent
twice. The first handshake returned sequence 2; a second returned 4. Each update
must therefore begin in a fresh bootloader session. The tool sends the handshake
and firmware in one session and offers no separate probe command.

The acknowledgment's first two words are:

| Offset | Meaning |
| --- | --- |
| 0 | Sum of all bytes in the outgoing report |
| 4 | Outgoing sequence number plus one |

The official updater reads 8 bytes after each packet except the final firmware
packet, when it reads 12. It checks the checksum and sequence number but does not
interpret the final four bytes. This project preserves that behavior rather than
inventing a meaning for them. Each read has a five-second timeout.

There is no separate erase, finish, or reboot command in the analyzed update
function. It returns success after the final acknowledgment. The tool does not
read the installed version or read flash back. A valid transfer proves that the
device acknowledged the transmitted packets, not that flash readback matched.

## Evidence

Both official Windows and macOS packages contain the same 22,124-byte file:
`D3V_MCU+DSP_V1_7_RC4.bin`. The RC4 name is part of ADAM's released 1.7 package.

```text
Firmware SHA-256:
f2486dae4ef2399db12fcb255eeab227e1533bf1eed96c9a2eaa3ef822388a38

Analyzed updater 1.0.0 macOS x86_64 slice SHA-256:
f14aa21e702f422f7485987078d3b3a2d6ff1d1771c332b81f68794dd4e9f719
```

The macOS binary retained Rust symbols for the relevant functions:

| Address | Function |
| --- | --- |
| `0x10006b7b0` | Application update; selects VID `0416` / PID `3f00` |
| `0x1000ded00` | `d3v_update_device::update_device` |
| `0x1000dfcf0` | `ApromPacketBuilder::next` |
| `0x1000df690` | `d3v_helpers::read_ack` |

The [offline harness](../tools/validate_original.py) runs the original update
function and packet builder with emulated allocation, memory copying, printing,
and HID calls. All 397 reports for firmware 1.7 matched the Linux implementation,
including acknowledgment lengths and timeouts. Boundary inputs of 1, 47, 48, 49,
103, 104, and 105 bytes also matched.

The hardware transfer acknowledged the handshake and all 396 firmware packets in
about 2.2 seconds. Reconstructing the image from the transfer log reproduced the
official firmware exactly, with only zero padding after its end. The final ACK
was `1c0000001a030000bdffdfff`.