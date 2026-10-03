// Request dispatcher: translates JSON requests into x64dbg bridge calls.
//
// Request:  {"id": 1, "method": "mem_read", "params": {"addr": "rsp", "size": 16}}
// Response: {"id": 1, "result": ...} or {"id": 1, "error": "message"}
//
// Address/value parameters accept an integer or a string evaluated as an x64dbg expression
// (numbers in expressions are hexadecimal by default, "kernel32.CreateFileW" and "rsp+8" work).
// Addresses and register values in results are hexadecimal strings ("0x7FF6...") so that
// 64-bit values survive JSON number limits.

#include "server.h"
#include "_plugins.h"
#include "jansson/jansson.h"

#include <chrono>
#include <functional>
#include <unordered_map>
#include <vector>

namespace
{
    constexpr int PluginApiVersion = 1;
    constexpr long long MaxMemoryRead = 64 * 1024 * 1024;
    constexpr long long MaxDisasmCount = 10000;

#ifdef _WIN64
    const char* const GprNames[] =
    {
        "rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp",
        "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15",
        "rip", "rflags",
    };
#else
    const char* const GprNames[] =
    {
        "eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp",
        "eip", "eflags",
    };
#endif //_WIN64

    struct ApiError
    {
        std::string message;
    };

    [[noreturn]] void Fail(const std::string & message)
    {
        throw ApiError{ message };
    }

    // RAII owner for json_t references
    struct JsonRef
    {
        json_t* ptr;
        explicit JsonRef(json_t* p) : ptr(p) { }
        ~JsonRef()
        {
            if(ptr)
                json_decref(ptr);
        }
        JsonRef(const JsonRef &) = delete;
        JsonRef & operator=(const JsonRef &) = delete;
    };

    json_t* Hex(duint value)
    {
        char text[32];
        sprintf_s(text, "0x%llX", (unsigned long long)value);
        return json_string(text);
    }

    json_t* GetParam(json_t* params, const char* name, bool required)
    {
        json_t* value = params ? json_object_get(params, name) : nullptr;
        if(json_is_null(value))
            value = nullptr;
        if(!value && required)
            Fail(std::string("missing parameter '") + name + "'");
        return value;
    }

    duint ValueParam(json_t* params, const char* name)
    {
        json_t* value = GetParam(params, name, true);
        if(json_is_integer(value))
            return (duint)json_integer_value(value);
        if(json_is_string(value))
        {
            bool success = false;
            duint result = DbgEval(json_string_value(value), &success);
            if(!success)
                Fail(std::string("cannot evaluate expression '") + json_string_value(value) + "'");
            return result;
        }
        Fail(std::string("parameter '") + name + "' must be an integer or an expression string");
    }

    std::string StringParam(json_t* params, const char* name)
    {
        json_t* value = GetParam(params, name, true);
        if(!json_is_string(value))
            Fail(std::string("parameter '") + name + "' must be a string");
        return json_string_value(value);
    }

    long long IntParam(json_t* params, const char* name, long long defaultValue)
    {
        json_t* value = GetParam(params, name, false);
        if(!value)
            return defaultValue;
        if(!json_is_integer(value))
            Fail(std::string("parameter '") + name + "' must be an integer");
        return json_integer_value(value);
    }

    bool BoolParam(json_t* params, const char* name, bool defaultValue)
    {
        json_t* value = GetParam(params, name, false);
        if(!value)
            return defaultValue;
        if(!json_is_boolean(value))
            Fail(std::string("parameter '") + name + "' must be a boolean");
        return json_is_true(value);
    }

    json_t* State()
    {
        json_t* state = json_object();
        bool debugging = DbgIsDebugging();
        bool running = debugging && DbgIsRunning();
        json_object_set_new(state, "debugging", json_boolean(debugging));
        json_object_set_new(state, "running", json_boolean(running));
        if(debugging && !running)
            json_object_set_new(state, "cip", Hex(DbgValFromString("cip")));
        return state;
    }

