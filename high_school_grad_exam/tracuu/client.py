"""HTTP client for the TraCuu score-lookup API.

A single requests.Session carries the ASP.NET_SessionId cookie that ties a fetched
captcha to subsequent lookups. All three endpoints observed in the live capture are
modelled here: the homepage (session bootstrap), GetCaptcha, and TraCuu (lookup).
"""

import time

import requests

DEFAULT_BASE_URL = "http://tracuudiem2.thuathienhue.edu.vn:81"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:151.0) "
    "Gecko/20100101 Firefox/151.0"
)


class TraCuuClient:
    def __init__(self, base_url=DEFAULT_BASE_URL, timeout=20, user_agent=DEFAULT_USER_AGENT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })

    @property
    def session_id(self):
        return self.session.cookies.get("ASP.NET_SessionId")

    def bootstrap(self):
        """GET the homepage to obtain a fresh ASP.NET_SessionId cookie."""
        resp = self.session.get(self.base_url + "/", timeout=self.timeout)
        resp.raise_for_status()
        return self.session_id

    def reset_session(self):
        """Drop the current session and start a clean one (recover from expiry)."""
        self.session.cookies.clear()
        return self.bootstrap()

    def fetch_captcha(self, choose=1):
        """Fetch a fresh captcha image (bytes). Generates a new code in the session."""
        url = self.base_url + "/TraCuu/GetCaptcha"
        params = {"time": int(time.time() * 1000), "choose": choose}
        headers = {
            "Accept": "image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5",
            "Referer": self.base_url + "/",
        }
        resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.content

    def lookup(self, sbd, confirm_code, search_type="ts10"):
        """POST a score lookup. Returns the raw requests.Response (always HTTP 200 in practice)."""
        url = self.base_url + "/TraCuu/TraCuu"
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": self.base_url,
            "Referer": self.base_url + "/",
        }
        data = {"SearchType": search_type, "sbd": sbd, "ConfirmCode": confirm_code}
        resp = self.session.post(url, data=data, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp
