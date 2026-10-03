#include "TraceExport.h"
#include "_dbgfunctions.h"
#include "debugger.h"
#include "handle.h"
#include "module.h"
#include "stringutils.h"
#include "zydis_wrapper.h"
#include "jansson/jansson_x64dbg.h"

// File format reference: docs/developers/tracefile.md

namespace
{
    // Number of pointer-sized words of REGDUMP that are stored in a trace file
    constexpr size_t TraceExportRegWordCount = (FIELD_OFFSET(REGDUMP, lastError) + sizeof(DWORD)) / sizeof(duint);
    // Matches the size of the memory operand buffers in TraceRecordManager
    constexpr size_t TraceExportMaxMemoryOperands = 32;

#ifdef _WIN64
    const char* const TraceExportRegNames[] =
    {
        "rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi",
        "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15",
        "rip", "rflags",
    };
#else
    const char* const TraceExportRegNames[] =
    {
        "eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi",
        "eip", "eflags",
    };
#endif //_WIN64

    // The exported registers are the first words of REGISTERCONTEXT, ending with eflags
    static_assert(FIELD_OFFSET(REGISTERCONTEXT, eflags) == (_countof(TraceExportRegNames) - 1) * sizeof(duint), "Unexpected REGISTERCONTEXT layout");

    class TraceExportReader
    {
    public:
        explicit TraceExportReader(HANDLE hFile) : mFile(hFile), mBuffer(1024 * 1024) { }

        // Returns the number of bytes read, which is less than size at the end of the file
        size_t read(void* dest, size_t size)
        {
            auto out = (unsigned char*)dest;
            size_t total = 0;
            while(total < size)
            {
                if(mPos == mSize)
                {
                    DWORD bytesRead = 0;
                    if(!ReadFile(mFile, mBuffer.data(), (DWORD)mBuffer.size(), &bytesRead, nullptr) || bytesRead == 0)
                        break;
                    mPos = 0;
                    mSize = bytesRead;
                }
                auto chunk = std::min(size - total, mSize - mPos);
                memcpy(out + total, mBuffer.data() + mPos, chunk);
                mPos += chunk;
                total += chunk;
            }
            return total;
        }

        bool readExact(void* dest, size_t size)
        {
            return read(dest, size) == size;
        }

        bool skip(size_t size)
        {
            unsigned char temp[4096];
            while(size > 0)
            {
                auto chunk = std::min(size, sizeof(temp));
                if(!readExact(temp, chunk))
                    return false;
                size -= chunk;
            }
            return true;
        }

    private:
        HANDLE mFile;
        std::vector<unsigned char> mBuffer;
        size_t mPos = 0;
        size_t mSize = 0;
    };

    struct TraceExportEntry
    {
        DWORD threadId = 0;
        unsigned char opcode[16] = {};
        unsigned char opcodeSize = 0;
        union
        {
            REGDUMP registers;
            duint regwords[TraceExportRegWordCount];
        };
        unsigned char memoryCount = 0;
        unsigned char memoryFlags[TraceExportMaxMemoryOperands] = {};
        duint memoryAddress[TraceExportMaxMemoryOperands] = {};
        duint memoryOld[TraceExportMaxMemoryOperands] = {};
        duint memoryNew[TraceExportMaxMemoryOperands] = {};

        TraceExportEntry()
        {
            memset(&registers, 0, sizeof(registers));
        }
    };

    enum class TraceExportBlockResult
    {
        Instruction,
        UserBlock,
        EndOfFile,
        Truncated,
    };

