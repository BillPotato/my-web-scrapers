# TraCuu score scraper

Talks directly to the public score-lookup API behind
`http://tracuudiem2.thuathienhue.edu.vn:81/`, auto-solves the captcha, enumerates the
known SBD (student-number) range, and exports every result to JSON.

The data is public (no password is required to look up a score). This tool is deliberately
**gentle** (one connection, ~1 request/second with jitter) and **resumable**, for a
programming challenge — not for hammering the server.

## How it works

1. A `requests.Session` carries the `ASP.NET_SessionId` cookie that ties a captcha to lookups.
2. `GET /TraCuu/GetCaptcha` returns a small PNG; [ddddocr](https://github.com/sml2h3/ddddocr)
   reads the 5-character code offline.
3. `POST /TraCuu/TraCuu` with `SearchType`, `sbd`, `ConfirmCode` returns JSON. Responses are
   classified as **success** (student object), **wrong captcha** (retry), **not found** (stop),
   or **error** (back off).
4. Results stream to `output/results.jsonl` (crash-safe); `output/results.json` is the compiled
   array. Re-running skips already-completed SBDs.

## Layout

```
main.py              # CLI + probe
tracuu/
  client.py          # HTTP session: bootstrap, fetch_captcha, lookup
  captcha.py         # ddddocr solver (raw-or-base64 PNG, truncation-tolerant)
  parser.py          # response -> Outcome {SUCCESS, WRONG_CAPTCHA, NOT_FOUND, ERROR}
  storage.py         # resumable JSONL + checkpoint + final JSON
  scraper.py         # enumerate, retry loop, rate limiting
output/              # results.jsonl, results.json
samples/             # captcha samples (+ optional self-labeled pairs)
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`ddddocr` is fully offline (bundles its ONNX model); no Tesseract or external service needed.

## Usage

```powershell
# 1) Probe the live API: measures solver accuracy, infers case-sensitivity, tests captcha reuse
.\.venv\Scripts\python.exe main.py --probe

# 2) Full gentle scrape of the default range 010001-016001
.\.venv\Scripts\python.exe main.py --start 010001 --end 016001

# Resume is automatic (re-run the same command). Rebuild the JSON array anytime:
.\.venv\Scripts\python.exe main.py --compile
```

Key flags: `--captcha-mode {auto,reuse,per_request}`, `--delay`/`--jitter` (pace),
`--max-attempts`, `--no-beta` (default ddddocr model), `--save-captchas`.

If the probe reports `--captcha-mode reuse` works, the whole range is covered by a single
solved captcha and the run is fast; otherwise it solves per lookup.

## Output record

```json
{ "sbd": "016001", "status": "found", "fetched_at": "...", "attempts": 1,
  "message": null, "data": { "SBD": "016001", "HOTEN": "...", "DTOAN": "5,50", ... } }
```

For educational / challenge use only.
