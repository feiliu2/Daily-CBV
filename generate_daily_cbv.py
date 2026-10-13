"""Generate a compact, email-style HTML report for one Phoenix test cycle."""
import argparse
import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


HERE = Path(__file__).resolve().parent
SOURCE_DIR = HERE.parent / "BIOS BAT Blue EBlue Execution Status"
if not (SOURCE_DIR / "phoenix_status.py").is_file():
    SOURCE_DIR = HERE
sys.path.insert(0, str(SOURCE_DIR))
from phoenix_status import extract_cycle, summarize  # noqa: E402


def esc(value):
    return html.escape(str(value or ""), quote=True)


def cache_name(cycle):
    return f"status_{re.sub(r'[^A-Za-z0-9]+', '_', cycle)[-60:]}.json"


def load_summary(cycle, use_cache):
    name = cache_name(cycle)
    candidates = [HERE / name, SOURCE_DIR / name]
    if use_cache:
        for path in candidates:
            if path.exists():
                with path.open(encoding="utf-8") as file:
                    return json.load(file)
        raise SystemExit(f"[ERROR] no cached data found for {cycle}")

    data = summarize(cycle)
    with (HERE / name).open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    return data


def pct(count, total):
    return f"{count / total * 100:.1f}%" if total else "0.0%"


def result_rows(summary, include_other):
    groups = {}
    for row in summary["rows"]:
        component = row.get("component") or "(unset)"
        group = groups.setdefault(component, {"total": 0, "pass": 0, "fail": 0,
                              "blocked": 0, "other": 0, "rows": []})
        group["rows"].append(row)
        group["total"] += 1
        if row["status_reason"] == "complete.optimized":
            continue
        elif row["bucket"] in group:
            group[row["bucket"]] += 1
        elif row["bucket"] in ("other_complete", "rejected"):
            group["other"] += 1

    rows = []
    sorted_groups = sorted(groups.items(), key=lambda item: item[0].lower())
    for component, counts in sorted_groups:
        other_cell = f"<td>{counts['other']}</td>" if include_other else ""
        test_cases = []
        for row in counts["rows"]:
            tc_id = esc(row.get("tc_id"))
            tc_url = f"https://hsdes.intel.com/appstore/article/#/article/{tc_id}"
            title = esc(row.get("title"))
            status_reason = row.get("status_reason")
            status = esc(
                "complete" if status_reason == "complete.optimized"
                else status_reason or row.get("bucket")
            )
            test_cases.append(
                f'<li><a href="{tc_url}" target="_blank" rel="noopener">{tc_id}</a>'
                f" {title} <small>{status}</small></li>"
            )
        component_html = (
            '<details class="component-details">'
            f'<summary>{esc(component)} <span>({len(counts["rows"])} TCs)</span></summary>'
            f'<ul class="tc-list">{"".join(test_cases)}</ul></details>'
        )
        rows.append(
            "<tr>"
            f"<td>{component_html}</td>"
            f"<td>{counts['pass']}/{counts['total']}</td>"
            f"<td>{pct(counts['pass'], counts['total'])}</td>"
            f"<td>{counts['fail']}</td>"
            f"{other_cell}"
            "</tr>"
        )
    return "\n".join(rows)


