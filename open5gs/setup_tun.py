#!/usr/bin/env python3
import click
import ipaddress
import logging
import re
import shutil
import subprocess
from pyroute2 import IPRoute
from pyroute2.netlink import NetlinkError


def handle_ip_string(ctx, param, value):
    try:
        return ipaddress.ip_network(value)
    except ValueError:
        raise click.BadParameter(f"{value} is not a valid IP range.")


def pick_iptables_binary():
    # Prefer nft backend if present (often avoids legacy xtables module dependencies)
    # xtables-nft tools manage the nf_tables backend using iptables syntax
    for c in ("iptables-nft", "iptables", "iptables-legacy"):
        if shutil.which(c):
            return c
    raise RuntimeError("No iptables binary found in container.")


def run(cmd):
    logging.info("RUN: %s", " ".join(cmd))
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def ensure_rule(iptables, table, chain, rule_args):
    # iptables -t <table> -C <chain> <rule...>  (check) then -A (add)
    check = [iptables, "-t", table, "-C", chain] + rule_args
    add = [iptables, "-t", table, "-A", chain] + rule_args
    try:
        subprocess.run(check, check=True, capture_output=True, text=True)
        logging.info("Rule already present: %s", " ".join(check))
    except subprocess.CalledProcessError:
        run(add)


def default_egress_if():
    out = subprocess.check_output(
        ["ip", "-4", "route", "show", "default"], text=True
    ).strip()
    m = re.search(r"\bdev\s+(\S+)", out)
    return m.group(1) if m else None


def enable_ip_forward():
    try:
        run(["sysctl", "-w", "net.ipv4.ip_forward=1"])
    except Exception:
        # Fallback if sysctl is unavailable
        with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
            f.write("1\n")


@click.command()
@click.option("--if_name", default="ogstun", help="TUN interface name.")
@click.option(
    "--ip_range",
    default="10.45.0.0/16",
    callback=handle_ip_string,
    help="UE IPv4 pool routed via the TUN (should match UPF/SMF config).",
)
def main(if_name, ip_range):
    logging.basicConfig(
        level=logging.INFO, format="[setup_tun] %(levelname)s  -  %(message)s"
    )

    iptables = pick_iptables_binary()
    egress = default_egress_if()
    if not egress:
        raise RuntimeError(
            "Cannot determine default egress interface inside container."
        )

    # Use the first usable address for ogstun, as in Open5GS docs (e.g., 10.45.0.1/16)
    ogstun_ip = str(next(ip_range.hosts()))
    prefix = ip_range.prefixlen

    ipr = IPRoute()
    try:
        ipr.link("add", ifname=if_name, kind="tuntap", mode="tun")
        logging.info("Created TUN: %s", if_name)
    except NetlinkError as e:
        logging.info("TUN exists or cannot be created: %s", e)

    idx_list = ipr.link_lookup(ifname=if_name)
    if not idx_list:
        raise RuntimeError(f"Interface {if_name} not found after creation attempt.")
    idx = idx_list[0]

    ipr.link("set", index=idx, state="down")
    try:
        ipr.addr("add", index=idx, address=ogstun_ip, mask=prefix)
    except NetlinkError as e:
        logging.info("Address add skipped/failed (may already exist): %s", e)
    ipr.link("set", index=idx, state="up")

    enable_ip_forward()

    # NAT: MASQUERADE UE pool for any egress except ogstun, matching Open5GS guidance
    ensure_rule(
        iptables,
        "nat",
        "POSTROUTING",
        ["-s", ip_range.with_prefixlen, "!", "-o", if_name, "-j", "MASQUERADE"],
    )

    # Forwarding rules (typical minimal stateful policy for NAT gateway)
    ensure_rule(
        iptables, "filter", "FORWARD", ["-i", if_name, "-o", egress, "-j", "ACCEPT"]
    )
    ensure_rule(
        iptables,
        "filter",
        "FORWARD",
        [
            "-i",
            egress,
            "-o",
            if_name,
            "-m",
            "conntrack",
            "--ctstate",
            "RELATED,ESTABLISHED",
            "-j",
            "ACCEPT",
        ],
    )

    # Optional: allow local access to the container via ogstun (ping 10.45.0.1 etc.)
    ensure_rule(iptables, "filter", "INPUT", ["-i", if_name, "-j", "ACCEPT"])

    logging.info(
        "TUN+NAT ready: %s=%s/%d, UE pool=%s, egress=%s, iptables=%s",
        if_name,
        ogstun_ip,
        prefix,
        ip_range.with_prefixlen,
        egress,
        iptables,
    )


if __name__ == "__main__":
    main()
