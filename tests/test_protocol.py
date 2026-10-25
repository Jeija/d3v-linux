import io
import json
import struct
import unittest

from d3v_linux.protocol import ProtocolError, check_ack, packets
from d3v_linux.updater import transfer


class FakeTransport:
    def __init__(self, bad_packet=None):
        self.writes = []
        self.bad_packet = bad_packet

    def exchange(self, packet, length):
        self.writes.append(packet)
        sequence = struct.unpack_from("<I", packet, 5)[0] + 1
        checksum = sum(packet) + (len(self.writes) == self.bad_packet)
        return struct.pack("<II", checksum, sequence).ljust(length, b"\0")


class ProtocolTests(unittest.TestCase):
    def test_sync_and_first_packet(self):
        reports = list(packets(b"abc"))
        self.assertEqual(
            reports[0], (bytes.fromhex("00a60000000100000001000000").ljust(65, b"\0"), 8, 2)
        )
        expected = bytes.fromhex("00a0000000030000000000000003000000") + b"abc"
        self.assertEqual(reports[1], (expected.ljust(65, b"\0"), 12, 4))

    def test_boundaries_and_full_firmware_size(self):
        for size, count in [(1, 2), (48, 2), (49, 3), (104, 3), (105, 4), (22124, 397)]:
            with self.subTest(size=size):
                data = bytes(i % 256 for i in range(size))
                reports = list(packets(data))
                self.assertEqual(len(reports), count)
                reconstructed = b""
                for i, (packet, length, sequence) in enumerate(reports[1:]):
                    self.assertEqual(len(packet), 65)
                    self.assertEqual(sequence, 4 + i * 2)
                    self.assertEqual(length, 12 if i == count - 2 else 8)
                    self.assertEqual(struct.unpack_from("<I", packet, 1)[0], 0xA0 if i == 0 else 0)
                    reconstructed += packet[17 if i == 0 else 9 :]
                self.assertEqual(reconstructed[:size], data)
                self.assertFalse(any(reconstructed[size:]))

    def test_empty_firmware_rejected(self):
        with self.assertRaises(ValueError):
            list(packets(b""))

    def test_ack_failures(self):
        packet, length, seq = next(packets(b"x"))
        for response in [
            b"",
            struct.pack("<II", sum(packet) + 1, seq),
            struct.pack("<II", sum(packet), seq + 2),
        ]:
            with self.subTest(response=response), self.assertRaises(ProtocolError):
                check_ack(packet, response, length, seq)

    def test_bad_ack_stops_before_next_write(self):
        for bad_packet in (1, 2, 3):
            with self.subTest(bad_packet=bad_packet):
                transport = FakeTransport(bad_packet)
                with self.assertRaises(ProtocolError):
                    transfer(transport, bytes(500), io.StringIO())
                self.assertEqual(len(transport.writes), bad_packet)

    def test_one_handshake_and_complete_log(self):
        log = io.StringIO()
        transport = FakeTransport()
        response, failed = transfer(transport, bytes(105), log)
        self.assertEqual(len(transport.writes), 4)
        self.assertEqual(len(response), 12)
        self.assertFalse(failed)
        records = [json.loads(line) for line in log.getvalue().splitlines()]
        self.assertEqual([bytes.fromhex(r["packet"]) for r in records], transport.writes)

    def test_log_failure_does_not_interrupt_flash(self):
        class FullDisk:
            def write(self, _):
                raise OSError("No space left")

        transport = FakeTransport()
        _, failed = transfer(transport, bytes(105), FullDisk())
        self.assertTrue(failed)
        self.assertEqual(len(transport.writes), 4)


if __name__ == "__main__":
    unittest.main()
