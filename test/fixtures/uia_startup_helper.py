"""Synthetic startup protocol only; never creates a window or calls UI Automation."""
import json
import os
import sys
import threading

challenge, mode = sys.argv[1:3]
packet = {"id": challenge, "result": {"fixture": "uia", "version": 1,
          "pid": os.getpid(), "hwnd": 101, "challenge": challenge}}
if mode == "wait":
    threading.Event().wait(30)
elif mode == "oversize":
    print("x" * 1025, flush=True)
elif mode == "nested_duplicate":
    print('{"id":"' + challenge + '","result":{"pid":42,"pid":42}}', flush=True)
elif mode == "duplicate":
    print('{"id":"' + challenge + '","id":"' + challenge + '","result":{}}', flush=True)
else:
    if mode == "extra":
        packet["extra"] = "forbidden"
    if mode == "wrong":
        packet["id"] = "wrong"
    print(json.dumps(packet), flush=True)
    if mode == "repeat":
        print(json.dumps(packet), flush=True)
sys.stdin.buffer.read(1)
