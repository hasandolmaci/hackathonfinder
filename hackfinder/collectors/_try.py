"""Run one collector live and print a summary:  python -m hackfinder.collectors._try devpost"""
import importlib
import json
import sys
import time

from hackfinder.models import Event

cid = sys.argv[1]
mod = importlib.import_module(f"hackfinder.collectors.{cid}")
assert mod.SOURCE["id"] == cid, "SOURCE['id'] must equal module name"
t = time.time()
events = mod.collect()
dt = time.time() - t
assert all(isinstance(e, Event) for e in events), "collect() must return list[Event]"
print(f"{cid}: {len(events)} events in {dt:.1f}s")
for e in events[:5]:
    print(" -", e.title, "|", e.start, "|", e.format, "|", e.location, "|", e.kind, "|", e.url)
missing_start = sum(1 for e in events if e.start is None)
print(f"   missing start: {missing_start}/{len(events)}")
if events:
    print("   signals:", json.dumps(events[0].signals, ensure_ascii=False))
