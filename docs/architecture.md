# Studio architecture

Current execution: dub_video.py or animode.webui/animode.api → animode.pipeline.

1. Validate/copy source; separate dialogue and background.
2. Diarize, retaining regular and exclusive annotations.
3. Slice/transcribe exclusive turns; translate to Hindi.
4. Build references from isolated regular turns.
5. Review script/character edits with revision checks.
6. Condition Fish Speech per character; reuse cached generations.
7. Fit disjoint sample windows, mix, master and export.

The Gradio front end uses local sessions and revision-checked saves. The API runs heavy inference
in one isolated subprocess at a time. Task status survives restart; partially completed analysis
is not stage-resumed. Rendering and preview generation acquire project locks.
