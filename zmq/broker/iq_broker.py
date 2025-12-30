#!/usr/bin/env python3
import argparse
import json
import os
import threading
import time
import logging
import sys
import zmq
from datetime import datetime
from typing import Optional, BinaryIO

log = logging.getLogger("iq_broker")


def setup_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s | %(threadName)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    logging.Formatter.converter = time.localtime


def _local_tag() -> str:
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")


class Recorder:
    def __init__(self, out_dir: str):
        self.out_dir = out_dir
        self.lock = threading.Lock()
        self.enabled = False
        self.dl_f: Optional[BinaryIO] = None
        self.ul_f: Optional[BinaryIO] = None
        self.tag: Optional[str] = None
        self.dl_path: Optional[str] = None
        self.ul_path: Optional[str] = None

    def start(self, tag: str):
        with self.lock:
            if self.enabled:
                log.info("Start requested but already recording (tag=%s)", tag)
                return {
                    "ok": True,
                    "msg": "already recording",
                    "tag": self.tag,
                    "dl": self.dl_path,
                    "ul": self.ul_path,
                }
            os.makedirs(self.out_dir, exist_ok=True)
            dl_path = os.path.join(self.out_dir, f"{tag}_dl.fc32")
            ul_path = os.path.join(self.out_dir, f"{tag}_ul.fc32")

            dl_f: Optional[BinaryIO] = None
            ul_f: Optional[BinaryIO] = None
            try:
                dl_f = open(dl_path, "wb")
                ul_f = open(ul_path, "wb")
            except Exception:
                log.exception(
                    f"Failed to open output files (dl: {dl_path} ul: {ul_path})"
                )
                if dl_f:
                    dl_f.close()
                if ul_f:
                    ul_f.close()
                raise

            self.dl_f = dl_f
            self.ul_f = ul_f
            self.enabled = True
            self.tag = tag
            self.dl_path = dl_path
            self.ul_path = ul_path
            log.info(f"Recording started. Tag: {tag}")
            return {"ok": True, "tag": tag, "dl": dl_path, "ul": ul_path}

    def stop(self):
        with self.lock:
            if not self.enabled:
                log.info("Stop requested but already stopped")
                return {"ok": True, "msg": "already stopped"}

            tag = self.tag
            dl_path = self.dl_path
            ul_path = self.ul_path

            try:
                if self.dl_f:
                    self.dl_f.flush()
                    self.dl_f.close()
                if self.ul_f:
                    self.ul_f.flush()
                    self.ul_f.close()
            finally:
                self.dl_f = None
                self.ul_f = None
                self.enabled = False
                self.tag = None
                self.dl_path = None
                self.ul_path = None

            log.info(
                f"Recording stopped. Output files: {dl_path} | ul: {ul_path}"
            )
            return {"ok": True, "tag": tag, "dl": dl_path, "ul": ul_path}

    def write_dl(self, payload: bytes):
        with self.lock:
            if self.enabled and self.dl_f:
                self.dl_f.write(payload)

    def write_ul(self, payload: bytes):
        with self.lock:
            if self.enabled and self.ul_f:
                self.ul_f.write(payload)


def bind_or_connect(sock: zmq.Socket, endpoint: str):
    # Convention:
    #  - tcp://*:PORT or tcp://0.0.0.0:PORT => bind
    #  - otherwise => connect
    if endpoint.startswith("tcp://*"):
        ep = endpoint.replace("tcp://*", "tcp://0.0.0.0")
        sock.bind(ep)
        log.info("Bound to %s", ep)
    elif endpoint.startswith("tcp://0.0.0.0") or endpoint.startswith("ipc://"):
        sock.bind(endpoint)
        log.info("Bound to %s", endpoint)
    else:
        sock.connect(endpoint)
        log.info("Connected to %s", endpoint)


