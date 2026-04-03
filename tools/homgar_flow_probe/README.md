# HomGar / RainPoint Flow Probe

This tool polls the live API for an `HTV145FRF` timer and records raw status snapshots while you manually start and stop watering.

The current API methods we know about expose:

- device metadata from `getDeviceByHid`
- runtime status from `getDeviceStatus`
- on/off control from `controlWorkMode`

The missing piece is water-usage history or live flow data. This probe helps capture any hidden changes in the raw `D01` payload while water is running.

## What it records

- all non-null `subDeviceStatus` values
- the raw `D01` hex payload
- decoded known fields:
  - valve state
  - duration setting
  - countdown
  - device clock
- unknown hex chunks that may contain flow-meter information

## Requirements

- Python 3
- `requests`

## Usage

Run the probe, then start watering from the RainPoint app or the timer button:

```powershell
python .\tools\homgar_flow_probe\homgar_flow_probe.py --email you@example.com --app-code 2 --area-code 1 --interval 5 --count 120
```

To capture the full lifecycle automatically, start the probe before watering and let it stop on its own after the valve returns to idle:

```powershell
python .\tools\homgar_flow_probe\homgar_flow_probe.py --email you@example.com --app-code 2 --area-code 1 --interval 5 --until-stop
```

The output is written as JSONL to:

```powershell
.\tools\homgar_flow_probe\flow_probe_output.jsonl
```

You can label each run so repeated tests are easier to compare:

```powershell
python .\tools\homgar_flow_probe\homgar_flow_probe.py --email you@example.com --app-code 2 --area-code 1 --interval 5 --until-stop --label run_30s --output .\tools\homgar_flow_probe\run_30s.jsonl
```

## Recommended workflow

1. Start the probe with `--until-stop`.
2. Wait for a few idle snapshots.
3. Start manual watering in the app.
4. Let the watering run normally.
5. Wait for the probe to detect the stop event and capture a few extra polls.
6. Review the JSONL file for any changing unknown fields or additional non-null status ids.

Suggested test matrix:

1. Run a 30 second manual watering cycle and save to `run_30s.jsonl`
2. Run a 60 second manual watering cycle and save to `run_60s.jsonl`
3. Run a 120 second manual watering cycle and save to `run_120s.jsonl`
4. Compare them with:

```powershell
python .\tools\homgar_flow_probe\compare_flow_runs.py .\tools\homgar_flow_probe\run_30s.jsonl .\tools\homgar_flow_probe\run_60s.jsonl .\tools\homgar_flow_probe\run_120s.jsonl
```

## Notes

- The script auto-discovers a single `modelCode 302` device.
- If you have multiple matching timers, rerun with `--hid`, `--mid`, or `--did`.
- The script does not start watering on its own.
- In `--until-stop` mode, the script has a safety cap of 720 polls unless you override `--max-polls`.
- At the end of each run, the probe prints a compact JSON summary including the candidate post-run field transition.