    // Waits until the debuggee is paused. timeoutMs < 0 waits forever.
    bool WaitPaused(long long timeoutMs, const std::atomic<bool> & serverRunning)
    {
        auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeoutMs < 0 ? 0 : timeoutMs);
        while(serverRunning)
        {
            if(DbgIsDebugging() && !DbgIsRunning())
                return true;
            if(timeoutMs >= 0 && std::chrono::steady_clock::now() >= deadline)
                return false;
            Sleep(5);
        }
        return false;
    }

    json_t* ExecAndWait(const char* command, json_t* params, bool waitByDefault, const std::atomic<bool> & serverRunning)
    {
        if(!DbgCmdExecDirect(command))
            Fail(std::string("command '") + command + "' failed");
        bool paused = false;
        if(BoolParam(params, "wait", waitByDefault))
            paused = WaitPaused(IntParam(params, "timeout_ms", 10000), serverRunning);
        json_t* state = State();
        json_object_set_new(state, "paused", json_boolean(paused));
        return state;
    }

    std::vector<unsigned char> FromHex(const std::string & text)
    {
        auto nibble = [](char ch) -> int
        {
            if(ch >= '0' && ch <= '9')
                return ch - '0';
            if(ch >= 'a' && ch <= 'f')
                return ch - 'a' + 10;
            if(ch >= 'A' && ch <= 'F')
                return ch - 'A' + 10;
            return -1;
        };
        std::vector<unsigned char> data;
        int high = -1;
        for(char ch : text)
        {
            if(ch == ' ')
                continue;
            int value = nibble(ch);
            if(value < 0)
                Fail("invalid hex data");
            if(high < 0)
                high = value;
            else
            {
                data.push_back((unsigned char)(high << 4 | value));
                high = -1;
            }
        }
        if(high >= 0)
            Fail("hex data has an odd number of digits");
        return data;
    }

    std::string ToHex(const unsigned char* data, size_t size)
    {
        static const char digits[] = "0123456789ABCDEF";
        std::string text(size * 2, '\0');
        for(size_t i = 0; i < size; i++)
        {
            text[i * 2] = digits[data[i] >> 4];
            text[i * 2 + 1] = digits[data[i] & 0xF];
        }
        return text;
    }

    using Method = std::function<json_t*(json_t* params, const std::atomic<bool> & serverRunning)>;

    const std::unordered_map<std::string, Method> & Methods()
    {
        static const std::unordered_map<std::string, Method> methods =
        {
            {
                "ping", [](json_t*, const std::atomic<bool> &)
                {
                    json_t* result = json_object();
                    json_object_set_new(result, "name", json_string("pybridge"));
                    json_object_set_new(result, "version", json_integer(PluginApiVersion));
#ifdef _WIN64
                    json_object_set_new(result, "arch", json_string("x64"));
#else
                    json_object_set_new(result, "arch", json_string("x32"));
#endif //_WIN64
                    return result;
                }
            },
            {
                "cmd", [](json_t* params, const std::atomic<bool> &)
                {
                    return json_boolean(DbgCmdExecDirect(StringParam(params, "command").c_str()));
                }
            },
            {
                "eval", [](json_t* params, const std::atomic<bool> &)
                {
                    auto expression = StringParam(params, "expr");
                    bool success = false;
                    duint value = DbgEval(expression.c_str(), &success);
                    if(!success)
                        Fail("cannot evaluate expression '" + expression + "'");
                    return Hex(value);
                }
            },
            {
                "state", [](json_t*, const std::atomic<bool> &)
                {
                    return State();
                }
            },
            {
                "wait", [](json_t* params, const std::atomic<bool> & serverRunning)
                {
                    bool paused = WaitPaused(IntParam(params, "timeout_ms", 10000), serverRunning);
                    json_t* state = State();
                    json_object_set_new(state, "paused", json_boolean(paused));
                    return state;
                }
            },
            {
                "run", [](json_t* params, const std::atomic<bool> & serverRunning)
                {
                    // erun passes first chance exceptions to the debuggee
                    return ExecAndWait(BoolParam(params, "pass_exceptions", false) ? "erun" : "run", params, false, serverRunning);
                }
            },
            {
                "pause", [](json_t* params, const std::atomic<bool> & serverRunning)
                {
                    return ExecAndWait("pause", params, true, serverRunning);
                }
            },
            {
                "step_into", [](json_t* params, const std::atomic<bool> & serverRunning)
                {
                    return ExecAndWait("StepInto", params, true, serverRunning);
                }
            },
            {
                "step_over", [](json_t* params, const std::atomic<bool> & serverRunning)
                {
                    return ExecAndWait("StepOver", params, true, serverRunning);
                }
            },
            {
                "step_out", [](json_t* params, const std::atomic<bool> & serverRunning)
                {
                    return ExecAndWait("StepOut", params, true, serverRunning);
                }
            },
            {
                "regs", [](json_t*, const std::atomic<bool> &)
                {
                    if(!DbgIsDebugging())
                        Fail("not debugging");
                    json_t* result = json_object();
                    for(auto name : GprNames)
                        json_object_set_new(result, name, Hex(DbgValFromString(name)));
                    return result;
                }
            },
            {
                "reg_get", [](json_t* params, const std::atomic<bool> &)
                {
                    auto name = StringParam(params, "name");
                    bool success = false;
                    duint value = DbgEval(name.c_str(), &success);
                    if(!success)
                        Fail("unknown register '" + name + "'");
                    return Hex(value);
                }
            },
            {
                "reg_set", [](json_t* params, const std::atomic<bool> &)
                {
                    auto name = StringParam(params, "name");
                    duint value = ValueParam(params, "value");
                    if(!DbgValSetScalar(name.c_str(), value))
                        Fail("cannot set '" + name + "'");
                    return json_true();
                }
            },
            {
                "mem_read", [](json_t* params, const std::atomic<bool> &)
                {
                    duint addr = ValueParam(params, "addr");
                    long long size = IntParam(params, "size", -1);
                    if(size < 0 || size > MaxMemoryRead)
                        Fail("parameter 'size' must be between 0 and " + std::to_string(MaxMemoryRead));
                    std::vector<unsigned char> data((size_t)size);
                    if(size && !DbgMemRead(addr, data.data(), (duint)size))
                        Fail("cannot read memory");
                    return json_string(ToHex(data.data(), data.size()).c_str());
                }
            },
            {
                "mem_write", [](json_t* params, const std::atomic<bool> &)
                {
                    duint addr = ValueParam(params, "addr");
                    auto data = FromHex(StringParam(params, "data"));
                    if(!data.empty() && !DbgMemWrite(addr, data.data(), data.size()))
                        Fail("cannot write memory");
                    return json_true();
                }
            },
            {
                "mem_valid", [](json_t* params, const std::atomic<bool> &)
                {
                    return json_boolean(DbgMemIsValidReadPtr(ValueParam(params, "addr")));
                }
            },
            {
                "disasm", [](json_t* params, const std::atomic<bool> &)
                {
                    duint addr = ValueParam(params, "addr");
                    long long count = IntParam(params, "count", 1);
                    if(count < 1 || count > MaxDisasmCount)
                        Fail("parameter 'count' must be between 1 and " + std::to_string(MaxDisasmCount));
                    json_t* result = json_array();
                    for(long long i = 0; i < count; i++)
                    {
                        BASIC_INSTRUCTION_INFO info = {};
                        DbgDisasmFastAt(addr, &info);
                        int size = info.size > 0 ? info.size : 1;
                        unsigned char bytes[16] = {};
                        bool readable = DbgMemRead(addr, bytes, std::min(size, 16));
                        json_t* entry = json_object();
                        json_object_set_new(entry, "address", Hex(addr));
                        json_object_set_new(entry, "size", json_integer(size));
                        json_object_set_new(entry, "text", json_string(readable ? info.instruction : "???"));
                        json_object_set_new(entry, "bytes", json_string(readable ? ToHex(bytes, std::min(size, 16)).c_str() : ""));
                        json_array_append_new(result, entry);
                        addr += size;
                    }
                    return result;
                }
            },
        };
        return methods;
    }

    std::string Dump(json_t* json)
    {
        // json_dump_callback avoids freeing memory allocated by jansson.dll
        std::string result;
        auto append = [](const char* buffer, size_t size, void* data)
        {
            ((std::string*)data)->append(buffer, size);
            return 0;
        };
        if(json_dump_callback(json, append, &result, JSON_COMPACT) != 0)
            result = "{\"error\":\"cannot serialize response\"}";
        return result;
    }
}

std::string BridgeHandleRequest(const std::string & line, const std::atomic<bool> & serverRunning)
{
    JsonRef response(json_object());
    json_error_t parseError;
    JsonRef request(json_loadb(line.data(), line.size(), 0, &parseError));
    if(!json_is_object(request.ptr))
    {
        json_object_set_new(response.ptr, "error", json_string("request is not a JSON object"));
        return Dump(response.ptr);
    }

    json_t* id = json_object_get(request.ptr, "id");
    if(id)
        json_object_set(response.ptr, "id", id);
    const char* method = json_string_value(json_object_get(request.ptr, "method"));
    json_t* params = json_object_get(request.ptr, "params");

    try
    {
        if(!method)
            Fail("missing 'method'");
        auto found = Methods().find(method);
        if(found == Methods().end())
            Fail(std::string("unknown method '") + method + "'");
        json_object_set_new(response.ptr, "result", found->second(params, serverRunning));
    }
    catch(const ApiError & error)
    {
        json_object_set_new(response.ptr, "error", json_string(error.message.c_str()));
    }
    return Dump(response.ptr);
}
