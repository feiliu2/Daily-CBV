"""Phoenix execution link -> total / pass / fail / blocked / not-run.

Usage:
    python phoenix_status.py "<phoenix execution URL>"
    python phoenix_status.py "<raw cycle string>"

How it works (three HSDES queries, joined locally):
  1. PLANNED set  -- test_case where test_case.test_cycle contains <cycle>
     (test_case.test_cycle is a MULTI-VALUE field listing every cycle a TC is
      planned into; this is what Phoenix counts as "Total")
  2. RESULT set   -- test_result where test_result.test_cycle = <cycle>
     (a test_result article only exists once somebody records an outcome)
  3. Join on test_result.parent_id == test_case.id. Planned TCs with no result
     row are what Phoenix displays as "Not Run".
  4. CYCLE itself -- the cycle is a `milestone` article whose title IS the cycle
     string. That is where submitted_date / eta_request / owner live.
"""
import sys
import re
import json
from urllib.parse import urlparse, parse_qs, unquote
from collections import Counter

import hsdes_adhoc as h

TC_FIELDS = [
    ("id", "id"),
    ("title", "title"),
    ("component", "component"),
    ("priority", "priority"),
    ("owner", "owner"),
    ("tag", "tag"),
    ("configuration", "central_firmware.test_case.configuration"),
]
TR_FIELDS = [
    ("id", "id"),
    ("parent_id", "parent_id"),
    ("title", "title"),
    ("status", "status"),
    ("status_reason", "status_reason"),
    ("reason", "reason"),
    ("owner", "owner"),
    ("submitted_date", "submitted_date"),
    ("closed_date", "closed_date"),
    ("actual_start", "central_firmware.test_result.actual_start"),
    ("actual_end", "central_firmware.test_result.actual_end"),
]


def extract_cycle(arg):
    """Pull the cycle string out of a Phoenix URL, or pass a raw cycle through."""
    if arg.startswith("http"):
        qs = parse_qs(urlparse(arg).query)
        if "cycle" not in qs:
            raise SystemExit("[ERROR] URL has no 'cycle' parameter")
        return unquote(qs["cycle"][0])
    return arg


def bucket(status_reason):
    """Map an HSDES test_result status_reason onto a Phoenix execution bucket."""
    sr = (status_reason or "").lower()
    if sr.startswith("complete.pass"):
        return "pass"
    if sr.startswith("complete.fail"):
        return "fail"
    if sr.startswith("blocked"):
        return "blocked"
    if sr.startswith("rejected"):
        return "rejected"
    if sr.startswith("complete"):
        return "other_complete"
    return "not_run"          # open.not_run, open.in_progress, ...


MS_FIELDS = [
    ("id", "id"),
    ("title", "title"),
    ("status", "status"),
    ("status_reason", "status_reason"),
    ("owner", "owner"),
    ("submitted_by", "submitted_by"),
    ("submitted_date", "submitted_date"),
    ("updated_date", "updated_date"),
    ("eta_request", "eta_request"),
    ("eta_request_ww", "central_firmware.milestone.eta_request_ww"),
    ("owner_team", "central_firmware.milestone.owner_team"),
    ("plc_milestone", "central_firmware.milestone.plc_milestone"),
    ("release", "release"),
]


def cycle_milestone(cycle):
    """The cycle itself is a `milestone` article titled exactly like the cycle."""
    r = h.run(
        h.build_xml(
            "central_firmware.milestone",
            [("title", "contains", f"'%{cycle}%'", "text")],
            MS_FIELDS,
        ),
        1, 5,
    )
    for d in r.get("data", []):
        if d.get("title") == cycle:
            return d
    return (r.get("data") or [None])[0]


def collect(cycle):
    planned = h.fetch_all(
        h.build_xml(
            "central_firmware.test_case",
            [("central_firmware.test_case.test_cycle", "contains", f"'%{cycle}%'", "text")],
            TC_FIELDS,
        ),
        page=100, cap=5000,
    )
    results = h.fetch_all(
        h.build_xml(
            "central_firmware.test_result",
            [("central_firmware.test_result.test_cycle", "in", f"'{cycle}'", "singlesel")],
            TR_FIELDS,
        ),
        page=100, cap=5000,
    )
    return planned, results


