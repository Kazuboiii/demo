"""Small local-network discovery responder for the installed HOMS app.

Listens on all local interfaces (Wi-Fi, hotspot, emulator) for discovery
probes from the phone app and replies with the laptop's identity so the phone
can connect to the HOMS API.
"""
import ipaddress
import json
import socket

PORT = 45873


def _private_lan_ips():
    """Return every private IPv4 address active on non-loopback interfaces."""
    found = []
    seen = set()

    def _add(ip_str):
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return
        if addr.is_loopback or not addr.is_private:
            return
        if ip_str not in seen:
            seen.add(ip_str)
            found.append(ip_str)

    test_ips = [
        "192.168.1.1", "192.168.0.1", "192.168.2.1",
        "192.168.137.1", "192.168.137.2",
        "10.0.0.1", "10.0.1.1", "172.16.0.1", "172.17.0.1",
        "172.18.0.1", "172.19.0.1", "172.20.0.1", "172.21.0.1",
        "172.22.0.1", "172.23.0.1", "172.24.0.1", "172.25.0.1",
        "172.26.0.1", "172.27.0.1", "172.28.0.1", "172.29.0.1",
        "172.30.0.1", "172.31.0.1",
    ]
    for ip in test_ips:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.bind((ip, 0))
                _add(probe.getsockname()[0])
        except OSError:
            continue

    for ip in list(found):
        parts = ip.split(".")
        if len(parts) == 4 and parts[0] == "192" and parts[1] == "168":
            third = parts[2]
            for host in ("1", "2", "137"):
                candidate = f"192.168.{third}.{host}"
                if candidate not in seen:
                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                            probe.bind((candidate, 0))
                            _add(probe.getsockname()[0])
                    except OSError:
                        continue

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("1.1.1.1", 53))
            _add(probe.getsockname()[0])
    except OSError:
        pass

    return found


def _reply(payload):
    """Validate a discovery probe and return the reply bytes, or None."""
    try:
        message = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(message, dict):
        return None
    if message.get("service") != "homs-discover":
        return None
    nonce = message.get("nonce")
    if not isinstance(nonce, str) or not 1 <= len(nonce) <= 64:
        return None
    return json.dumps({"service": "homs", "version": 1, "port": 8000, "nonce": nonce}).encode()


def _pick_best_ip(peer_ip, candidates):
    """Pick the candidate IP on the same subnet as the peer."""
    try:
        peer = ipaddress.ip_address(peer_ip)
    except ValueError:
        return candidates[0] if candidates else None

    peer_parts = peer_ip.split(".")
    if len(peer_parts) == 4:
        for candidate in candidates:
            cand_parts = candidate.split(".")
            if len(cand_parts) == 4 and cand_parts[:3] == peer_parts[:3]:
                return candidate

    return candidates[0] if candidates else None


def main():
    candidates = sorted(set(_private_lan_ips()))
    if not candidates:
        print("HOMS discovery: no private LAN IP found; giving up.", flush=True)
        return

    # One response socket per interface IP so replies always leave the right way.
    responders = {}
    for ip in candidates:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind((ip, 0))
            responders[ip] = sock
        except OSError as exc:
            print(f"HOMS discovery: cannot bind response socket for {ip}: {exc}", flush=True)

    if not responders:
        print("HOMS discovery: no usable response sockets; giving up.", flush=True)
        return

    # Single listener on 0.0.0.0 receives probes from all interfaces.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        listener.bind(("0.0.0.0", PORT))
        print(f"HOMS discovery listening on UDP {PORT}", flush=True)
        print(f"HOMS discovery LAN IPs: {', '.join(candidates)}", flush=True)

        while True:
            try:
                data, peer = listener.recvfrom(1024)
            except OSError:
                continue
            response = _reply(data)
            if not response:
                continue
            peer_ip = peer[0]
            best = _pick_best_ip(peer_ip, list(responders.keys()))
            if best and best in responders:
                try:
                    responders[best].sendto(response, peer)
                except OSError:
                    pass


if __name__ == "__main__":
    main()
