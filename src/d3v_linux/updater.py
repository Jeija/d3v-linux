"""Transfer one firmware image in one fresh bootloader session."""

import json
import signal
from contextlib import contextmanager

from .protocol import check_ack, packets


@contextmanager
def uninterrupted_transfer():
    previous = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, signal.SIG_IGN)
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def transfer(transport, firmware, log, progress=lambda done, total: None):
    reports = list(packets(firmware))
    logging_failed = False
    # Include the handshake: there must be no probe between boot and this transfer.
    with uninterrupted_transfer():
        for index, (packet, length, sequence) in enumerate(reports):
            response = transport.exchange(packet, length)
            if not logging_failed:
                try:
                    log.write(
                        json.dumps(
                            {
                                "packet": packet.hex(),
                                "ack": response.hex(),
                                "expected_sequence": sequence,
                            }
                        )
                        + "\n"
                    )
                    log.flush()
                except OSError:
                    # An exhausted log disk must not interrupt an otherwise valid transfer.
                    logging_failed = True
            check_ack(packet, response, length, sequence)
            progress(index, len(reports) - 1)
    return response, logging_failed
