#include "server.h"
#include "_plugins.h"

#include <cstdlib>

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
