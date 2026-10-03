#include "server.h"
#include "_plugins.h"

#include <windows.h>
#include <shlwapi.h>
#include <cstdlib>
#include <string>
#include <vector>

#pragma comment(lib, "shlwapi.lib")

#define PLUGIN_NAME "pybridge"
#define PLUGIN_VERSION 1
#define DEFAULT_PORT 27041

namespace
{
    int gPluginHandle;
    BridgeServer gServer;

    // Directory of the loaded plugin DLL (<x64dbg>/x64/plugins/pybridge.dp64).
    // We walk up from here to find emulate_dump.py in both layouts:
    //   release:  <x64dbg>/pybridge/examples/emulate_dump.py        (../pybridge/examples)
    //   dev:      <x64dbg>/pybridge/examples/emulate_dump.py        (../../pybridge/examples)
    std::string PluginDir()
    {
        HMODULE self = nullptr;
        if(!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                               (LPCSTR)&PluginDir, &self))
            return {};
        char path[MAX_PATH] = "";
        if(!GetModuleFileNameA(self, path, MAX_PATH))
            return {};
        PathRemoveFileSpecA(path);
        return path;
    }

    bool FileExists(const std::string & path)
    {
        DWORD attrs = GetFileAttributesA(path.c_str());
        return attrs != INVALID_FILE_ATTRIBUTES && !(attrs & FILE_ATTRIBUTE_DIRECTORY);
    }

    std::string FindEmulateScript()
    {
        // Explicit override wins
        char buf[MAX_PATH] = "";
        size_t length = 0;
        if(getenv_s(&length, buf, "X64DBG_EMU_SCRIPT") == 0 && length > 0 && FileExists(buf))
            return buf;

        std::string pluginDir = PluginDir();   // <x64dbg>/x64/plugins (or similar)
        // Candidates relative to the plugin DLL, covering the release and dev layouts
        const char* const relatives[] =
        {
            "\\..\\..\\pybridge\\examples\\emulate_dump.py",       // release layout
            "\\..\\..\\..\\pybridge\\examples\\emulate_dump.py",   // dev layout (bin/x64/plugins/..)
        };
        for(const char* rel : relatives)
        {
            std::string candidate = pluginDir + rel;
            char full[MAX_PATH] = "";
            if(GetFullPathNameA(candidate.c_str(), MAX_PATH, full, nullptr) && FileExists(full))
                return full;
        }
        return {};  // caller falls back to a bare "emulate_dump.py" on PATH
    }

    // Prefers the "py" launcher (handles --3), falls back to python/python3 in PATH
    std::string FindPythonLauncher()
    {
        static const char* const names[] = { "py.exe", "python.exe", "python3.exe" };
        for(const char* name : names)
        {
            char full[MAX_PATH] = "";
            if(SearchPathA(nullptr, name, nullptr, MAX_PATH, full, nullptr) > 0)
                return full;
        }
        return {};
    }

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

    // Checks if 127.0.0.1:port already has a listener (short connect probe, 50 ms timeout).
    // Used after launching the emulator to confirm it actually bound its port.
    bool PortIsListening(unsigned short port)
    {
        WSADATA wsa;
        if(WSAStartup(MAKEWORD(2, 2), &wsa) != 0)
            return false;
        SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        bool ok = false;
        if(s != INVALID_SOCKET)
        {
            u_long nonblocking = 1;
            ioctlsocket(s, FIONBIO, &nonblocking);
            sockaddr_in addr = {};
            addr.sin_family = AF_INET;
            addr.sin_port = htons(port);
            addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            connect(s, (sockaddr*)&addr, sizeof(addr));
            fd_set wfd;
            FD_ZERO(&wfd);
            FD_SET(s, &wfd);
            timeval tv = { 0, 50000 };  // 50 ms
            if(select(0, nullptr, &wfd, nullptr, &tv) > 0)
            {
                int err = 0;
                int len = sizeof(err);
                getsockopt(s, SOL_SOCKET, SO_ERROR, (char*)&err, &len);
                ok = (err == 0);
            }
            closesocket(s);
        }
        WSACleanup();
        return ok;
    }

    // pybridge.emu "C:\path\crash.dmp"[, port[, thread[, keepgoing]]]
    // Launches emulate_dump.py --serve in a new console so the dump can be driven like a
    // live target through x64dbg_bridge.Debugger(port=...). The script path is auto-discovered
    // relative to the plugin DLL (release and dev layouts) unless X64DBG_EMU_SCRIPT overrides it.
    bool CbEmu(int argc, char* argv[])
    {
        if(argc < 2)
        {
            _plugin_logputs("[" PLUGIN_NAME "] usage: pybridge.emu \"dump.dmp\"[, port[, thread[, keepgoing]]]");
            return false;
        }

        std::string script = FindEmulateScript();
        if(script.empty())
        {
            _plugin_logprintf("[" PLUGIN_NAME "] emulate_dump.py not found. Set X64DBG_EMU_SCRIPT to its full path, "
                              "or place pybridge\\examples\\emulate_dump.py next to the x64dbg release.\n");
            return false;
        }

        std::string python = FindPythonLauncher();
        if(python.empty())
        {
            _plugin_logputs("[" PLUGIN_NAME "] no Python interpreter found (looked for py.exe, python.exe, python3.exe). "
                            "Install Python 3 or the Python Launcher (https://www.python.org/).");
            return false;
        }

        std::string port = argc > 2 ? argv[2] : "27041";
        unsigned short portNumber = 0;
        if(!ParsePort(port.c_str(), portNumber))
        {
            _plugin_logprintf("[" PLUGIN_NAME "] invalid port \"%s\" (decimal number expected)\n", port.c_str());
            return false;
        }
        std::string thread = argc > 3 ? argv[3] : "0";
        bool keepGoing = argc > 4 && (argv[4][0] == '1' || argv[4][0] == 'y' || argv[4][0] == 'Y');

        // "py" takes "-3"; "python"/"python3" do not
        bool isLauncher = _stricmp(PathFindFileNameA(python.c_str()), "py.exe") == 0;
        std::string cmd = "\"" + python + "\"" + (isLauncher ? " -3" : "") +
                          " \"" + script + "\" --serve --port " + port +
                          " --thread " + thread + (keepGoing ? " --keep-going" : "") +
                          " \"" + argv[1] + "\"";

        _plugin_logprintf("[" PLUGIN_NAME "] launching: %s\n", cmd.c_str());

        STARTUPINFOA si = { sizeof(si) };
        PROCESS_INFORMATION pi = {};
        std::string mutableCmd = cmd;  // CreateProcessA may modify the command line buffer
        // Run the emulator in the script's own folder so its sibling imports resolve
        std::string scriptDir = script;
        PathRemoveFileSpecA(&scriptDir[0]);
        scriptDir.resize(strlen(scriptDir.c_str()));
        if(!CreateProcessA(nullptr, mutableCmd.data(), nullptr, nullptr, FALSE,
                           CREATE_NEW_CONSOLE, nullptr, scriptDir.c_str(), &si, &pi))
        {
            _plugin_logprintf("[" PLUGIN_NAME "] CreateProcess failed (error %lu)\n", GetLastError());
            return false;
        }
        CloseHandle(pi.hThread);

        // Give the emulator a moment to parse the dump and bind the port. We wait up to 5s;
        // if the process dies first (e.g. missing Unicorn, bad dump) we report that instead.
        bool listening = false;
        for(int i = 0; i < 50 && !listening; i++)
        {
            Sleep(100);
            DWORD exitCode = 0;
            if(GetExitCodeProcess(pi.hProcess, &exitCode) && exitCode != STILL_ACTIVE)
            {
                _plugin_logprintf("[" PLUGIN_NAME "] emulator exited early with code %lu "
                                  "(check its console; often: missing 'unicorn' pip package or unreadable dump)\n", exitCode);
                CloseHandle(pi.hProcess);
                return false;
            }
            listening = PortIsListening(portNumber);
        }
        CloseHandle(pi.hProcess);
        if(!listening)
        {
            _plugin_logprintf("[" PLUGIN_NAME "] emulator started but 127.0.0.1:%s is not listening yet; "
                              "the dump may be large or the script is still parsing.\n", port.c_str());
        }
        else
        {
            _plugin_logprintf("[" PLUGIN_NAME "] emulating %s on 127.0.0.1:%s "
                              "(connect with Debugger(port=%s))\n", argv[1], port.c_str(), port.c_str());
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
