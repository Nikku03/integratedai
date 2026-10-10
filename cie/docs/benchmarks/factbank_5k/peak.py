"""Run a command and append its wall time and peak memory (of the command and its children) to a JSON-lines file.

    python peak.py OUT.jsonl -- command args...
"""
import json
import resource
import subprocess
import sys
import time

out, cmd = sys.argv[1], sys.argv[sys.argv.index("--") + 1:]
t = time.perf_counter()
code = subprocess.call(cmd)
rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss  # KiB on Linux
with open(out, "a") as f:
    f.write(json.dumps({"cmd": " ".join(cmd[-6:]), "seconds": round(time.perf_counter() - t, 1), "peak_mb": round(rss / 1024, 1),
                        "exit": code}) + "\n")
sys.exit(code)
