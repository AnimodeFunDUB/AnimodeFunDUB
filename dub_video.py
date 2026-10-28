#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
"""Animode Fun DUB CLI. Created and maintained by Animode Fun DUB."""

import argparse
import json
import logging
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Animode Fun DUB — multi-character Hindi dubbing")
    parser.add_argument("video", nargs="?", type=Path)
    parser.add_argument("--job", type=Path, help="Render an existing edited job.json")
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument("--source-language", choices=["ja", "en", "ko", "zh", "hi"], default="ja")
    parser.add_argument("--speakers", type=int, help="Known count; omit for automatic detection")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--asr-model", default="large-v3")
    parser.add_argument("--work-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--voices", type=Path, help="JSON speaker -> {audio,text,name,style}")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--no-background", action="store_true")
    parser.add_argument("--background-gain", type=float, default=0.35)
    parser.add_argument("--force-tempo", action="store_true", help="Allow tempo outside 0.5–2x")
    parser.add_argument(
        "--accept-source-overlap",
        action="store_true",
        help="Acknowledge reviewed simultaneous source dialogue",
    )
    parser.add_argument("--no-master", action="store_true", help="Skip loudness mastering")
    args = parser.parse_args()
    if bool(args.video) == bool(args.job):
        parser.error("Provide exactly one video or --job.")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from dotenv import load_dotenv

    load_dotenv()
    from animode.pipeline import DubbingPipeline, save_job, set_reference

    pipeline = DubbingPipeline(args.device, args.asr_model)
    try:
        job = (
            json.loads(args.job.read_text(encoding="utf-8"))
            if args.job
            else pipeline.analyze(args.video, args.work_dir, args.source_language, args.speakers)
        )
        if args.voices:
            for speaker, voice in json.loads(args.voices.read_text(encoding="utf-8")).items():
                reference = Path(voice["audio"])
                if not reference.is_absolute():
                    reference = args.voices.resolve().parent / reference
                set_reference(
                    job,
                    speaker,
                    reference,
                    voice["text"],
                    voice.get("name", ""),
                    voice.get("style", ""),
                )
        print(f"Job: {save_job(job)}")
        for warning in job["warnings"]:
            logging.warning(warning)
        if not args.analyze_only:
            print(
                pipeline.render(
                    job,
                    args.output,
                    keep_background=not args.no_background,
                    background_gain=args.background_gain,
                    workers=args.workers,
                    force_tempo=args.force_tempo,
                    accept_source_overlap=args.accept_source_overlap,
                    master=not args.no_master,
                )
            )
    except Exception as exc:
        logging.error("Dubbing stopped: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
