# Hue city high school entrance exam score scraper

Aggregates scores behind the score portal at 
`http://tracuudiem2.thuathienhue.edu.vn:81/`. 

This program auto-solves capcha using `ddddocr` and exports data in CSV/JSONL.

Request rate is 1req/s.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Usage

```powershell
# 1) Probe the live API
.\.venv\Scripts\python.exe main.py --probe

# 2) Begin scraping
.\.venv\Scripts\python.exe main.py --start 010001 --end 016001

# Rebuild the JSON array:
.\.venv\Scripts\python.exe main.py --compile
```

Key flags: `--captcha-mode {auto,reuse,per_request}`, `--delay`/`--jitter` (pace),
`--max-attempts`, `--no-beta` (default ddddocr model), `--save-captchas`.

The whole scraping process uses a single solved captcha.

## Output record

- json:
```json
{ "sbd": "016001", "status": "found", "fetched_at": "...", "attempts": 1,
  "message": null, "data": { "SBD": "016001", "HOTEN": "...", "DTOAN": "5,50", ... } }
```

- csv:
```csv
sbd,status,STT,MAHS,SBD,HOTEN,GIOITINH,NGAYSINH,NOISINH,DANTOC,CCCD,LOP,HOCSINHTRUONG, ...
```

For educational use only.