    // Reads the next block. The entry keeps the register state of the previous instruction, because
    // registers are delta-encoded. Throws a String on malformed data.
    TraceExportBlockResult TraceExportReadBlock(TraceExportReader & reader, TraceExportEntry & entry)
    {
        unsigned char blockType;
        if(!reader.readExact(&blockType, 1))
            return TraceExportBlockResult::EndOfFile;

        if(blockType >= 0x80)
        {
            uint32_t blockSize;
            if(!reader.readExact(&blockSize, sizeof(blockSize)) || !reader.skip(blockSize))
                return TraceExportBlockResult::Truncated;
            return TraceExportBlockResult::UserBlock;
        }
        if(blockType != 0)
            throw StringUtils::sprintf("Unsupported block type %u", blockType);

        unsigned char changedCountFlags[3]; //reg changed count, mem accessed count, flags
        if(!reader.readExact(changedCountFlags, sizeof(changedCountFlags)))
            return TraceExportBlockResult::Truncated;
        if((changedCountFlags[2] & 0x80) && !reader.readExact(&entry.threadId, sizeof(entry.threadId)))
            return TraceExportBlockResult::Truncated;

        entry.opcodeSize = changedCountFlags[2] & 0x0F;
        if(entry.opcodeSize == 0)
            throw String("Instruction block without opcode");
        if(!reader.readExact(entry.opcode, entry.opcodeSize))
            return TraceExportBlockResult::Truncated;

        const unsigned char regCount = changedCountFlags[0];
        if(regCount > TraceExportRegWordCount)
            throw StringUtils::sprintf("Bad register count %u", regCount);
        unsigned char regPosition[TraceExportRegWordCount];
        duint regContent[TraceExportRegWordCount];
        if(!reader.readExact(regPosition, regCount) || !reader.readExact(regContent, regCount * sizeof(duint)))
            return TraceExportBlockResult::Truncated;
        int lastPosition = -1;
        for(unsigned char i = 0; i < regCount; i++)
        {
            lastPosition += regPosition[i] + 1;
            if(lastPosition >= (int)TraceExportRegWordCount)
                throw String("Register change out of bounds");
            entry.regwords[lastPosition] = regContent[i];
        }

        entry.memoryCount = changedCountFlags[1];
        if(entry.memoryCount > TraceExportMaxMemoryOperands)
            throw StringUtils::sprintf("Bad memory operand count %u", entry.memoryCount);
        const size_t memorySize = entry.memoryCount * sizeof(duint);
        if(!reader.readExact(entry.memoryFlags, entry.memoryCount)
                || !reader.readExact(entry.memoryAddress, memorySize)
                || !reader.readExact(entry.memoryOld, memorySize))
            return TraceExportBlockResult::Truncated;
        for(unsigned char i = 0; i < entry.memoryCount; i++)
        {
            // Bit 0 set: memory is unchanged, no new content is stored
            if(entry.memoryFlags[i] & 1)
                entry.memoryNew[i] = entry.memoryOld[i];
            else if(!reader.readExact(&entry.memoryNew[i], sizeof(duint)))
                return TraceExportBlockResult::Truncated;
        }
        return TraceExportBlockResult::Instruction;
    }

    String TraceExportHex(duint value)
    {
        return StringUtils::sprintf("0x%llX", (unsigned long long)value);
    }

    String TraceExportBytes(const TraceExportEntry & entry)
    {
        String result;
        for(unsigned char i = 0; i < entry.opcodeSize; i++)
        {
            if(i)
                result.push_back(' ');
            result += StringUtils::sprintf("%02X", entry.opcode[i]);
        }
        return result;
    }

    void TraceExportJsonString(String & out, const String & s)
    {
        out.push_back('"');
        for(unsigned char ch : s)
        {
            switch(ch)
            {
            case '"':
                out += "\\\"";
                break;
            case '\\':
                out += "\\\\";
                break;
            case '\n':
                out += "\\n";
                break;
            case '\r':
                out += "\\r";
                break;
            case '\t':
                out += "\\t";
                break;
            default:
                if(ch < 0x20)
                    out += StringUtils::sprintf("\\u%04X", ch);
                else
                    out.push_back(ch);
                break;
            }
        }
        out.push_back('"');
    }

    void TraceExportCsvString(String & out, const String & s)
    {
        out.push_back('"');
        for(char ch : s)
        {
            if(ch == '"')
                out.push_back('"');
            out.push_back(ch);
        }
        out.push_back('"');
    }

    struct TraceExportHeader
    {
        String path;
        String hash;
        duint hashValue = 0;
    };

