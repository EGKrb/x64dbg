#include "server.h"
#include "_plugins.h"

#include <windows.h>
#include <cstdlib>
#include <string>

#define PLUGIN_NAME "pybridge"
#define PLUGIN_VERSION 1
#define DEFAULT_PORT 27041

namespace
{
    int gPluginHandle;
    BridgeServer gServer;

    void StartServer(unsigned short port)
    {
        std::string error;
        if(gServer.Start(port, error))
            _plugin_logprintf("[" PLUGIN_NAME "] listening on 127.0.0.1:%u\n", gServer.Port());
        else
            _plugin_logprintf("[" PLUGIN_NAME "] cannot start: %s\n", error.c_str());
    }

    // The port is parsed as a decimal number (x64dbg expressions would treat it as hex)
    bool ParsePort(const char* text, unsigned short & port)
    {
        char* end = nullptr;
        unsigned long value = strtoul(text, &end, 10);
        if(!*text || *end || value > 65535)
            return false;
        port = (unsigned short)value;
        return true;
    }

    bool CbStart(int argc, char* argv[])
    {
        unsigned short port = DEFAULT_PORT;
        if(argc > 1 && !ParsePort(argv[1], port))
        {
            _plugin_logprintf("[" PLUGIN_NAME "] invalid port \"%s\" (decimal number expected)\n", argv[1]);
            return false;
        }
        StartServer(port);
        return gServer.IsRunning();
    }

    bool CbStop(int, char*[])
    {
        if(gServer.IsRunning())
        {
            gServer.Stop();
            _plugin_logputs("[" PLUGIN_NAME "] stopped");
        }
        return true;
    }

    // pybridge.emu "C:\path\crash.dmp"[, port[, thread[, keepgoing]]]
    // Launches emulate_dump.py --serve in a new console so the dump can be driven like a
    // live target through x64dbg_bridge.Debugger(port=...). The script path comes from the
    // X64DBG_EMU_SCRIPT environment variable, or defaults to emulate_dump.py on the PATH.
    bool CbEmu(int argc, char* argv[])
    {
        if(argc < 2)
        {
            _plugin_logputs("[" PLUGIN_NAME "] usage: pybridge.emu \"dump.dmp\"[, port[, thread[, keepgoing]]]");
            return false;
        }

        char scriptBuf[MAX_PATH] = "";
        size_t length = 0;
        getenv_s(&length, scriptBuf, "X64DBG_EMU_SCRIPT");
        std::string script = length > 0 ? scriptBuf : "emulate_dump.py";

        std::string port = argc > 2 ? argv[2] : "27041";
        std::string thread = argc > 3 ? argv[3] : "0";
        bool keepGoing = argc > 4 && (argv[4][0] == '1' || argv[4][0] == 'y' || argv[4][0] == 'Y');

        std::string cmd = "py -3 \"" + script + "\" --serve --port " + port +
                          " --thread " + thread + (keepGoing ? " --keep-going" : "") +
                          " \"" + argv[1] + "\"";

        STARTUPINFOA si = { sizeof(si) };
        PROCESS_INFORMATION pi = {};
        std::string mutableCmd = cmd;  // CreateProcessA may modify the command line buffer
        if(!CreateProcessA(nullptr, mutableCmd.data(), nullptr, nullptr, FALSE,
                           CREATE_NEW_CONSOLE, nullptr, nullptr, &si, &pi))
        {
            _plugin_logprintf("[" PLUGIN_NAME "] cannot start emulator (error %lu): %s\n",
                              GetLastError(), cmd.c_str());
            return false;
        }
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
        _plugin_logprintf("[" PLUGIN_NAME "] emulating %s on 127.0.0.1:%s "
                          "(connect with Debugger(port=%s))\n", argv[1], port.c_str(), port.c_str());
        return true;
    }

    bool CbStatus(int, char*[])
    {
        if(gServer.IsRunning())
            _plugin_logprintf("[" PLUGIN_NAME "] listening on 127.0.0.1:%u\n", gServer.Port());
        else
            _plugin_logputs("[" PLUGIN_NAME "] not running");
        return true;
    }
}

extern "C" __declspec(dllexport) bool pluginit(PLUG_INITSTRUCT* initStruct)
{
    initStruct->pluginVersion = PLUGIN_VERSION;
    initStruct->sdkVersion = PLUG_SDKVERSION;
    strncpy_s(initStruct->pluginName, PLUGIN_NAME, _TRUNCATE);
    gPluginHandle = initStruct->pluginHandle;

    _plugin_registercommand(gPluginHandle, "pybridge.start", CbStart, false);
    _plugin_registercommand(gPluginHandle, "pybridge.stop", CbStop, false);
    _plugin_registercommand(gPluginHandle, "pybridge.status", CbStatus, false);
    _plugin_registercommand(gPluginHandle, "pybridge.emu", CbEmu, false);

    // Start automatically when launched by the Python client (x64dbg_bridge.launch)
    char portText[16] = "";
    size_t length = 0;
    if(getenv_s(&length, portText, "X64DBG_PYBRIDGE_PORT") == 0 && length > 0)
    {
        unsigned short port;
        if(ParsePort(portText, port))
            StartServer(port);
        else
            _plugin_logprintf("[" PLUGIN_NAME "] invalid X64DBG_PYBRIDGE_PORT \"%s\"\n", portText);
    }
    return true;
}

extern "C" __declspec(dllexport) void plugstop()
{
    gServer.Stop();
}

extern "C" __declspec(dllexport) void plugsetup(PLUG_SETUPSTRUCT*)
{
}
