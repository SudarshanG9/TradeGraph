"""Native local preflight preserves listener exclusion but permits TCP TIME_WAIT."""
import socket
import pytest
from scripts.run_local import check_port_available


def test_reused_probe_rejects_listener_and_accepts_closed_connections():
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        server.bind(('127.0.0.1',0))
        port=server.getsockname()[1]
        server.listen(1)
        with pytest.raises(ValueError,match='occupied'):
            check_port_available('127.0.0.1',port)
        with socket.create_connection(('127.0.0.1',port)) as client:
            accepted,_=server.accept()
            accepted.close()  # active close leaves server-side TCP TIME_WAIT
            assert client.recv(1)==b''
    check_port_available('127.0.0.1',port)
