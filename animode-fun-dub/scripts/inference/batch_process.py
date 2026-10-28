# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
"""Sequential video batch runner. Each video gets an isolated resumable project."""

from __future__ import annotations

import argparse
from pathlib import Path


def main():
    from dotenv import load_dotenv

    from animode.pipeline import DubbingPipeline
    from animode.state import atomic_json

    load_dotenv()
    parser = argparse.ArgumentParser(description="Animode Hindi video batch")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("outputs"))
    parser.add_argument("--source-language", choices=["ja", "en", "ko", "zh", "hi"], default="ja")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument("--accept-source-overlap", action="store_true")
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error("Input directory does not exist")
    videos = sorted(
        p for p in args.directory.iterdir() if p.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm"}
    )
    if not videos:
        parser.error("No supported videos found")
    args.output_root.mkdir(parents=True, exist_ok=True)
    pipeline = DubbingPipeline(args.device)
    report = []
    for video in videos:
        item = {"input": str(video.resolve())}
        try:
            job = pipeline.analyze(video, args.output_root, args.source_language)
            item["project"] = job["directory"]
            if not args.analyze_only:
                item["output"] = str(
                    pipeline.render(job, accept_source_overlap=args.accept_source_overlap)
                )
            item["status"] = "ready" if args.analyze_only else "complete"
        except Exception as exc:
            item.update(status="failed", error=str(exc))
        report.append(item)
        atomic_json(args.output_root / "batch_report.json", {"videos": report})
        print(f"{video.name}: {item['status']}")
    raise SystemExit(1 if any(r["status"] == "failed" for r in report) else 0)


if __name__ == "__main__":
    main()
