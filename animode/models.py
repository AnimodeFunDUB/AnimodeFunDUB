# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
"""Lazy ASR and Hindi translation adapters; failures never fall back to source text."""

from pathlib import Path

LANGUAGES = {
    "ja": "jpn_Jpan",
    "en": "eng_Latn",
    "ko": "kor_Hang",
    "zh": "zho_Hans",
    "hi": "hin_Deva",
}


class Transcriber:
    def __init__(self, device: str, model: str = "large-v3"):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(
            model, device=device, compute_type="float16" if device == "cuda" else "int8"
        )

    def transcribe(self, audio: Path, language: str) -> str:
        segments, _ = self.model.transcribe(
            str(audio),
            language=language,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip()


class HindiTranslator:
    def __init__(self, language: str, device: str):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        model_id = "facebook/nllb-200-distilled-600M"
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, src_lang=LANGUAGES[language])
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_id).to(device).eval()
        self.device = device
        self.language = language

    def translate(self, text: str) -> str:
        if self.language == "hi":
            return text
        inputs = self.tokenizer(text, return_tensors="pt").to(self.device)
        if inputs["input_ids"].shape[-1] > 512:
            raise ValueError("Dialogue too long for translation; split the source turn.")
        with self.torch.inference_mode():
            tokens = self.model.generate(
                **inputs,
                forced_bos_token_id=self.tokenizer.convert_tokens_to_ids("hin_Deva"),
                max_new_tokens=512,
                num_beams=4,
            )
        result = self.tokenizer.batch_decode(tokens, skip_special_tokens=True)[0].strip()
        if not result or not any("\u0900" <= c <= "\u097f" for c in result):
            raise ValueError(
                "Translation did not produce Hindi Devanagari; review the source transcript."
            )
        return result
