# trace_export

Records a short trace of the target and converts it with the `TraceExport` command.

The script checks the exported instruction counts (JSON, CSV by extension and CSV by explicit
format argument). `check.py` then parses `trace.json` and `trace.csv` and verifies that both
files describe the same instructions.
