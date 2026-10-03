# TraceExport

Convert a trace file recorded with [StartTraceRecording](./StartRunTrace.md) to a readable JSON or CSV file. This command does not need an active debug session, so it can be used from a script in `headless.exe`.

## arguments

`arg1` The trace file to read (`.trace64` with x64dbg, `.trace32` with x32dbg).

`arg2` The output file. It is overwritten if it already exists.

`[arg3]` The output format: `json` or `csv`. When this argument is omitted, `csv` is used if the output file name ends with `.csv`, otherwise `json`.

## result

`$result` will be set to the number of exported instructions.

## remarks

Every exported instruction contains its index, thread id, address, opcode bytes, disassembly, the general purpose registers *before* the instruction was executed and the memory it accessed (address, old value and new value, one pointer-sized value per access). The module name is included when the trace belongs to the process that is currently being debugged. All numbers except the index and thread id are hexadecimal strings, because 64-bit values do not fit in a JSON number.

In the CSV format, memory accesses are stored in the `memory` column as `address:old` for an unchanged value, or `address:old->new` for a modified value, separated by `;`.

A trace that is still being recorded can be exported, the last incomplete instruction is skipped.

## example

```
StartTraceRecording "C:\traces\target.trace64"
TraceIntoConditional 0, .1000
StopTraceRecording
TraceExport "C:\traces\target.trace64", "C:\traces\target.json"
TraceExport "C:\traces\target.trace64", "C:\traces\target.csv"
```