def relay_loop(
    name: str,
    ctx: zmq.Context,
    front_rep: str,
    back_req: str,
    recorder: Recorder,
    is_dl: bool,
):
    # front: REP towards the receiver (receiver uses REQ)
    # back:  REQ towards the transmitter (transmitter uses REP)
    front = ctx.socket(zmq.REP)
    back = ctx.socket(zmq.REQ)

    front.setsockopt(zmq.LINGER, 0)
    back.setsockopt(zmq.LINGER, 0)

    bind_or_connect(front, front_rep)
    bind_or_connect(back, back_req)

    direction = "DL" if is_dl else "UL"
    log.info(
        "%s relay loop started (front_rep=%s back_req=%s)",
        direction,
        front_rep,
        back_req,
    )

    msgs = 0
    bytes_total = 0
    last_report = time.time()

    while True:
        try:
            token = front.recv()  # request, typically empty or small
            back.send(token)  # forward request to TX
            payload = back.recv()  # reply = IQ bytes

            if is_dl:
                recorder.write_dl(payload)
            else:
                recorder.write_ul(payload)

            front.send(payload)  # reply to RX

            msgs += 1
            bytes_total += len(payload)
            now = time.time()
            if now - last_report >= 5.0:
                log.info(
                    "%s relay stats: msgs=%d bytes=%d recording=%s",
                    direction,
                    msgs,
                    bytes_total,
                    recorder.enabled,
                )
                last_report = now

        except zmq.ZMQError:
            log.exception(
                "%s relay ZMQ error (front_rep=%s back_req=%s)",
                direction,
                front_rep,
                back_req,
            )
            time.sleep(0.5)
        except Exception:
            log.exception(
                "%s relay unexpected error (front_rep=%s back_req=%s)",
                direction,
                front_rep,
                back_req,
            )
            time.sleep(0.5)


def control_loop(ctx: zmq.Context, ctl_rep: str, recorder: Recorder):
    ctl = ctx.socket(zmq.REP)
    ctl.setsockopt(zmq.LINGER, 0)
    bind_or_connect(ctl, ctl_rep)
    log.info(f"Control loop started (ctl_rep={ctl_rep})")

    while True:
        msg = ctl.recv()
        try:
            cmd = json.loads(msg.decode("utf-8"))
        except Exception:
            log.warning(f"Control: invalid JSON (len={len(msg)})")
            ctl.send_json({"ok": False, "err": "invalid json"})
            continue

        c = str(cmd.get("cmd", "")).upper()
        if c == "START":
            tag = cmd.get("tag") or _local_tag()
            log.debug(f"Control: received START cmd")
            ctl.send_json(recorder.start(tag))
        elif c == "STOP":
            log.debug("Control: received STOP cmd")
            ctl.send_json(recorder.stop())
        elif c == "STATUS":
            log.debug("Control: received STATUS cmd")
            ctl.send_json({"ok": True, "recording": recorder.enabled, "tag": recorder.tag})
        else:
            log.warning(f"Control: unknown command ({c})")
            ctl.send_json({"ok": False, "err": "unknown cmd"})


def main():
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dl-front-rep",
        required=True,
        help="REP endpoint on the UE RX side (broker replies)",
    )
    ap.add_argument(
        "--dl-back-req",
        required=True,
        help="REQ endpoint towards the gNB TX side (broker requests)",
    )
    ap.add_argument(
        "--ul-front-rep",
        required=True,
        help="REP endpoint on the gNB RX side (broker replies)",
    )
    ap.add_argument(
        "--ul-back-req",
        required=True,
        help="REQ endpoint towards the UE TX side (broker requests)",
    )
    ap.add_argument(
        "--ctl-rep", default="tcp://0.0.0.0:5555", help="Control REP endpoint"
    )
    ap.add_argument("--out-dir", default="/iq", help="Output directory for .fc32")
    args = ap.parse_args()

    log.info(
        f"Starting Broker: dl_front_rep={args.dl_front_rep} | "
        + f"dl_back_req={args.dl_back_req} | "
        + f"ul_front_rep={args.ul_front_rep} | "
        + f"ul_back_req={args.ul_back_req} | "
        + f"ctl_rep={args.ctl_rep} | "
        + f"out_dir={args.out_dir}"
    )

    ctx = zmq.Context.instance()
    recorder = Recorder(args.out_dir)

    t1 = threading.Thread(
        target=relay_loop,
        args=("DL", ctx, args.dl_front_rep, args.dl_back_req, recorder, True),
        daemon=True,
        name="relay-DL",
    )
    t2 = threading.Thread(
        target=relay_loop,
        args=("UL", ctx, args.ul_front_rep, args.ul_back_req, recorder, False),
        daemon=True,
        name="relay-UL",
    )
    t3 = threading.Thread(
        target=control_loop,
        args=(ctx, args.ctl_rep, recorder),
        daemon=True,
        name="control",
    )

    t1.start()
    t2.start()
    t3.start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
