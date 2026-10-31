# Gemma Agent

A local web page where a Gemma 4 agent finishes tasks while you watch every step live. It works on files in a sandbox folder, and with your click it can also find, open, and look at things on your PC. It needs Python 3.9 or newer and nothing else: no pip, no Node, no downloads.

## Setup

Get a key from https://openrouter.ai/keys. Create a file named `.env` next to `main.py`:

```
OPENROUTER_API_KEY=your-key
MODEL_PRIMARY=google/gemma-4-26b-a4b-it
```

The paid model is strongly recommended: testing cost about $0.02 for over 60 runs, while the free models were rate-limited almost all the time. Never commit `.env`; the included `.gitignore` covers it.

Then start the app:

- **Windows:** `python main.py`
- **macOS / Linux:** `python3 main.py`

Open http://127.0.0.1:8000. If the key is missing, the page shows setup steps.

To check the model before a demo, run `python smoke_test.py`. It sends three real requests (text, tool call, image) and prints PASS or FAIL for each.

## What you can ask

- Work on sandbox files: use the demo buttons.
- "Where is my file called budget?" searches your user folders by filename.
- "Open that file", "Open the calculator", "Open example.com" ask for your click first.
- "What's on my screen?" shows you the screenshot and sends it only if you approve.

Follow-up questions work. **Start over** clears the conversation and rebuilds the sandbox, and the demo buttons start a new conversation.

## Settings

Set these in `.env` or as environment variables. Environment variables win.

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | none | Required |
| `MODEL_PRIMARY` | `google/gemma-4-31b-it:free` | Model tried first |
| `MODEL_FALLBACK` | `google/gemma-4-26b-a4b-it:free` | Used when the primary keeps failing |
| `TOOL_PROTOCOL` | `native` | Set to `json` if a model can't do tool calling (untested) |
| `IMAGE_ENABLED` | `1` | Set to `0` to hide image upload |

## Files

- `main.py`: web server and API
- `agent.py`: the agent loop. `python agent.py "your task"` runs it in the terminal, where anything needing approval is denied
- `tools.py`: the tools, path safety, and seed data
- `index.html`: the page
- `smoke_test.py`: live API check

`sandbox/`, `runs.jsonl`, and `.check.json` are generated. Starting the server or pressing Start over rebuilds `sandbox/` and erases anything in it.

## Safety

**Limits that are enforced**
- File tools can't leave `sandbox/`: `..`, absolute paths, and links pointing out are rejected.
- Deleting, opening anything, opening an app, and sharing a screenshot all wait for your click. No answer within 60 seconds counts as no.
- `open_path` only takes http(s) links and visible items in your user folders. It refuses hidden folders, `AppData`, and anything that would run, such as `.exe`, `.bat`, and `.py`.
- `open_app` only opens apps on a short list: Calculator, Notepad, Paint.
- `find_file` reads filenames only, never contents.

**What is not protected**
- `run_python` is not a real sandbox. It starts in the sandbox folder and doesn't receive your API key as an environment variable, but the script runs as you. A model-written script could reach any file you can, including `.env`. Use a key you're happy to revoke.
- Screenshots you approve, filenames that are found, and your tasks go to OpenRouter and the model provider. Don't approve a screenshot showing anything private.
- The audience sees file paths and screenshots on the projector. Use a clean desktop and a prepared folder.
- Text on screen or in files could try to trick the model. The system prompt says to ignore such instructions, and the approval click is the real safeguard, so read what you're approving.
