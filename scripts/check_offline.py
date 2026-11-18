r"""외부 API를 호출하지 않고 로컬 회귀 테스트를 재현한다.

실행: .venv\Scripts\python.exe scripts\check_offline.py
Windows 비동기 UI 테스트에 필요한 loopback 통신만 허용한다.
이 차단은 현재 Python 프로세스에 적용되며 운영체제 방화벽을 대신하지 않는다.
"""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import socket
import sys
from uuid import uuid4


def is_loopback(host: object) -> bool:
    """호스트 이름으로 외부 DNS 조회를 하지 않고 숫자 loopback 주소만 허용한다."""
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False


def block_external_connections() -> None:
    """실제 API 호출을 실수로 추가한 테스트는 즉시 실패하도록 한다."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo

    def require_loopback(address: object) -> None:
        if not isinstance(address, tuple) or not address or not is_loopback(address[0]):
            raise RuntimeError("외부 네트워크 호출은 오프라인 검증에서 허용하지 않습니다.")

    def local_connect(sock, address):
        require_loopback(address)
        return original_connect(sock, address)

    def local_connect_ex(sock, address):
        require_loopback(address)
        return original_connect_ex(sock, address)

    def local_getaddrinfo(host, *args, **kwargs):
        # localhost는 DNS 서버로 보내지 않고 숫자 주소로 바꾼다.
        local_host = "127.0.0.1" if host in ("localhost", b"localhost") else host
        if isinstance(local_host, bytes):
            local_host = local_host.decode("ascii")
        if not is_loopback(local_host):
            raise RuntimeError("외부 DNS 조회는 오프라인 검증에서 허용하지 않습니다.")
        return original_getaddrinfo(local_host, *args, **kwargs)

    socket.socket.connect = local_connect
    socket.socket.connect_ex = local_connect_ex
    socket.getaddrinfo = local_getaddrinfo


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    sys.path.insert(0, str(root))
    for name in ("GEMINI_API_KEY", "JEJU_HUB_PROJECT_KEY"):
        os.environ[name] = ""
    os.environ["OPEN_BROWSER"] = "0"
    block_external_connections()
    # 매번 새 경로를 지정해 기존 테스트 결과나 사용자 파일을 삭제하지 않는다.
    test_root = root / ".test-runs"
    test_root.mkdir(exist_ok=True)
    temporary_path = test_root / f"offline-{uuid4().hex}"
    import pytest

    return pytest.main(["tests", "-q", "-p", "no:cacheprovider",
                        f"--basetemp={temporary_path}", "--tb=short"])


if __name__ == "__main__":
    raise SystemExit(main())
