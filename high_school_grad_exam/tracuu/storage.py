"""CSV-native, resumable persistence.

results.csv is the single source of truth and the user-facing deliverable. Records are held
in memory and the whole file is atomically rewritten (temp file + os.replace) every
``flush_interval`` records and on exit, so the file on disk is always valid CSV (never a torn
line) and never contains duplicate SBDs. Resume reads completed SBDs straight from results.csv.

UTF-8 BOM makes Excel render Vietnamese correctly; csv quoting keeps comma-decimal scores like
'5,50' inside a single cell. The student record schema is fixed (verified identical across all
records), so a stable header can be written up front for live streaming.
"""

import csv
import os
from datetime import datetime, timezone

TERMINAL_STATUSES = ("found", "not_found")

# Fixed student-object field order (verified constant across every record).
DATA_FIELDS = [
    "STT", "MAHS", "SBD", "HOTEN", "GIOITINH", "NGAYSINH", "NOISINH", "DANTOC", "CCCD", "LOP",
    "HOCSINHTRUONG", "DIABAN", "NV1", "NV2", "NV3", "NVC", "DTNT", "DUT", "DKK", "DTHCS",
    "DVAN", "DTOAN", "DNN", "DC", "DXETCHUYEN", "DDTNT", "DTHPT", "MATRUONGTRUNGTUYEN",
    "KETQUA", "GHICHU", "KHOI", "DOT",
]
COLUMNS = ["sbd", "status"] + DATA_FIELDS
_DATA_FIELD_SET = set(DATA_FIELDS)


class Storage:
    def __init__(self, out_dir="output", flush_interval=25):
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.csv_path = os.path.join(out_dir, "results.csv")
        self.flush_interval = flush_interval
        self._records = self._load()  # sbd -> record
        self._dirty = 0
        self._warned_keys = set()

    def _load(self):
        records = {}
        if os.path.exists(self.csv_path):
            with open(self.csv_path, encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    sbd = (row.get("sbd") or "").strip()
                    if not sbd:
                        continue
                    status = row.get("status")
                    data = {k: row.get(k, "") for k in DATA_FIELDS} if status == "found" else None
                    records[sbd] = {"sbd": sbd, "status": status, "data": data}
        return records

    def is_done(self, sbd):
        rec = self._records.get(sbd)
        return rec is not None and rec.get("status") in TERMINAL_STATUSES

    def counts(self):
        out = {"found": 0, "not_found": 0, "failed": 0}
        for rec in self._records.values():
            status = rec.get("status", "failed")
            out[status] = out.get(status, 0) + 1
        return out

    @staticmethod
    def make_record(sbd, status, data=None, attempts=None, message=None):
        return {
            "sbd": sbd,
            "status": status,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "attempts": attempts,
            "message": message,
            "data": data,
        }

    def append(self, record):
        data = record.get("data") or {}
        unknown = set(data) - _DATA_FIELD_SET
        if unknown and unknown - self._warned_keys:
            self._warned_keys |= unknown
            print(f"[storage] WARNING: unexpected data fields dropped from CSV: {sorted(unknown)}")
        self._records[record["sbd"]] = record
        self._dirty += 1
        if self._dirty >= self.flush_interval:
            self.flush()

    def flush(self):
        """Atomically rewrite results.csv from in-memory records. Returns rows written (or -1
        if the file was locked, e.g. open in Excel — data stays in memory for the next flush)."""
        records = sorted(self._records.values(), key=lambda r: r["sbd"])
        tmp = self.csv_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
                writer.writeheader()
                for rec in records:
                    row = {"sbd": rec["sbd"], "status": rec.get("status")}
                    row.update(rec.get("data") or {})
                    writer.writerow(row)
            os.replace(tmp, self.csv_path)
            self._dirty = 0
            return len(records)
        except OSError as exc:
            print(f"[storage] could not write {self.csv_path} ({exc}); "
                  f"is it open in Excel? Keeping data in memory, will retry.")
            return -1

    # Backwards-compatible alias used by the CLI's explicit compile/finalize step.
    def compile_csv(self):
        return self.flush()
