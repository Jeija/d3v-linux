"""The HID protocol used by the official D3V updater 1.0.0."""

import struct


class ProtocolError(ValueError):
    """A bootloader reply did not match the request."""


def packets(firmware):
    if not 0 < len(firmware) <= 0xFFFFFFFF:
        raise ValueError("Firmware must contain between 1 and 2^32 - 1 bytes")
    yield (b"\0" + struct.pack("<III", 0xA6, 1, 1)).ljust(65, b"\0"), 8, 2
    offset, sequence = 0, 3
    while offset < len(firmware):
        if offset == 0:
            header = struct.pack("<IIII", 0xA0, sequence, 0, len(firmware))
        else:
            header = struct.pack("<II", 0, sequence)
        chunk = firmware[offset : offset + 64 - len(header)]
        offset += len(chunk)
        ack_length = 12 if offset == len(firmware) else 8
        yield (b"\0" + header + chunk).ljust(65, b"\0"), ack_length, sequence + 1
        sequence += 2


def check_ack(packet, response, length, sequence):
    if len(response) != length:
        raise ProtocolError(f"Expected {length} ACK bytes, got {len(response)}")
    checksum, counter = struct.unpack_from("<II", response)
    if checksum != sum(packet):
        raise ProtocolError(f"Checksum mismatch: expected {sum(packet)}, got {checksum}")
    if counter != sequence:
        detail = " Re-enter update mode before starting another session." if sequence == 2 else ""
        raise ProtocolError(f"Packet counter mismatch: expected {sequence}, got {counter}.{detail}")