    TraceExportHeader TraceExportReadHeader(TraceExportReader & reader)
    {
        uint8_t magic[4];
        uint32_t headerSize;
        if(!reader.readExact(magic, sizeof(magic)) || memcmp(magic, "TRAC", sizeof(magic)) != 0)
            throw String("Not a trace file (missing TRAC header)");
        if(!reader.readExact(&headerSize, sizeof(headerSize)) || headerSize > 100 * 1024)
            throw String("Invalid trace file header size");
        std::vector<char> headerData(headerSize);
        if(!reader.readExact(headerData.data(), headerData.size()))
            throw String("Trace file header is truncated");

        json_error_t error;
        auto root = json_loadb(headerData.data(), headerData.size(), 0, &error);
        if(!root)
            throw String("Trace file header is not valid JSON");
        TraceExportHeader header;
        String failure;
        auto ver = json_integer_value(json_object_get(root, "ver"));
        auto arch = json_string_value(json_object_get(root, "arch"));
        auto path = json_string_value(json_object_get(root, "path"));
        auto hash = json_object_get(root, "hash");
        if(ver != 1)
            failure = StringUtils::sprintf("Unsupported trace file version %lld", (long long)ver);
        else if(!arch || strcmp(arch, ArchValue("x86", "x64")) != 0)
            failure = StringUtils::sprintf("This trace was recorded on %s, export it with %s", arch ? arch : "an unknown architecture", ArchValue("x64dbg", "x32dbg"));
        if(path)
            header.path = path;
        if(json_is_string(hash))
        {
            header.hash = json_string_value(hash);
            header.hashValue = (duint)json_hex_value(hash);
        }
        json_decref(root);
        if(!failure.empty())
            throw failure;
        return header;
    }

    bool TraceExportSamePath(const char* a, const char* b)
    {
        wchar_t fullA[MAX_PATH] = L"", fullB[MAX_PATH] = L"";
        if(!GetFullPathNameW(StringUtils::Utf8ToUtf16(a).c_str(), _countof(fullA), fullA, nullptr)
                || !GetFullPathNameW(StringUtils::Utf8ToUtf16(b).c_str(), _countof(fullB), fullB, nullptr))
            return false;
        return _wcsicmp(fullA, fullB) == 0;
    }
}

