ROLE
You are a senior engineer on a hackathon team. Build a working demo in under 60 minutes. Do not ask me questions. Make sensible choices, record them in NOTES.md, and keep moving. Choose simple code that works over clever code. Never claim something works unless you ran it and saw it work.

PROJECT
"Gemma Agent": a local web page where an AI agent, powered by Google's Gemma 4 through an online API, finishes tasks by using tools inside a safe sandbox folder. The user types a task, and a live view shows every step. It must look impressive on a projector.

HARD CONSTRAINTS (read twice)
- My PC is weak: 4GB RAM and almost no free disk space (assume under 50MB free). The whole project must stay under 5MB on disk.
- Use ONLY the Python standard library (http.server / ThreadingHTTPServer, urllib.request, json, threading, queue, pathlib, subprocess, base64, time, os, sys). No pip install, no virtual environment, no Node, no database, no external JS libraries or CDN links (the page must work with no extra downloads).
- Must work on Windows, macOS, and Linux. Do not use shell tools like ls, cat, grep. Implement every tool in pure Python. Use pathlib and sys.executable.
- The server binds to 127.0.0.1 only, port 8000.
- If you cannot write files to my disk, print each file in its own code block labeled with the exact filename, and keep the total number of files small (main.py, agent.py, tools.py, index.html, README.md, NOTES.md).

MODEL ACCESS
- OpenRouter, OpenAI-compatible. POST https://openrouter.ai/api/v1/chat/completions with header Authorization: Bearer $OPENROUTER_API_KEY. Non-streaming model calls (simpler).
- Env vars: MODEL_PRIMARY (default google/gemma-4-31b-it:free), MODEL_FALLBACK (default google/gemma-4-26b-a4b-it:free). Free model IDs change, so at startup call GET https://openrouter.ai/api/v1/models, and if a configured ID is missing, log a warning that lists any available IDs containing "gemma-4".
- On rate-limit (429), 5xx, or timeout: retry twice with backoff, then switch to the fallback model. If both fail, show a clear message in the UI. Never crash.
- Never hardcode keys. Read OPENROUTER_API_KEY from the environment. If missing, the page shows a setup message.

STAGE 0: SMOKE TEST (do this first, before anything else)
Write smoke_test.py that sends three tiny requests to the primary model and prints PASS or FAIL for each:
1. Plain text reply.
2. A request with one tool schema where the model should call it. Check that the reply has valid tool_calls with parseable JSON arguments.
3. A request with one small image (a tiny base64 PNG) sent as an image_url data URI, asking what color it is.
Run it. If the primary fails tool calling, test the fallback. If tool calling fails on both, change the design to a plain-JSON tool protocol: the model replies with a JSON object {"tool": "...", "args": {...}} or {"final": "..."} and you parse it. If image input fails, hide the image upload and the image demo. Record the results in NOTES.md and build around what actually works.

AGENT LOOP (agent.py)
- Send the task, system prompt, and tool schemas. If the reply has tool calls, run them, append the results, and repeat. Stop when the model replies without a tool call.
- Hard cap 12 steps. Temperature 0.2. Tool output truncated to 4000 characters. Total run timeout 120 seconds.
- System prompt: "You are a careful computer agent. Work only inside the sandbox. Plan briefly, use tools, check your result before saying you are done. Keep your final answer under 120 words."
- Invalid tool-call JSON or an unknown tool: send the error text back to the model once and let it retry. Never crash the loop.
- If the response has reasoning/thinking text (for example a "reasoning" field), emit it as an event. Do not depend on it existing.
- Run each task in a background thread. Events go through a queue.

TOOLS (tools.py; every path is resolved against ./sandbox and rejected if it escapes it, including "..", absolute paths, and symlinks)
1. list_files(path)
2. read_file(path): first 8000 characters
3. write_file(path, content)
4. make_dir(path)
5. move_file(src, dst)
6. run_python(file): runs a .py file that is inside the sandbox with sys.executable, cwd=sandbox, 20 second timeout, output truncated. This is the ONLY way to execute code. No general shell.
7. delete_file(path): pauses and needs the user to click Approve in the UI before it runs.
- Define the tool schemas from a single dict so adding a tool takes one edit.

