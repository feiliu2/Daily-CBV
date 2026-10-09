"""Ad-hoc HSDES query runner (Windows integrated auth via curl --negotiate).

Discovered API:
  POST https://hsdes-api.intel.com/rest/query/execution?start_at=N&max_results=M
  Body: {"queryXml": "<Query xmlns=...>...</Query>"}

Usage as a library: build_xml(...) / run(...)
"""
import json
import subprocess
import tempfile
import os

API = "https://hsdes-api.intel.com/rest/query/execution"
NS = "https://hsdes.intel.com/schemas/2012/Query"


def build_xml(subject, criteria, fields):
    """criteria: list of (field, operator, value, fieldtype); fields: list of (shortname, fullname)"""
    crit = "".join(
        f'<Criteria Name="R{i+1}">'
        f'<Subject Value="{subject}"/>'
        f'<CriteriaField Value="{f}"/>'
        f'<FieldOperator Value="{op}"/>'
        f'<FieldValue Value="{val}"/>'
        f'<FieldType Value="{ft}"/>'
        f"</Criteria>"
        for i, (f, op, val, ft) in enumerate(criteria)
    )
    disp = "".join(
        f'<DisplayField Visible="true" Shortname="{s}" Fullname="{fn}"/>' for s, fn in fields
    )
    return (
        f'<Query xmlns="{NS}"><Filter><Parent><Hierarchy/>'
        f'<WhereClause Operand="MATCH ALL">{crit}</WhereClause>'
        f"</Parent><Flags/></Filter>"
        f'<Display Displayas="shortname">{disp}</Display></Query>'
    )


def _powershell_fetch(query_xml, start_at, max_results):
    """Fallback for environments where curl.exe --negotiate is not accepted.
    Uses Windows integrated auth via PowerShell Invoke-WebRequest with
    -UseDefaultCredentials, which is closer to the browser/SSPI trust model.
    """
    fd, body_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    out_path = body_path + ".out"
    try:
        with open(body_path, "w", encoding="utf-8") as f:
            json.dump({"queryXml": query_xml}, f)

        ps = f'''
$ProgressPreference = 'SilentlyContinue'
$env:HTTP_PROXY = ''
$env:HTTPS_PROXY = ''
$env:ALL_PROXY = ''
$env:NO_PROXY = '*.intel.com,intel.com,hsdes-api.intel.com'

try {{
    $body = Get-Content -Raw -Path "{body_path}"
    $uri = "{API}?start_at={start_at}&max_results={max_results}"
    $r = Invoke-WebRequest -Uri $uri -Method POST -ContentType "application/json" -UseDefaultCredentials -Body $body -UseBasicParsing
    $r.Content | Set-Content -Encoding UTF8 "{out_path}"
    Write-Output "OK"
}} catch {{
    $msg = $_.Exception.Message
    if ($_.Exception.InnerException) {{
        $msg += " :: " + $_.Exception.InnerException.Message
    }}
    @{{ "_raw" = $msg }} | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 "{out_path}"
    Write-Output "FAIL"
}}
'''
        p = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if p.returncode == 0 and os.path.exists(out_path):
            with open(out_path, "r", encoding="utf-8-sig") as f:
                payload = f.read()
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                if payload.strip().startswith('{') and '"_raw"' in payload:
                    try:
                        return json.loads(payload)
                    except json.JSONDecodeError:
                        pass
                return {"_raw": payload[:800]}
        return {"_raw": (p.stderr or p.stdout or "PowerShell HSDES fallback failed")[:800]}
    finally:
        for tmp in (body_path, out_path):
            if os.path.exists(tmp):
                os.unlink(tmp)


def run(query_xml, start_at=1, max_results=100):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"queryXml": query_xml}, f)
    try:
        p = subprocess.run(
            [
                "curl.exe", "-sS", "--negotiate", "-u", ":",
                "-H", "Content-Type: application/json",
                "--data-binary", f"@{path}",
                f"{API}?start_at={start_at}&max_results={max_results}",
            ],
            capture_output=True, text=True, timeout=120,
        )
        out = p.stdout
        if p.returncode != 0 or not out.strip() or '401 Unauthorized' in out:
            return _powershell_fetch(query_xml, start_at, max_results)
    finally:
        os.unlink(path)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"_raw": out[:800]} 


def fetch_all(query_xml, page=100, cap=5000):
    first = run(query_xml, 1, page)
    if "data" not in first:
        return first
    rows = first["data"]
    total = first.get("total", len(rows))
    while len(rows) < min(total, cap):
        nxt = run(query_xml, len(rows) + 1, page)
        batch = nxt.get("data", [])
        if not batch:
            break
        rows.extend(batch)
    first["data"] = rows
    first["total"] = total
    return first
