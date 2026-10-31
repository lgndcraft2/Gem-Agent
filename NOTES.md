# Notes

## Status
Working end to end with the real Gemma 4 model on Windows and Python 3.12. Total API spend across all testing was about $0.02. `/api/stats` includes runs from internet outages and from before fixes, so its success rate understates the current build.

## Smoke test results
| Model | Text | Tool calling | Image |
|---|---|---|---|
| `google/gemma-4-26b-a4b-it` (paid) | PASS | PASS | PASS |
| `:free` versions of both models | 429 | 429 | 429 |

The free models were rate-limited by the provider almost all the time: 1 of 12 polling requests succeeded over about 3 minutes. They were never measured for tools or images. **The app therefore uses the paid model through `.env`,** and native tool calling, so the JSON protocol is unused and untested. `google/gemma-4-31b-it` (paid) was not tested.

## Acceptance checklist
| Item | Result | Evidence |
|---|---|---|
| Starts with no installs, page loads at 127.0.0.1:8000 | PASS | Plain `python main.py`, real browser, reading only `.env` |
| Path escapes rejected | PASS | `../x`, `..\x`, `/etc/passwd`, `C:\Windows`, UNC, NTFS stream, real symlink |
| delete_file waits for Approve, nothing on Deny | PASS | 6 of 6 with the real model, plus browser clicks |
| Stops at 12 steps with a readable message | PASS | With a scripted model |
| Wrong key: clear message, no crash | PASS | Real API returned 401 |
| Demo 1: downloads root clear, report.md exists | PASS | 3 of 3 clean runs after the final tool hints, 6-8 steps |
| Demo 2: insights.md names the right top 5 | PASS | 8 of 8 across the last two passes |
| Demo 3: buggy.py prints the correct result | PASS | Prints `Total: 150`, on every run with working internet |
| Project under 5MB | PASS | Under 100KB |
| /api/stats correct | PASS | Matches values computed from runs.jsonl |

Demo 4 (uploaded image): 5 of 5 on the final prompt. Results were checked from the files on disk, not from what the model said. 50 scripted regression checks and 21 PC tool checks also pass, apart from one check that expected the old count of 7 tools.

Final build, real model, no outages: all four demos 2 of 2, delete approval 6 of 6, and no second modal after a Deny. Find a file, open it as a follow-up, open Calculator, and read the screen each worked on one run. The scripted regression checks were last run before the final tool-text changes.

## Bugs found by live testing
- Truncated HTTP replies crashed a run. They now count as a retryable network error.
- report.md was saved inside downloads/. Tool descriptions now say where such files go.
- Demo 1 used 10-11 of 12 steps. Better tool hints cut it to 6-8.
- Adding see_screen made the model doubt uploaded images, so demo 4 failed 3 of 3. Uploads now carry an explicit note.
- "The user must approve" made the model ask in chat instead of calling the tool. Descriptions now say the app handles approval.
- The model used find_file on sandbox files. It's now scoped, and the sandbox is excluded from search.

## Decisions
- Fixed random seed, so every reset gives identical files and answers.
- Tools are defined once, in `tools.TOOLS`.
- One run at a time, since runs share the sandbox. `/api/stream` replays history for late connections.
- Time waiting for approval doesn't count toward the 120 seconds. No answer within 60 seconds counts as no.
- HTTP 401/403 stop at once, because retrying can't fix a key.
- Several tool calls in one reply count as one step.
- A second invalid reply in a row ends the run.
- `run_python` removes `OPENROUTER_API_KEY` from the child environment.
- POST must be `application/json` and the Host must be local, so other websites can't drive the server.
- `.env` is read by a small stdlib loader; real environment variables win.
- The screenshot is captured first and shown in the modal, so you approve the exact image. It is not saved to disk or kept in the conversation.
- Follow-ups keep only earlier tasks and final answers, up to 12 messages.

## Changes beyond the original brief
Requested during the build: the find_file, open_path, open_app, and see_screen tools, follow-up conversation, `.env` for the key, and the visual redesign. The system prompt was extended to cover the new tools, and the size limit was raised from 5MB to 500MB, though the app doesn't need it.

## Known limits
- **Internet is the biggest demo risk.** The connection dropped during two test passes (`getaddrinfo failed`), and every task fails while it's down, with a clear message.
- `run_python` is not a true sandbox; see the README.
- Screenshots and filenames you approve leave your PC.
- `open_app` covers Windows and macOS only. Screen capture has no Linux support.
- Only tested on Windows with Python 3.12. macOS, Linux, and the Python 3.9 minimum are untested.
- The agent can open and look at things, but can't click or type in other apps.
- Follow-ups only remember final answers, so "the second one" works only if the answer listed it.
- Demo 2 is the slowest, at 40-75 seconds per run.
- Run state is in memory; a restart forgets the conversation.

## Stage script
Use a clean desktop, run one test task first, and have a phone hotspot ready.
1. Click "Top 5 products" and point at the gems lighting up as each step runs.
2. Click "Organize downloads" and point at the files flashing in the tree on the right.
3. Type "Where is my file called slides?" using a prepared file, then "Open that file", and click to approve.
4. Click "What's on my screen?", show the preview, and approve it.
5. Say the demo tasks passed every run on the final build with working internet, and each run cost a tiny fraction of a cent. Quote `/api/stats` only after a fresh rehearsal, since old test runs lower it.
