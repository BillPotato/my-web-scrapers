"""CLI for the TraCuu score scraper.

Examples
--------
  python main.py --probe                         # research the live API, recommend settings
  python main.py --start 010001 --end 016001     # full gentle scrape -> output/results.csv
  python main.py --compile                        # rewrite/clean output/results.csv and exit
"""

import argparse
import random
import sys
import time

import requests

from tracuu.client import TraCuuClient, DEFAULT_BASE_URL
from tracuu.captcha import CaptchaSolver
from tracuu.parser import Outcome, classify
from tracuu.storage import Storage

DEFAULT_PROBE_SBDS = ["010001", "010002", "010003", "015000", "016000", "016001"]


def _finalize(storage):
    n = storage.flush()
    if n >= 0:
        print(f"Wrote {n} records -> {storage.csv_path}")
    print(f"Counts: {storage.counts()}")


def _gentle_sleep(args):
    time.sleep(args.delay + random.uniform(0, args.jitter))


def _attempt(client, solver, sbd, search_type, lowercase=True):
    """One captcha-solve + lookup. Returns (Outcome, code, payload)."""
    img = client.fetch_captcha()
    code = solver.solve(img)
    if lowercase:
        code = code.lower()
    outcome, payload = classify(client.lookup(sbd, code, search_type))
    return outcome, code, payload


def run_probe(client, args):
    print("== PROBE ==")
    session_id = client.bootstrap()
    print(f"Session bootstrapped: ASP.NET_SessionId={session_id}")
    target = args.probe_sbds[0]

    # 1) Compare both ddddocr models by end-to-end success rate against a known-valid SBD.
    #    Submitting ddddocr's lowercase guess: if lookups succeed, the backend is effectively
    #    case-insensitive (the model cannot be reproducing the captcha's true mixed case).
    best = None
    for beta in (False, True):
        label = "beta" if beta else "default"
        solver = CaptchaSolver(beta=beta)
        success = wrong = other = 0
        for _ in range(args.probe_n):
            _gentle_sleep(args)
            try:
                outcome, _code, _ = _attempt(client, solver, target, args.search_type)
            except requests.RequestException as exc:
                other += 1
                print(f"  [{label}] request error: {exc}")
                continue
            if outcome is Outcome.SUCCESS:
                success += 1
            elif outcome is Outcome.WRONG_CAPTCHA:
                wrong += 1
            else:
                other += 1
        rate = success / max(1, args.probe_n)
        print(f"  model={label:7s} success={success}/{args.probe_n} "
              f"wrong_captcha={wrong} other={other}  -> solve rate {rate:.0%}")
        if best is None or rate > best[2]:
            best = (label, solver, rate, beta)

    label, solver, rate, beta = best
    print(f"\nBest model: {label} (solve rate {rate:.0%})")
    if rate == 0:
        print("WARNING: 0% success. Backend may be case-sensitive (ddddocr emits lowercase),")
        print("         or the captcha style defeats the model. Investigate before a full run.")
    else:
        print("Backend accepts ddddocr's lowercase guesses -> effectively CASE-INSENSITIVE.")

    # 2) Captcha-reuse test: get one confirmed-correct code, then reuse it (no re-fetch)
    #    across several other valid SBDs.
    print("\n-- captcha reuse test --")
    confirmed_code = None
    for _ in range(args.probe_n):
        _gentle_sleep(args)
        try:
            outcome, code, _ = _attempt(client, solver, target, args.search_type)
        except requests.RequestException:
            continue
        if outcome is Outcome.SUCCESS:
            confirmed_code = code
            break

    if not confirmed_code:
        print("  Could not obtain a confirmed-correct code; skipping reuse test.")
        recommended = "per_request"
    else:
        print(f"  Confirmed-correct code: {confirmed_code!r}; reusing on other SBDs...")
        reuse_sbds = [s for s in args.probe_sbds[1:] if s != target][:4]
        reuse_ok = 0
        for sbd in reuse_sbds:
            _gentle_sleep(args)
            try:
                outcome, _ = classify(client.lookup(sbd, confirmed_code, args.search_type))
            except requests.RequestException as exc:
                print(f"    {sbd}: request error {exc}")
                continue
            accepted = outcome in (Outcome.SUCCESS, Outcome.NOT_FOUND)
            reuse_ok += int(accepted)
            print(f"    {sbd}: {outcome.value} (captcha accepted={accepted})")
        recommended = "reuse" if reuse_sbds and reuse_ok == len(reuse_sbds) else "per_request"

    print("\n== RECOMMENDATION ==")
    print(f"  model: {'beta' if beta else 'default'}  ->  "
          f"run with {'(default)' if beta else '--no-beta'}")
    print(f"  --captcha-mode {recommended}")
    if recommended == "reuse":
        print("  Reuse works: one solved captcha covers the whole range. Fast run expected.")
    elif rate:
        per_sbd = 1 / rate
        secs = (args.end_count) * per_sbd * 2 * (args.delay + args.jitter / 2)
        print(f"  Per-request mode: ~{per_sbd:.1f} attempts/SBD; rough ETA for "
              f"{args.end_count} SBDs ~ {secs/3600:.1f} h at the current pace.")
    return 0


