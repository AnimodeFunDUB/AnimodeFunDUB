# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
"""Animode Fun DUB studio: characters, dialogue, clip preview and delivery."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path

from .editor import apply_edits, dialogue_rows, export_dialogue
from .pipeline import DubbingPipeline, set_reference
from .state import commit_project
from .tasks import identifier

# Kept as the public editor helper name for callers of the previous version.
apply_dialogue = apply_edits

CSS = """
.gradio-container {max-width:1300px!important; background:#0b1016; color:#e2edf2;}
#studio-hero {padding:28px; border:1px solid #25483e; border-radius:16px;
 background:linear-gradient(120deg,#102720,#101820 65%); margin-bottom:18px;}
#studio-hero h1 {color:#65f3b4; font-size:34px; letter-spacing:2px; margin:4px 0;}
#studio-hero p {color:#aac6bd; margin:8px 0;}
#studio-hero .eyebrow {font:12px monospace; letter-spacing:3px; color:#65f3b4;}
"""


def character_rows(job):
    return [
        [s, p["name"], len(p["references"]), p.get("style", "")] for s, p in job["profiles"].items()
    ]


def build_app():
    import gradio as gr

    root = Path(os.environ.get("ANIMODE_OUTPUT_ROOT", "outputs")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    pipeline = DubbingPipeline(
        os.environ.get("ANIMODE_DEVICE", "cpu"), os.environ.get("ASR_MODEL", "large-v3")
    )

    def available_jobs():
        return sorted(p.parent.name for p in root.glob("*/job.json"))

    def populated(job):
        ids = list(job["profiles"])
        message = "Project ready. Review voices, source text and Hindi before final rendering."
        if job["warnings"]:
            message += "\n\n" + "\n\n".join(job["warnings"])
        return (
            job,
            character_rows(job),
            gr.update(choices=ids, value=ids[0]),
            dialogue_rows(job),
            gr.update(
                choices=[str(s["id"]) for s in job["segments"]], value=str(job["segments"][0]["id"])
            ),
            message,
            str(Path(job["directory"]) / "job.json"),
            None,
            [],
            None,
        )

    def analyze(video, language, count, progress=gr.Progress()):
        if not video:
            raise gr.Error("Upload a video first.")
        job = pipeline.analyze(
            video,
            root,
            language,
            int(count) or None,
            progress=lambda value, message: progress(value, desc=message),
        )
        return populated(job)

    def load(selected):
        if not selected:
            raise gr.Error("Select a saved project.")
        job = json.loads((root / identifier(selected) / "job.json").read_text())
        return populated(job)

    def inspect(job, speaker):
        if not job or speaker not in job["profiles"]:
            return "", "", None, ""
        profile = job["profiles"][speaker]
        ref = profile["references"][0] if profile["references"] else {}
        return profile["name"], profile.get("style", ""), ref.get("audio"), ref.get("text", "")

    def assign(job, speaker, name, style, reference, text):
        if not job or speaker not in job["profiles"]:
            raise gr.Error("Analyze a video and select a character first.")
        if "[" in style or "]" in style or len(style) > 200:
            raise gr.Error("Use a voice direction under 200 characters without brackets.")
        updated = copy.deepcopy(job)
        if reference:
            set_reference(updated, speaker, reference, text, name, style, persist=False)
        else:
            updated["profiles"][speaker].update(name=name.strip() or speaker, style=style.strip())
        for key in ("exports", "last_output", "timing_report"):
            updated.pop(key, None)
        commit_project(updated, job.get("revision", 0))
        return (
            updated,
            character_rows(updated),
            "Voice saved. Render again to update exports.",
            str(Path(updated["directory"]) / "job.json"),
            None,
            [],
        )

    def edits(job, rows):
        if not job:
            raise gr.Error("Analyze or load a project first.")
        updated = apply_edits(job, rows)
        commit_project(updated, job.get("revision", 0))
        return updated

    def save_dialogue(job, rows):
        updated = edits(job, rows)
        paths = export_dialogue(updated, Path(updated["directory"]) / "review_exports")
        return (
            updated,
            dialogue_rows(updated),
            "Dialogue saved; final exports need a new render.",
            str(Path(updated["directory"]) / "job.json"),
            list(paths.values()),
            None,
        )

    def preview_clip(job, rows, selected, force, regenerate):
        updated = edits(job, rows)
        path = pipeline.preview_segment(
            updated, int(selected), regenerate=regenerate, force_tempo=force
        )
        return (
            updated,
            str(path),
            "Clip ready. Listen before final rendering.",
            str(Path(updated["directory"]) / "job.json"),
        )

    def render(job, rows, keep, gain, force, accept, master, progress=gr.Progress()):
        updated = edits(job, rows)
        result = pipeline.render(
            updated,
            keep_background=keep,
            background_gain=gain,
            force_tempo=force,
            accept_source_overlap=accept,
            master=master,
            progress=lambda value, message: progress(value, desc=message),
        )
        return (
            updated,
            str(result),
            [str(result), *updated["exports"].values()],
            "Hindi studio exports ready.",
            str(Path(updated["directory"]) / "job.json"),
        )

    def diagnostics():
        from .preflight import check_environment

        return check_environment(device=pipeline.device)

    with gr.Blocks(
        title="Animode Fun DUB Studio", theme=gr.themes.Monochrome(primary_hue="green"), css=CSS
    ) as demo:
        gr.HTML(
            '<div id="studio-hero"><div class="eyebrow">ANIMODE / AUDIO LAB / v2.1</div>'
            "<h1>FUN DUB STUDIO</h1><p>Character voices · Hindi dialogue · Timeline control</p>"
            "<p>Created & maintained by Animode Fun DUB</p></div>"
        )
        state = gr.State(None)
        status = gr.Markdown("Start with Setup, then create or resume a project.")
        with gr.Tab("01 · Project & setup"):
            check = gr.Button("Run setup diagnostics")
            checks = gr.JSON(label="Environment readiness")
            with gr.Row():
                saved = gr.Dropdown(choices=available_jobs(), label="Saved local project")
                refresh = gr.Button("Refresh projects")
                resume = gr.Button("Resume project")
            with gr.Row():
                video = gr.File(
                    label="Anime video (up to 30 minutes)", file_types=["video"], type="filepath"
                )
                language = gr.Dropdown(
                    choices=[
                        ("Japanese", "ja"),
                        ("English", "en"),
                        ("Korean", "ko"),
                        ("Chinese", "zh"),
                        ("Hindi", "hi"),
                    ],
                    value="ja",
                    label="Source language",
                )
                count = gr.Number(
                    value=0, precision=0, minimum=0, maximum=32, label="Speaker count (0 = auto)"
                )
            detect = gr.Button("Analyze characters + translate to Hindi", variant="primary")
        with gr.Tab("02 · Character voices"):
            characters = gr.Dataframe(
                headers=["Speaker ID", "Character name", "Reference clips", "Voice direction"],
                interactive=False,
            )
            speaker = gr.Dropdown(choices=[], label="Character")
            with gr.Row():
                name = gr.Textbox(label="Character name")
                style = gr.Textbox(label="Voice direction", placeholder="confident, energetic")
            reference_preview = gr.Audio(label="Current reference (first clip)", interactive=False)
            current_text = gr.Textbox(label="Reference transcript (first clip)", interactive=False)
            custom = gr.Audio(
                label="Optional custom reference: one clean voice, 2–30 seconds", type="filepath"
            )
            reference_text = gr.Textbox(label="Exact words spoken in the custom reference")
            assign_button = gr.Button("Save character voice", variant="primary")
        with gr.Tab("03 · Dialogue & clip preview"):
            gr.Markdown(
                "Edit **speaker ID, start/end seconds, source transcript and Hindi**. Keep IDs unchanged. "
                "Time windows must remain disjoint. Editing source text does not automatically retranslate Hindi."
            )
            dialogue = gr.Dataframe(
                headers=["ID", "Speaker", "Start", "End", "Source", "Hindi"],
                datatype=["str"] * 6,
                type="array",
                interactive=True,
            )
            save = gr.Button("Save edits + export subtitles")
            with gr.Row():
                segment = gr.Dropdown(choices=[], label="Preview segment ID")
                preview_button = gr.Button("Preview clip (reuse generated audio)")
                regenerate_button = gr.Button("Regenerate this voice clip")
            clip_preview = gr.Audio(label="Hindi clip preview", interactive=False)
            force = gr.Checkbox(
                value=False, label="Allow extreme tempo outside 0.5–2× (may sound unnatural)"
            )
        with gr.Tab("04 · Mix & delivery"):
            with gr.Row():
                keep = gr.Checkbox(value=True, label="Keep music / effects bed")
                gain = gr.Slider(0, 1, value=0.35, label="Background gain")
                master = gr.Checkbox(value=True, label="Master to -16 LUFS / -1 dBTP target")
            accept = gr.Checkbox(
                value=False,
                label="I reviewed simultaneous source dialogue and accept possible missing secondary speech",
            )
            render_button = gr.Button("Render Hindi dub + studio exports", variant="primary")
            result = gr.Video(label="Hindi dubbed preview")
            downloads = gr.Files(label="MP4, master WAV, subtitles, CSV and character tracks ZIP")
            manifest = gr.File(label="Project manifest (local paths; keep private)")
        gr.Markdown(
            "Output language: **हिन्दी**. Voice quality depends on the model and source audio. "
            "This is not an ElevenLabs service or an anime lip-sync engine."
        )
        common = {"concurrency_id": "animode_gpu", "concurrency_limit": 1}
        populated_outputs = [
            state,
            characters,
            speaker,
            dialogue,
            segment,
            status,
            manifest,
            result,
            downloads,
            clip_preview,
        ]
        check.click(diagnostics, outputs=checks, **common)
        refresh.click(lambda: gr.update(choices=available_jobs()), outputs=saved, **common)
        detect.click(analyze, [video, language, count], populated_outputs, **common).then(
            inspect, [state, speaker], [name, style, reference_preview, current_text]
        )
        resume.click(load, [saved], populated_outputs, **common).then(
            inspect, [state, speaker], [name, style, reference_preview, current_text]
        )
        speaker.change(
            inspect, [state, speaker], [name, style, reference_preview, current_text], **common
        ).then(lambda: (None, ""), outputs=[custom, reference_text])
        assign_button.click(
            assign,
            [state, speaker, name, style, custom, reference_text],
            [state, characters, status, manifest, result, downloads],
            **common,
        ).then(inspect, [state, speaker], [name, style, reference_preview, current_text]).then(
            lambda: (None, ""), outputs=[custom, reference_text]
        )
        save.click(
            save_dialogue,
            [state, dialogue],
            [state, dialogue, status, manifest, downloads, result],
            **common,
        )
        preview_button.click(
            preview_clip,
            [state, dialogue, segment, force, gr.State(False)],
            [state, clip_preview, status, manifest],
            **common,
        )
        regenerate_button.click(
            preview_clip,
            [state, dialogue, segment, force, gr.State(True)],
            [state, clip_preview, status, manifest],
            **common,
        )
        render_button.click(
            render,
            [state, dialogue, keep, gain, force, accept, master],
            [state, result, downloads, status, manifest],
            **common,
        )
    return demo


def main():
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(description="Animode Fun DUB Studio")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    root = Path(os.environ.get("ANIMODE_OUTPUT_ROOT", "outputs")).resolve()
    build_app().queue(max_size=8).launch(
        server_name=os.environ.get("ANIMODE_UI_HOST", "127.0.0.1"),
        server_port=args.port,
        allowed_paths=[str(root)],
        max_file_size="1gb",
    )


if __name__ == "__main__":
    main()