def failure_rows(summary):
    failed = [row for row in summary["rows"] if row["bucket"] in ("fail", "blocked")]
    if not failed:
        return '<p class="success">No failed or blocked test cases.</p>'

    rows = []
    for row in failed:
        rows.append(
            "<tr>"
            f"<td>{esc(row.get('tc_id'))}</td>"
            f"<td>{esc(row.get('title'))}</td>"
            f"<td>{esc(row.get('component'))}</td>"
            f"<td>{esc(row.get('status_reason') or row.get('bucket'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>ID</th><th>Name</th><th>Component</th><th>Status</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def build_html(summary, source_url):
    total = summary["total"]
    passed = summary["pass"]
    failed = summary["fail"]
    blocked = summary["blocked"]
    not_run = summary["not_run"]
    optimized = sum(row.get("status_reason") == "complete.optimized"
                    for row in summary["rows"])
    other = max(0, summary["other_complete"] - optimized) + summary["rejected"]
    cycle = summary["cycle"]
    milestone = summary.get("milestone") or {}
    report_match = re.search(r"(\d{4}\.D\d+)(?:_(\d{2}WW\d+\.\d+))?", cycle)
    version = report_match.group(1) if report_match else ""
    week = report_match.group(2) if report_match else ""
    report_title = "Daily_CBV"
    report_suffix = ""
    if version:
        report_suffix += version
    if week:
        report_suffix += f"_{week}"
    full_report_title = report_title + report_suffix
    source_url = source_url if source_url.startswith(("https://", "http://")) else ""
    open_link = (
        f'<a class="action" href="{esc(source_url)}" target="_blank" rel="noopener">'
        "Open Full Report</a>" if source_url else ""
    )
    cycle_value = (
        f'<a href="{esc(source_url)}" target="_blank" rel="noopener">View cycle</a>'
        if source_url else esc(cycle)
    )
    owner = milestone.get("owner") or "Not available"

    cards = [
        ("Passed", passed, "good"),
        ("Failed", failed, "bad"),
        ("Blocked", blocked, "warn"),
        ("Not run", not_run, "neutral"),
    ]
    if other:
        cards.insert(5, ("Other complete", other, "neutral"))
    other_header = "<th>Other Complete</th>" if other else ""
    card_html = "".join(
        f'<div class="metric {kind}"><strong>{value}</strong><span>{esc(label)}</span></div>'
        for label, value, kind in cards
    )
    planned_html = (
        f'<section class="planned" aria-label="Planned Test Cases">'
        f'<strong>{total}</strong><span>Planned Test Cases</span></section>'
    )

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(full_report_title)}</title>
<style>
:root{{--ink:#192332;--muted:#5e6c7e;--line:#d3dce6;--blue:#075c91;--pale:#f4f7fa;
--green:#168044;--green-bg:#e8f5ed;--red:#c5221f;--red-bg:#fff0ef;--amber:#8c5c00;--amber-bg:#fff4d8}}
*{{box-sizing:border-box}}
body{{margin:0;background:#edf1f5;color:var(--ink);font:14px/1.45 "Segoe UI",Arial,sans-serif}}
.page{{max-width:960px;margin:10px auto;background:white;border:1px solid var(--line)}}
.banner{{background:var(--blue);color:white;padding:22px 28px 20px}}
.banner h1{{font-size:27px;line-height:1.25;margin:0 0 7px;overflow-wrap:anywhere}}
.banner p{{font-size:12px;margin:0;color:#e3f0fa}}
main{{padding:22px 28px 24px}}
.section-head{{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:0 0 18px}}
h2{{font-size:16px;margin:0;font-weight:650}}
.action{{display:inline-block;background:#0873b9;color:white;text-decoration:none;font-weight:650;
padding:9px 14px;border:1px solid #075c91;white-space:nowrap}}
.planned{{display:flex;align-items:baseline;gap:9px;margin:0 4px 10px}}
.planned strong{{font-size:23px;line-height:1.15}}
.planned span{{font-size:23px;font-weight:700;color:var(--green)}}
.metrics{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;margin:0 4px 28px}}
.metric{{min-height:76px;background:var(--pale);display:flex;flex-direction:column;align-items:center;
justify-content:center;padding:9px 6px;text-align:center}}
.metric strong{{font-size:23px;line-height:1.15}}
.metric span{{font-size:11px;color:var(--muted);margin-top:3px}}
.metric.good{{background:var(--green-bg);color:var(--green)}}
.metric.good span{{color:var(--green)}}
.metric.bad{{background:var(--red-bg);color:var(--red)}}
.metric.bad span{{color:var(--red)}}
.metric.warn{{background:var(--amber-bg);color:var(--amber)}}
.meta{{display:grid;grid-template-columns:1fr 1fr;gap:15px 28px;margin:0 4px 10px}}
.meta div{{display:grid;grid-template-columns:140px minmax(0,1fr);gap:10px;align-items:start}}
.meta dt{{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase}}
.meta dd{{margin:0;overflow-wrap:anywhere}}
.detail{{background:#f7f9fb;border-top:1px solid var(--line);padding:20px 28px 24px}}
.detail h2{{margin:0 0 12px}}
.component-details summary{{cursor:pointer;font-weight:650}}
.component-details summary span{{font-size:11px;font-weight:400;color:var(--muted);white-space:nowrap}}
.tc-list{{margin:8px 0 2px;padding-left:18px;min-width:240px}}
.tc-list li{{padding:3px 0;overflow-wrap:anywhere}}
.tc-list a{{white-space:nowrap}}
.tc-list small{{color:var(--muted)}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#e2edf7;color:#26384a;font-weight:700}}
th,td{{padding:7px 9px;text-align:left;border-bottom:1px solid #e1e7ed}}
tbody tr:nth-child(even){{background:#f1f5f9}}
.table-wrap{{overflow-x:auto;margin-bottom:22px}}
.success{{margin:0;color:var(--green);background:var(--green-bg);font-weight:650;padding:7px 9px}}
footer{{border-top:1px solid var(--line);padding:14px 28px;color:var(--muted);font-size:11px;overflow-wrap:anywhere}}
@media(max-width:650px){{
 .page{{margin:0;border:0}}.banner,main,.detail,footer{{padding-left:16px;padding-right:16px}}
 .section-head{{align-items:flex-start;flex-direction:column}}.metrics{{grid-template-columns:repeat(2,minmax(0,1fr));margin-left:0;margin-right:0}}
 .meta{{grid-template-columns:1fr;gap:12px}}.meta div{{grid-template-columns:110px minmax(0,1fr)}}
}}
</style>
</head>
<body><div class="page">
<header class="banner"><h1>{esc(report_title)}</h1><p class="version">{esc(report_suffix)}</p></header>
<main><div class="section-head"><h2>Overview</h2>{open_link}</div>
{planned_html}
<section class="metrics" aria-label="Cycle results">{card_html}</section>
<dl class="meta">
<div><dt>Owner</dt><dd>{esc(owner)}</dd></div>
<div><dt>Cycle</dt><dd>{cycle_value}</dd></div>
<div><dt>Result records</dt><dd>{summary['result_records']}</dd></div>
</dl></main>
<section class="detail"><h2>Test Case Summary by Component</h2>
<div class="table-wrap"><table><thead><tr><th>Component</th><th>Pass / Total</th>
<th>Pass Rate</th><th>Failed</th>{other_header}</tr></thead>
<tbody>{result_rows(summary, bool(other))}</tbody></table></div>
<h2>Failed Test Cases ({failed + blocked})</h2>{failure_rows(summary)}</section>
</div></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cycle", help="Phoenix execution URL or raw cycle name")
    parser.add_argument("-o", "--output")
    parser.add_argument("--cache", action="store_true", help="reuse locally cached cycle data")
    args = parser.parse_args()

    cycle = extract_cycle(args.cycle)
    summary = load_summary(cycle, args.cache)
    if args.output:
        output_name = args.output
    else:
        version_match = re.search(r"\d{4}\.D\d+(?:_\d{2}WW\d+\.\d+)?", cycle)
        suffix = version_match.group(0) if version_match else re.sub(
            r"[^A-Za-z0-9._-]+", "_", cycle
        ).strip("_")[-80:]
        output_name = f"Daily_CBV_{suffix}.html"
    output = HERE / output_name
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_html(summary, args.cycle), encoding="utf-8")
    print(f"[SUCCESS] {output} ({summary['total']} cases, {summary['pass']} passed, "
          f"{summary['fail']} failed)")


if __name__ == "__main__":
    main()