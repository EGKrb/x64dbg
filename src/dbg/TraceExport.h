#ifndef TRACEEXPORT_H
#define TRACEEXPORT_H

#include "_global.h"

enum class TraceExportFormat
{
    Json,
    Csv,
};

struct TraceExportResult
{
    duint count = 0; // number of exported instructions
    bool truncated = false; // the last block was incomplete (trace still being recorded?)
    String error; // set when the export failed
};

// Convert a trace file (.trace32/.trace64) to a human-readable format.
bool TraceExportFile(const char* traceFileName, const char* outputFileName, TraceExportFormat format, TraceExportResult & result);

#endif // TRACEEXPORT_H
