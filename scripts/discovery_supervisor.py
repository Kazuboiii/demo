"""Watch the network interfaces and keep HOMS discovery healthy.

Runs as a thin wrapper around lan_discovery.py. If discovery dies for any
reason, or the set of LAN IPs changes (Wi-Fi toggled, hotspot, new DHCP), it
restarts discovery so the advertised IP stays correct. The UDP listener on
45873 is treated as a singleton — only one instance is allowed to hold it.

Intended to be started by start.ps1 in place of calling lan_discovery.py
directly. Logs to .runtime/discovery-supervisor.log and
.runtime/discovery-supervisor.error.log.
"""

import ipaddress
import json
import os
import socket
import subprocess
import sys
import time

PORT = 45873
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), ".runtime")
LAN_DISCOVERY_PATH = os.path.join(SCRIPT_DIR, "lan_discovery.py")
SUPERVISOR_PID_FILE = os.path.join(RUNTIME_DIR, "discovery-supervisor.pid")
DISCOVERY_PID_FILE = os.path.join(RUNTIME_DIR, "discovery.pid")
DISCOVERY_LOG = os.path.join(RUNTIME_DIR, "discovery.log")
DISCOVERY_ERR_LOG = os.path.join(RUNTIME_DIR, "discovery.error.log")


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


def _current_lan_ips():
    return sorted(set(_private_lan_ips()))


def _write_pid(path, pid):
    try:
        with open(path, "w") as f:
            f.write(str(pid))
    except OSError:
        pass


def _alive(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _start_discovery():
    """Start lan_discovery.py and return the Popen handle + advertised IPs.

    Discovery's own stdout/stderr are appended to the same log files start.ps1
    would write, so tooling that reads .runtime/discovery.log and
    .runtime/discovery.error.log sees a continuous record across supervisor
    restarts.
    """
    advertised = _current_lan_ips()
    if not advertised:
        print("discovery-supervisor: no private LAN IP found; cannot start discovery", flush=True)
        return None, None

    log_f = open(DISCOVERY_LOG, "ab")
    err_f = open(DISCOVERY_ERR_LOG, "ab")
    try:
        proc = subprocess.Popen(
            [sys.executable, LAN_DISCOVERY_PATH],
            cwd=SCRIPT_DIR,
            stdout=log_f,
            stderr=err_f,
            creationflags=0,
        )
        _write_pid(DISCOVERY_PID_FILE, proc.pid)
        print(f"discovery-supervisor: started discovery pid={proc.pid}, advertised={advertised}", flush=True)
        return proc, advertised
    except Exception:
        log_f.close()
        err_f.close()
        raise


def _stop_discovery(proc):
    if proc is None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except OSError:
        pass
    print(f"discovery-supervisor: stopped discovery pid={proc.pid}", flush=True)


def _listener_holds_port():
    """Return True if some other process already owns UDP 45873.

    We test by trying to bind our own UDP socket to 0.0.0.0:PORT. On Windows,
    a second socket cannot bind to the same 0.0.0.0:PORT if another socket
    (bound to 0.0.0.0 or a specific IP) is already there, so a failure means
    the port is held by someone else.

    The probe socket is always closed (even on bind failure, using a finally
    block), so we never leak sockets across poll cycles. With SO_REUSEADDR set,
    the probe is also safe against the common TIME_WAIT-style conditions that
    can cause a false positive on Windows.
    """
    probe = None
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("0.0.0.0", PORT))
    except OSError:
        return True
    finally:
        if probe is not None:
            try:
                probe.close()
            except OSError:
                pass
    return False


def main():
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    _write_pid(SUPERVISOR_PID_FILE, os.getpid())

    print("discovery-supervisor: started", flush=True)

    proc = None
    last_advertised = None
    check_interval = 3  # seconds between interface-change checks
    restart_backoff = 2  # seconds, grows up to 30 when restarts fail
    last_check = 0.0

    try:
        # Start discovery immediately if the port is free.
        if not _listener_holds_port():
            proc, last_advertised = _start_discovery()
            restart_backoff = 2
            print(f"discovery-supervisor: port free; started discovery pid={proc.pid if proc else 'n/a'}", flush=True)
        else:
            print("discovery-supervisor: port 45873 already in use; waiting for it to free", flush=True)
            restart_backoff = 2

        while True:
            now = time.time()

            # 1. If discovery died, restart it (if the port is free).
            if proc is not None and not _alive(proc.pid):
                print(f"discovery-supervisor: discovery pid={proc.pid} died; will restart if port free", flush=True)
                _stop_discovery(proc)
                proc = None
                last_advertised = None

            if proc is None:
                if not _listener_holds_port():
                    restarted_proc, restarted_advertised = _start_discovery()
                    proc = restarted_proc
                    if proc is not None:
                        last_advertised = restarted_advertised
                        restart_backoff = 2
                        print(f"discovery-supervisor: restarted discovery pid={proc.pid}", flush=True)
                        _write_pid(DISCOVERY_PID_FILE, proc.pid)
                    else:
                        restart_backoff = min(30, restart_backoff * 2)
                    continue

            # Discovery is alive and holding the port: heartbeat it into the PID
            # file so that even if the supervisor crashes, tooling sees the live
            # discovery PID (not the stale one from the last restart).
            if proc is not None and _alive(proc.pid):
                _write_pid(DISCOVERY_PID_FILE, proc.pid)

            # If the port is held by a stale/foreign listener, wait for it to
            # clear rather than fight it.
            if proc is None and _listener_holds_port():
                print("discovery-supervisor: port 45873 still in use; discovery will be retried later", flush=True)
                last_check = now
                restart_backoff = min(30, restart_backoff * 2)
                continue

            # 2. If the advertised IP set changed *and* our discovery process is
            #    the one holding the port, restart it so it re-resolves the new
            #    interface set.
            if proc is not None and _alive(proc.pid):
                current = _current_lan_ips()
                changed = sorted(set(current)) != sorted(set(last_advertised or []))
                if changed and not _listener_holds_port():
                    print(f"discovery-supervisor: LAN IPs changed {last_advertised} -> {current}; restarting discovery", flush=True)
                    _stop_discovery(proc)
                    proc = None
                    last_advertised = None
                    restart_backoff = 2
                    continue
                last_advertised = current

            last_check = now

    except KeyboardInterrupt:
        print("discovery-supervisor: interrupted", flush=True)
    finally:
        _stop_discovery(proc)
        try:
            os.remove(SUPERVISOR_PID_FILE)
        except OSError:
            pass
        # Rewrite discovery.pid one last time so tooling never reads a stale PID
        # after the supervisor exits. If a live discovery exists, point at it;
        # otherwise remove the file so start.ps1 knows to start a fresh one.
        try:
            if proc is not None and _alive(proc.pid):
                _write_pid(DISCOVERY_PID_FILE, proc.pid)
            else:
                os.remove(DISCOVERY_PID_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
