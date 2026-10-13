"""The test suite runs with outbound sockets blocked (TR-SEC-01)."""

from __future__ import annotations

import socket

import pytest
from pytest_socket import SocketBlockedError


def test_outbound_socket_is_blocked() -> None:
    with pytest.raises(SocketBlockedError):
        socket.create_connection(("192.0.2.1", 80), timeout=1)  # TEST-NET-1, never routable


def test_raw_socket_construction_is_blocked() -> None:
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
