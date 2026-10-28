# Contributing to Animode Fun DUB

Thanks for helping improve the Studio.

## Setup

```bash
python3.11 -m venv .venv && source .venv/bin/activate
python -m pip install -e '.[test]'
```

## Before opening a pull request

```bash
python -m pytest tests/animode -q
python -m ruff check animode dub_video.py scripts/inference/batch_process.py tests/animode
```

## Rules

- Keep pull requests focused: one change, with tests where behavior changes.
- Never commit `.env`, tokens, model weights, voice samples or generated media.
- Do not remove or alter the copyright, NOTICE or credit lines.

## License

By contributing, you agree that your contribution is released under the
[MIT License](LICENSE), (c) Animode Fun DUB.