def run_scrape(client, args):
    storage = Storage(args.out)
    solver = CaptchaSolver(beta=args.beta)
    client.bootstrap()

    from tracuu.scraper import Scraper
    mode = "per_request" if args.captcha_mode == "auto" else args.captcha_mode
    scraper = Scraper(
        client, solver, storage,
        search_type=args.search_type, choose=args.choose, captcha_mode=mode,
        delay=args.delay, jitter=args.jitter, max_attempts=args.max_attempts,
        lowercase=not args.no_lowercase, quiet=args.quiet,
        save_captcha_dir=("samples/labeled" if args.save_captchas else None),
    )

    start, end = int(args.start), int(args.end)
    width = len(args.start)
    progress = None
    try:
        from tqdm import tqdm
        already = sum(1 for n in range(start, end + 1) if storage.is_done(str(n).zfill(width)))
        progress = tqdm(total=end - start + 1, initial=already, unit="sbd")
    except Exception:
        pass

    try:
        scraper.scrape_range(start, end, width=width, progress=progress)
    except KeyboardInterrupt:
        print("\nInterrupted; progress saved. Re-run the same command to resume.")
    finally:
        if progress:
            progress.close()
        _finalize(storage)
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="Direct-API scraper for tracuudiem2 score lookup.")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--start", default="010001", help="first SBD (zero-padded)")
    p.add_argument("--end", default="016001", help="last SBD (inclusive)")
    p.add_argument("--search-type", default="ts10")
    p.add_argument("--choose", type=int, default=1)
    p.add_argument("--out", default="output")
    p.add_argument("--delay", type=float, default=1.0, help="base seconds between requests")
    p.add_argument("--jitter", type=float, default=0.5, help="added random 0..jitter seconds")
    p.add_argument("--max-attempts", type=int, default=8)
    p.add_argument("--captcha-mode", choices=["auto", "reuse", "per_request"], default="per_request")
    p.add_argument("--beta", dest="beta", action="store_true", default=True,
                   help="use ddddocr beta model (default on)")
    p.add_argument("--no-beta", dest="beta", action="store_false")
    p.add_argument("--no-lowercase", action="store_true",
                   help="submit the solver guess as-is instead of lowercasing")
    p.add_argument("--save-captchas", action="store_true",
                   help="save confirmed (image,code) pairs to samples/labeled")
    p.add_argument("--quiet", action="store_true",
                   help="suppress per-SBD log lines (keep progress bar + prime/error logs)")
    p.add_argument("--probe", action="store_true", help="research the live API and exit")
    p.add_argument("--probe-n", type=int, default=12, help="attempts per model in probe")
    p.add_argument("--probe-sbds", nargs="+", default=DEFAULT_PROBE_SBDS)
    p.add_argument("--compile", action="store_true",
                   help="rewrite/clean results.csv from existing data and exit")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.end_count = int(args.end) - int(args.start) + 1

    if args.compile:
        _finalize(Storage(args.out))
        return 0

    client = TraCuuClient(base_url=args.base_url)
    if args.probe:
        return run_probe(client, args)
    return run_scrape(client, args)


if __name__ == "__main__":
    sys.exit(main())