SERVER (main.py, standard library)
- GET / serves index.html.
- POST /api/run (JSON: task, optional image as base64 data URI) returns {run_id}.
- GET /api/stream/{run_id} streams Server-Sent Events: step_start, thinking, tool_call, tool_result, approval_needed, final_answer, error, done. Send a keepalive comment every 10 seconds.
- POST /api/approve/{run_id} (JSON: approve true/false).
- POST /api/reset empties and reseeds the sandbox.
- GET /api/files returns the sandbox file tree as JSON.
- GET /api/stats returns total runs, success rate, average seconds, read from runs.jsonl. Append one line per run: task, steps, model, success, seconds.
- Use ThreadingHTTPServer so streaming and other requests do not block each other.
- Image upload: the browser reads the file with FileReader and sends base64 inside JSON (no multipart parsing). Reject images over 3MB.

SANDBOX SEED DATA (generated by code at start and on reset; the total size stays under 300KB)
- downloads/: 25 small mixed files (txt, csv, md, py, fake invoice txt files) with random names.
- sales.csv: 200 rows (date, product, units, price) over 12 products, so the top 5 by revenue have a clear answer. Compute the correct answer in code and save it to a hidden check file outside the sandbox so you can verify the agent's result.
- buggy.py: a short script with one clear bug (for example an off-by-one in a loop) that prints a wrong result.

FRONTEND (one index.html: vanilla JS and CSS inline, dark theme, large text, no external resources)
- Left: task box, image upload, Run and Reset buttons, four demo-task buttons.
- Center: live step log. Each tool call is a card with an icon, the tool name, its arguments, and its result, with a short slide-in animation. Thinking text sits in a muted collapsible block.
- Right: live sandbox file tree, refreshed after every tool call.
- Top bar: model name in use, step counter (3/12), elapsed time, status dot.
- Approval modal with Approve and Deny.
- The final answer in a highlighted card at the bottom.
- Usable at 1280px on a projector and on a phone.

DEMO TASKS (the buttons; each must work reliably)
1. "Organize the downloads folder into subfolders by file type and write report.md listing what moved."
2. "Read sales.csv, find the top 5 products by revenue, and write insights.md with a short summary."
3. "buggy.py has a bug. Find it, fix it, run it, and show me the output."
4. "Look at the uploaded image and write a short checklist of what you see to notes.md." (only if the smoke test showed image input works)

BUILD ORDER (commit or save after each stage)
0. 0-8 min: smoke test and decisions.
1. 8-20 min: tools.py with sandbox safety, plus a terminal version of the loop that completes demo task 1.
2. 20-35 min: server with streaming, and the full UI.
3. 35-45 min: approval flow, stats, fallback model, image upload.
4. 45-60 min: run each demo task 3 times, fix failures, write README.md and NOTES.md.

ACCEPTANCE CHECKLIST (run these and report PASS or FAIL for each, with evidence)
- python main.py starts with no installs and no errors, and the page loads at http://127.0.0.1:8000.
- Path escape attempts ("../x", "/etc/passwd", "C:\\Windows", a symlink out) are all rejected.
- delete_file does nothing until Approve is clicked, and does nothing on Deny.
- A task that never finishes stops at 12 steps with a readable message.
- A wrong API key shows a clear UI message and does not crash the server.
- Demo task 1: after the run, no loose files remain in downloads/ root, and report.md exists.
- Demo task 2: insights.md names the same top 5 products as the hidden check file.
- Demo task 3: buggy.py runs and prints the correct result.
- Total project size is under 5MB.
- /api/stats shows correct numbers after 3 runs.

DELIVERABLES
main.py, agent.py, tools.py, index.html, smoke_test.py, README.md (setup and run on Windows, macOS, Linux), NOTES.md (decisions, smoke test results, known limits, and a 5-line stage script: which task to run first, what to point at, and one real number from /api/stats to say out loud).
Finish with a short message that lists what works, what is shaky, and the exact command to start the app.

RULES
- Do not add features that are not listed. If you finish early, make the demo tasks more reliable.
- If something blocks you for more than 5 minutes, use the simplest workaround, note it in NOTES.md, and move on.
- Do not say "done" until the acceptance checklist has been run.