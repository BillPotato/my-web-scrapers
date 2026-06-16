"""Orchestration: enumerate SBDs, solve captchas, retry, persist, resume.

Captcha modes:
  - per_request : fetch + solve a fresh captcha for every lookup attempt (safe fallback).
  - reuse       : solve ONE captcha up front (prime()) and reuse that code for every lookup.
                  Used when the probe proves the server does not clear the session captcha. If
                  the code ever stops working (session drop), the scraper transparently re-primes.

Because per-attempt OCR accuracy on this captcha is low (~10-15%), reuse mode is the practical
path: priming retries until one code is accepted, then every SBD is a single POST.

Politeness: a configurable delay + jitter is slept before every HTTP request; transient errors
get exponential backoff. The loop is interruptible (Ctrl-C) without data loss.
"""

import os
import random
import time

import requests

from .parser import Outcome, classify


class Scraper:
    def __init__(self, client, solver, storage, *, search_type="ts10", choose=1,
                 captcha_mode="per_request", delay=1.0, jitter=0.5, max_attempts=8,
                 prime_tries=80, lowercase=True, save_captcha_dir=None, quiet=False, log=print):
        self.client = client
        self.solver = solver
        self.storage = storage
        self.search_type = search_type
        self.choose = choose
        self.captcha_mode = captcha_mode
        self.delay = delay
        self.jitter = jitter
        self.max_attempts = max_attempts
        self.prime_tries = prime_tries
        self.lowercase = lowercase
        self.save_captcha_dir = save_captcha_dir
        self.quiet = quiet
        self.log = log
        self._shared_code = None
        self._shared_img = None
        if save_captcha_dir:
            os.makedirs(save_captcha_dir, exist_ok=True)

    # -- helpers -----------------------------------------------------------------

    def _sleep(self):
        time.sleep(self.delay + random.uniform(0, self.jitter))

    def _solve_fresh(self):
        self._sleep()
        img = self.client.fetch_captcha(self.choose)
        code = self.solver.solve(img)
        if self.lowercase:
            code = code.lower()
        return img, code

    def _save_labeled(self, img, code):
        if not self.save_captcha_dir or not img:
            return
        try:
            from .captcha import to_png_bytes
            path = os.path.join(self.save_captcha_dir, f"{code}_{int(time.time()*1000)}.png")
            with open(path, "wb") as fh:
                fh.write(to_png_bytes(img))
        except OSError:
            pass

    # -- reuse priming -----------------------------------------------------------

    def prime(self, sample_sbd):
        """Acquire one confirmed-working captcha code (for reuse mode). Returns True on success."""
        for i in range(1, self.prime_tries + 1):
            img, code = self._solve_fresh()
            if not code:
                continue
            try:
                self._sleep()
                resp = self.client.lookup(sample_sbd, code, self.search_type)
            except requests.RequestException as exc:
                self.log(f"  prime: network error ({exc}); retrying")
                time.sleep(1.0)
                continue
            outcome, _ = classify(resp)
            if outcome in (Outcome.SUCCESS, Outcome.NOT_FOUND):
                self._shared_img, self._shared_code = img, code
                self.log(f"Primed reuse captcha after {i} tr{'y' if i == 1 else 'ies'}: {code!r}")
                return True
        self.log(f"Failed to prime a working captcha in {self.prime_tries} tries.")
        return False

    # -- per-SBD -----------------------------------------------------------------

    def scrape_one(self, sbd):
        backoff = 1.0
        code = img = None

        for attempt in range(1, self.max_attempts + 1):
            if self.captcha_mode == "reuse":
                if not self._shared_code and not self.prime(sbd):
                    continue
                code, img = self._shared_code, self._shared_img
            else:
                img, code = self._solve_fresh()
                if not code:
                    continue

            try:
                self._sleep()
                resp = self.client.lookup(sbd, code, self.search_type)
            except requests.RequestException as exc:
                self.log(f"  [{sbd}] network error: {exc}; backoff {backoff:.0f}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                try:
                    self.client.reset_session()
                except requests.RequestException:
                    pass
                self._shared_code = None
                continue

            outcome, payload = classify(resp)

            if outcome is Outcome.SUCCESS:
                self._save_labeled(img, code)
                return self.storage.make_record(sbd, "found", data=payload, attempts=attempt)

            if outcome is Outcome.NOT_FOUND:
                return self.storage.make_record(sbd, "not_found", attempts=attempt, message=payload)

            if outcome is Outcome.WRONG_CAPTCHA:
                self._shared_code = None  # stale (reuse) or just a miss (per_request)
                continue

            # ERROR: unexpected payload -> backoff, drop captcha, retry
            self.log(f"  [{sbd}] unexpected response: {str(payload)[:120]}")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
            self._shared_code = None
            continue

        return self.storage.make_record(sbd, "failed", attempts=self.max_attempts,
                                         message="exhausted attempts")

    # -- range -------------------------------------------------------------------

    def scrape_range(self, start, end, width=6, progress=None):
        pending = [str(n).zfill(width) for n in range(start, end + 1)
                   if not self.storage.is_done(str(n).zfill(width))]
        if not pending:
            self.log("Nothing to do; all SBDs in range already completed.")
            return end - start + 1
        if self.captcha_mode == "reuse" and not self._shared_code:
            self.prime(pending[0])
        for sbd in pending:
            record = self.scrape_one(sbd)
            self.storage.append(record)
            if not self.quiet:
                self.log(f"[{sbd}] {record['status']} (attempts={record['attempts']})")
            if progress:
                progress.update(1)
        return end - start + 1