bool TraceExportFile(const char* traceFileName, const char* outputFileName, TraceExportFormat format, TraceExportResult & result)
{
    result = TraceExportResult();
    if(TraceExportSamePath(traceFileName, outputFileName))
    {
        result.error = "The output file must be different from the trace file";
        return false;
    }

    // FILE_SHARE_WRITE allows exporting a trace that is still being recorded
    Handle hTrace = CreateFileW(StringUtils::Utf8ToUtf16(traceFileName).c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if(!hTrace)
    {
        result.error = StringUtils::sprintf("Cannot open trace file \"%s\" (error %u)", traceFileName, GetLastError());
        return false;
    }

    TraceExportReader reader(hTrace);
    TraceExportHeader header;
    try
    {
        header = TraceExportReadHeader(reader);
    }
    catch(const String & error)
    {
        result.error = error;
        return false;
    }

    FILE* output = _wfopen(StringUtils::Utf8ToUtf16(outputFileName).c_str(), L"wb");
    if(!output)
    {
        result.error = StringUtils::sprintf("Cannot create output file \"%s\"", outputFileName);
        return false;
    }
    setvbuf(output, nullptr, _IOFBF, 1024 * 1024);

    // Module names are only meaningful while debugging the process that recorded the trace
    const bool resolveModules = dbgisdebugging() && header.hashValue != 0 && header.hashValue == dbgfunctionsget()->DbGetHash();

    String line;
    if(format == TraceExportFormat::Json)
    {
        line = "{\n\"version\": 1,\n\"arch\": ";
        TraceExportJsonString(line, ArchValue("x86", "x64"));
        line += ",\n\"path\": ";
        TraceExportJsonString(line, header.path);
        line += ",\n\"hash\": ";
        TraceExportJsonString(line, header.hash);
        line += ",\n\"instructions\": [\n";
    }
    else
    {
        line = "index,thread,address,module,bytes,disasm";
        for(auto name : TraceExportRegNames)
        {
            line.push_back(',');
            line += name;
        }
        line += ",memory\r\n";
    }
    fwrite(line.data(), 1, line.size(), output);

    Zydis zydis;
    TraceExportEntry entry;
    try
    {
        while(true)
        {
            auto blockResult = TraceExportReadBlock(reader, entry);
            if(blockResult == TraceExportBlockResult::EndOfFile)
                break;
            if(blockResult == TraceExportBlockResult::Truncated)
            {
                // The last block can be incomplete when the trace is still being recorded
                result.truncated = true;
                break;
            }
            if(blockResult == TraceExportBlockResult::UserBlock)
                continue;

            const duint cip = entry.registers.regcontext.cip;
            const String disasm = zydis.Disassemble(cip, entry.opcode, entry.opcodeSize) ? zydis.InstructionText() : "???";
            char moduleName[MAX_MODULE_SIZE] = "";
            if(resolveModules)
                ModNameFromAddr(cip, moduleName, true);

            line.clear();
            if(format == TraceExportFormat::Json)
            {
                line += result.count ? ",\n{\"index\": " : "{\"index\": ";
                line += std::to_string(result.count);
                line += ", \"thread\": ";
                line += std::to_string(entry.threadId);
                line += ", \"address\": ";
                TraceExportJsonString(line, TraceExportHex(cip));
                if(*moduleName)
                {
                    line += ", \"module\": ";
                    TraceExportJsonString(line, moduleName);
                }
                line += ", \"bytes\": ";
                TraceExportJsonString(line, TraceExportBytes(entry));
                line += ", \"disasm\": ";
                TraceExportJsonString(line, disasm);
                line += ", \"regs\": {";
                for(size_t i = 0; i < _countof(TraceExportRegNames); i++)
                {
                    if(i)
                        line += ", ";
                    TraceExportJsonString(line, TraceExportRegNames[i]);
                    line += ": ";
                    TraceExportJsonString(line, TraceExportHex(entry.regwords[i]));
                }
                line += "}, \"mem\": [";
                for(unsigned char i = 0; i < entry.memoryCount; i++)
                {
                    if(i)
                        line += ", ";
                    line += "{\"address\": ";
                    TraceExportJsonString(line, TraceExportHex(entry.memoryAddress[i]));
                    line += ", \"old\": ";
                    TraceExportJsonString(line, TraceExportHex(entry.memoryOld[i]));
                    line += ", \"new\": ";
                    TraceExportJsonString(line, TraceExportHex(entry.memoryNew[i]));
                    line += "}";
                }
                line += "]}";
            }
            else
            {
                line += std::to_string(result.count);
                line.push_back(',');
                line += std::to_string(entry.threadId);
                line.push_back(',');
                line += TraceExportHex(cip);
                line.push_back(',');
                TraceExportCsvString(line, moduleName);
                line.push_back(',');
                TraceExportCsvString(line, TraceExportBytes(entry));
                line.push_back(',');
                TraceExportCsvString(line, disasm);
                for(size_t i = 0; i < _countof(TraceExportRegNames); i++)
                {
                    line.push_back(',');
                    line += TraceExportHex(entry.regwords[i]);
                }
                String memory;
                for(unsigned char i = 0; i < entry.memoryCount; i++)
                {
                    if(i)
                        memory.push_back(';');
                    memory += TraceExportHex(entry.memoryAddress[i]);
                    memory.push_back(':');
                    memory += TraceExportHex(entry.memoryOld[i]);
                    if(entry.memoryNew[i] != entry.memoryOld[i])
                    {
                        memory += "->";
                        memory += TraceExportHex(entry.memoryNew[i]);
                    }
                }
                line.push_back(',');
                TraceExportCsvString(line, memory);
                line += "\r\n";
            }
            fwrite(line.data(), 1, line.size(), output);
            result.count++;
        }
    }
    catch(const String & error)
    {
        result.error = StringUtils::sprintf("Malformed trace file after %llu instructions: %s", (unsigned long long)result.count, error.c_str());
    }

    if(format == TraceExportFormat::Json)
    {
        line = result.count ? "\n]\n}\n" : "]\n}\n";
        fwrite(line.data(), 1, line.size(), output);
    }
    const bool writeFailed = ferror(output) != 0;
    if(fclose(output) != 0 || writeFailed)
    {
        result.error = StringUtils::sprintf("Failed to write output file \"%s\"", outputFileName);
        return false;
    }
    return result.error.empty();
}
