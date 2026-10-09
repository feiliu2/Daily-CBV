# Daily CBV Report

Generate a compact HTML report from a Phoenix test cycle URL.

## Run

From the repository folder, run:

```powershell
python generate_daily_cbv.py "<Phoenix test cycle URL>"
```

Example:

```powershell
python generate_daily_cbv.py "https://hsdes.intel.com/appstore/phoenix/execution?wf=22011658142&wfs=22011658160&gn=0&v=central_firmware&family=firmware&scope=product&cycle=bios.oakstream_diamondrapids.FW-SW%20PC.Server-BIOS.AP_FWEval_EXT-BAT_0039.D86_26WW41.2_V1_IMH1_Daily_CBV_BA"
```

The generated report is saved in this folder. Its filename is based on the BIOS version and WW in the cycle name, for example `Daily_CBV_0039.D86_26WW41.2.html`.

## Requirements

- Python 3.8 or later
- `curl.exe` (included with Windows 10/11)
- Intel network or VPN access
- A Windows domain login with HSDES access (integrated authentication; no token or cookie required)

If HSDES cannot be reached, connect to the Intel network or VPN and retry.

## Optional arguments

- `-o output.html`: choose an output filename.
- `--cache`: reuse previously fetched cycle data instead of querying HSDES.
