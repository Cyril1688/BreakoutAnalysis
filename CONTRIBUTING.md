# Contributing to BreakoutAnalysis

Thank you for your interest in contributing!

## Getting Started

1. Fork the repository
2. Follow [SETUP.md](SETUP.md) to get a working local environment
3. Create a branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Open a Pull Request against `main`

## Code Style

- Python 3.10+, follow PEP 8
- Use `logging` (not `print`) for all output
- Add docstrings to public functions
- Keep modules focused — each file should have one clear responsibility

## Never Commit Secrets

- `config/config.json` is gitignored — keep it that way
- `credentials.json` and `token.json` are gitignored
- If you add a new credentials field, add it to `config/config.example.json` with a `YOUR_*` placeholder, not a real value
- Use `src/utils/config_loader.py` to load config — never `open()` config files directly in new modules

Consider using a [pre-commit](https://pre-commit.com/) hook with `detect-secrets` to prevent accidental secret commits.

## Adding a New LLM Model

1. Create a new model class in `src/llms/models/` inheriting from `BaseModel`
2. Implement `construct_prompt()` and `generate_analysis()`
3. Add an entry to `MODEL_CLASS_MAP` in `src/llms/llm_client.py`
4. Add a config entry in `config/config.example.json` with `"name"` matching the map key

## Reporting Bugs

Open a GitHub issue with:
- What you expected to happen
- What actually happened  
- Relevant log output (redact any API keys)
- Your Python version and OS
