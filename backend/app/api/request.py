import ipaddress

from fastapi import Request


def get_request_ip_address(request: Request) -> str | None:
    # The trusted customer ingress replaces this header before the loopback Nginx.
    candidates = [request.headers.get("x-real-ip")]
    if request.client is not None:
        candidates.append(request.client.host)
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return None
