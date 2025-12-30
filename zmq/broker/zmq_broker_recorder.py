#!/usr/bin/env python3

import argparse
import os
import time
from datetime import datetime, timezone

from gnuradio import gr, blocks, zeromq

class ZmqBrokerRecorder(gr.top_block):
    def __init__(self, dl_in, dl_out, ul_in, ul_out, outdir, timeout_ms=100, hwm=-1):
        super().__init__("zmq_broker_recorder")

        os.makedirs(outdir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.dl_path = os.path.join(outdir, f"dl_{ts}.fc32")
        self.ul_path = os.path.join(outdir, f"ul_{ts}.fc32")

        # ZMQ blocks (streaming)
        self.zmq_src_dl = zeromq.req_source(gr.sizeof_gr_complex, 1, dl_in, timeout_ms, False, hwm)
        self.zmq_src_ul = zeromq.req_source(gr.sizeof_gr_complex, 1, ul_in, timeout_ms, False, hwm)

        self.zmq_sink_dl = zeromq.rep_sink(gr.sizeof_gr_complex, 1, dl_out, timeout_ms, False, hwm)
        self.zmq_sink_ul = zeromq.rep_sink(gr.sizeof_gr_complex, 1, ul_out, timeout_ms, False, hwm)

        self.file_dl = blocks.file_sink(gr.sizeof_gr_complex, self.dl_path, False)
        self.file_ul = blocks.file_sink(gr.sizeof_gr_complex, self.ul_path, False)

        # DL: gNB TX -> (record + forward to UE RX)
        self.connect(self.zmq_src_dl, self.file_dl)
        self.connect(self.zmq_src_dl, self.zmq_sink_dl)

        # UL: UE TX -> (record + forward to gNB RX)
        self.connect(self.zmq_src_ul, self.file_ul)
        self.connect(self.zmq_src_ul, self.zmq_sink_ul)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dl-in", required=True, help="e.g. tcp://gnb:2101")
    ap.add_argument("--dl-out", required=True, help="e.g. tcp://*:2000")
    ap.add_argument("--ul-in", required=True, help="e.g. tcp://srsue:2001")
    ap.add_argument("--ul-out", required=True, help="e.g. tcp://*:2100")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--duration", type=int, default=15, help="seconds; 0 = run forever")
    ap.add_argument("--timeout-ms", type=int, default=100)
    args = ap.parse_args()

    tb = ZmqBrokerRecorder(
        dl_in=args.dl_in, dl_out=args.dl_out,
        ul_in=args.ul_in, ul_out=args.ul_out,
        outdir=args.outdir, timeout_ms=args.timeout_ms
    )

    tb.start()
    try:
        if args.duration > 0:
            time.sleep(args.duration)
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        tb.stop()
        tb.wait()
        print(f"[OK] DL Avoided in: {args.dl_in}  ->  saved: {tb.dl_path}")
        print(f"[OK] UL Avoided in: {args.ul_in}  ->  saved: {tb.ul_path}")

if __name__ == "__main__":
    main()
