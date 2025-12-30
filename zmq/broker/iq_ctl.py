#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
import time

import zmq

log = logging.getLogger("iq_ctl")


def setup_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )

    log.handlers.clear()
    log.setLevel(level)
    log.addHandler(handler)

    logging.Formatter.converter = time.localtime


def main():
    setup_logging()

    ap = argparse.ArgumentParser(description="Control client for iq_broker.py")
    ap.add_argument(
        "--ctl", default="tcp://zmq_broker:5555", help="Broker control REP endpoint"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("START", help="Start recording to /out-dir (broker-side)")
    p_start.add_argument(
        "--tag",
        default=None,
        help="Optional tag used in <tag>_dl.fc32 and <tag>_ul.fc32",
    )

    sub.add_parser("STOP", help="Stop recording")
    sub.add_parser("STATUS", help="Get broker status")

    args = ap.parse_args()

    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.REQ)
    s.setsockopt(zmq.LINGER, 0)
    s.connect(args.ctl)

    payload = {"cmd": args.cmd.upper()}
    if args.cmd == "START" and args.tag:
        payload["tag"] = args.tag

    log.info(f"Sending control request: {payload['cmd']} (endpoint={args.ctl})")
    s.send_string(json.dumps(payload))

    resp = s.recv_string()

    try:
        obj = json.loads(resp)
    except Exception:
        log.error("Invalid response")
        raise SystemExit(2)

    if not obj.get("ok", False):
        err = obj.get("err") or obj.get("msg") or "unknown error"
        log.error("request failed: %s", err)
        raise SystemExit(1)

    if payload["cmd"] == "STATUS":
        enabled = bool(obj.get("recording", False))
        tag = obj.get("tag")

        if enabled:
            log.info(f"Status: RECORDING, tag -> {tag}" if tag else "RECORDING")
        else:
            log.info("Status: NOT RECORDING.")


if __name__ == "__main__":
    main()
