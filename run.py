"""Local development: serve the app, optionally after one crawl pass.

    python run.py                  # serve http://127.0.0.1:8000
    python run.py --crawl quick    # run the quick pass once, then serve
"""
import argparse
import os

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Hackfinder locally.")
    parser.add_argument("--crawl", choices=["quick", "browser", "full"], help="run one worker pass first")
    args = parser.parse_args()
    if args.crawl:
        from hackfinder import worker
        worker.main(["--pass", args.crawl])
    uvicorn.run("hackfinder.app:app", host="127.0.0.1", port=int(os.getenv("HF_PORT", "8000")))
