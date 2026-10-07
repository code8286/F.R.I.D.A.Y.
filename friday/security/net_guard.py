# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""SSRF guard for the web gateway (Architecture §5 Web / §6).

`check_url` validates scheme, rejects embedded credentials, normalises odd IPv4 spellings
(``2130706433``, ``0x7f000001``, ``127.1``), unwraps IPv4-mapped IPv6, resolves the host and requires
EVERY resolved address to be globally routable. The returned `UrlVerdict.ips` must be used to pin the
connection (connect to the validated IP, send the original Host header) so DNS rebinding between
check and fetch is impossible. Redirects must be re-validated hop by hop with `validate_redirect`.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

Resolver = Callable[..., list]

BLOCKED_NAMES = {"localhost", "metadata.google.internal", "metadata", "instance-data"}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet", ".localdomain")
MAX_REDIRECTS = 5


@dataclass(frozen=True)
class UrlVerdict:
    ok: bool
    reason: str = ""
    url: str = ""
    host: str = ""
    port: int | None = None
    ips: tuple[str, ...] = ()


_V6_EMBEDDED_V4 = (
    ipaddress.ip_network("::/96"),             # IPv4-compatible
    ipaddress.ip_network("64:ff9b::/96"),      # NAT64
    ipaddress.ip_network("::ffff:0:0:0/96"),   # SIIT
)
_V6_BLOCKED = (
    ipaddress.ip_network("fec0::/10"),         # deprecated site-local
    ipaddress.ip_network("64:ff9b:1::/48"),    # local-use NAT64
    ipaddress.ip_network("100::/64"),          # discard-only
)


def _ip_ok(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return _ip_ok(ip.ipv4_mapped)
        if ip.sixtofour is not None and not _ip_ok(ip.sixtofour):
            return False
        if ip.teredo is not None and not all(_ip_ok(x) for x in ip.teredo):
            return False
        if any(ip in net for net in _V6_BLOCKED):
            return False
        if any(ip in net for net in _V6_EMBEDDED_V4):
            return _ip_ok(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))   # judge the IPv4 address hidden inside
    return ip.is_global and not ip.is_multicast


def _parse_ip_literal(host: str) -> ipaddress._BaseAddress | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:  # legacy inet_aton spellings: decimal, hex, octal, short forms
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except (OSError, ValueError):
        return None


def check_url(
    url: str,
    *,
    resolver: Resolver | None = None,
    allow_private: bool = False,
    resolve: bool = True,
) -> UrlVerdict:
    """Validate a URL. With ``resolve=False`` only syntax, scheme, IP literals and internal names are checked and no DNS
    lookup happens (the policy engine uses this: a lookup before approval would leak data in the hostname and block the
    event loop). The fetch itself resolves, re-checks every address and pins the connection."""
    if not isinstance(url, str) or not url.strip() or any(c in url for c in "\x00\r\n\t "):
        return UrlVerdict(False, "malformed URL")
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return UrlVerdict(False, "malformed URL")
    if parts.scheme not in ("http", "https"):
        return UrlVerdict(False, f"scheme {parts.scheme!r} is not allowed")
    if "@" in parts.netloc:
        return UrlVerdict(False, "URLs with embedded credentials are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        return UrlVerdict(False, "URL has no host")

    ips: list[ipaddress._BaseAddress] = []
    literal = _parse_ip_literal(host)
    if literal is not None:
        ips = [literal]
    else:
        if host in BLOCKED_NAMES or host.endswith(BLOCKED_SUFFIXES):
            if not allow_private:
                return UrlVerdict(False, f"host {host!r} is internal")
        try:
            host.encode("idna")
        except UnicodeError:
            return UrlVerdict(False, "invalid hostname")
        if not resolve:
            return UrlVerdict(True, "", url.strip(), host, port, ())
        resolve_fn = resolver or socket.getaddrinfo
        try:
            infos = resolve_fn(host, port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except (socket.gaierror, OSError) as exc:
            return UrlVerdict(False, f"cannot resolve host: {exc}")
        for info in infos:
            try:
                ips.append(ipaddress.ip_address(info[4][0].split("%")[0]))
            except (ValueError, IndexError):
                return UrlVerdict(False, "resolver returned an unparsable address")
        if not ips:
            return UrlVerdict(False, "host did not resolve")

    if not allow_private:
        for ip in ips:
            if not _ip_ok(ip):
                return UrlVerdict(False, f"address {ip} is not publicly routable")
    return UrlVerdict(True, "", url.strip(), host, port, tuple(str(i) for i in ips))


def validate_redirect(
    current_url: str,
    location: str,
    hops: int,
    *,
    resolver: Resolver | None = None,
    allow_private: bool = False,
) -> UrlVerdict:
    """Validate the next hop of a redirect chain (resolves relative Locations first)."""
    if hops >= MAX_REDIRECTS:
        return UrlVerdict(False, f"more than {MAX_REDIRECTS} redirects")
    return check_url(urljoin(current_url, location), resolver=resolver, allow_private=allow_private)