def summarize(cycle):
    planned, results = collect(cycle)
    tcs = planned.get("data", [])
    trs = results.get("data", [])

    by_tc = {}                                  # test_case id -> best result row
    for r in trs:
        by_tc.setdefault(r.get("parent_id"), r)

    counts = Counter()
    rows = []
    for tc in tcs:
        r = by_tc.get(tc["id"])
        b = bucket(r.get("status_reason") if r else None)
        counts[b] += 1
        rows.append({
            "tc_id": tc["id"],
            "title": tc.get("title"),
            "component": tc.get("component"),
            "priority": tc.get("priority"),
            "bucket": b,
            "status_reason": (r or {}).get("status_reason"),
            "result_id": (r or {}).get("id"),
            "executed_by": (r or {}).get("owner"),
            "actual_start": (r or {}).get("actual_start"),
            "actual_end": (r or {}).get("actual_end"),
            "submitted_date": (r or {}).get("submitted_date"),
            "closed_date": (r or {}).get("closed_date"),
        })

    orphan = [r for r in trs if r.get("parent_id") not in {t["id"] for t in tcs}]
    sub_dates = sorted(r["submitted_date"] for r in trs if r.get("submitted_date"))
    return {
        "cycle": cycle,
        "milestone": cycle_milestone(cycle),
        "first_result_submitted": sub_dates[0] if sub_dates else None,
        "last_result_submitted": sub_dates[-1] if sub_dates else None,
        "total": len(tcs),
        "pass": counts["pass"],
        "fail": counts["fail"],
        "blocked": counts["blocked"],
        "not_run": counts["not_run"],
        "rejected": counts["rejected"],
        "other_complete": counts["other_complete"],
        "result_records": len(trs),
        "orphan_results": len(orphan),
        "rows": rows,
    }


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cycle = extract_cycle(sys.argv[1])
    s = summarize(cycle)

    executed = s["pass"] + s["fail"] + s["blocked"] + s["other_complete"]
    pct = lambda n: f"{n / s['total'] * 100:.1f}%" if s["total"] else "-"

    print("=" * 78)
    print("  " + s["cycle"])
    print("=" * 78)
    ms = s.get("milestone") or {}
    if ms:
        print(f"  Milestone : {ms.get('id')}  (owner {ms.get('owner')}"
              f", team {ms.get('owner_team')}, {ms.get('plc_milestone')})")
        print(f"  Submitted : {ms.get('submitted_date')}   by {ms.get('submitted_by')}")
        print(f"  ETA req.  : {ms.get('eta_request')}   (WW {ms.get('eta_request_ww')})")
    else:
        print("  Milestone : NOT FOUND (no milestone article matches this cycle title)")
    print(f"  Results   : first submitted {s.get('first_result_submitted')}"
          f" / last {s.get('last_result_submitted')}")
    print("-" * 78)
    print(f"  Total     : {s['total']:>4}")
    print(f"  Pass      : {s['pass']:>4}   {pct(s['pass'])}")
    print(f"  Fail      : {s['fail']:>4}   {pct(s['fail'])}")
    print(f"  Blocked   : {s['blocked']:>4}   {pct(s['blocked'])}")
    print(f"  Not Run   : {s['not_run']:>4}   {pct(s['not_run'])}")
    if s["rejected"]:
        print(f"  Rejected  : {s['rejected']:>4}   {pct(s['rejected'])}")
    if s["other_complete"]:
        print(f"  Other cmpl: {s['other_complete']:>4}   {pct(s['other_complete'])}")
    print("-" * 78)
    print(f"  Executed  : {executed}/{s['total']} = {pct(executed)}"
          f"   |  Pass rate of executed: "
          f"{s['pass'] / executed * 100:.1f}%" if executed else "")
    print(f"  (HSDES test_result records for this cycle: {s['result_records']};"
          f" orphan: {s['orphan_results']})")
    print("=" * 78)

    out = f"status_{re.sub(r'[^A-Za-z0-9]+', '_', cycle)[-60:]}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    print(f"  detail -> {out}")


if __name__ == "__main__":
    main()
