// ExtraCmds: convenience commands for x64dbg.
//
//   .init file[, arguments[, folder]]   init for an executable, opens the minidump viewer for a .dmp
//   .save [file[, address[, size]]]     dbsave / minidump / savedata depending on the arguments
//   scylla_hide.enable [profile]        activate a ScyllaHide profile (default: the last active one)
//   scylla_hide.disable                 switch ScyllaHide to its "Disabled" profile
//   scylla_hide.status                  show the active ScyllaHide profile and the available ones

#include "_plugins.h"

#include <string>
#include <vector>

#define PLUGIN_NAME "ExtraCmds"
#define PLUGIN_VERSION 1
#define LOG_PREFIX "[" PLUGIN_NAME "] "

namespace
{
    int gPluginHandle;

    const char* const ScyllaHidePluginName = "ScyllaHideX64DBGPlugin";
    const wchar_t* const ScyllaHideDisabledProfile = L"Disabled";
    const wchar_t* const ScyllaHideDefaultProfile = L"Basic";

    std::wstring Utf8ToUtf16(const std::string & text)
    {
        if(text.empty())
            return {};
        int size = MultiByteToWideChar(CP_UTF8, 0, text.c_str(), (int)text.size(), nullptr, 0);
        std::wstring result(size, L'\0');
        MultiByteToWideChar(CP_UTF8, 0, text.c_str(), (int)text.size(), &result[0], size);
        return result;
    }

    std::string Utf16ToUtf8(const std::wstring & text)
    {
        if(text.empty())
            return {};
        int size = WideCharToMultiByte(CP_UTF8, 0, text.c_str(), (int)text.size(), nullptr, 0, nullptr, nullptr);
        std::string result(size, '\0');
        WideCharToMultiByte(CP_UTF8, 0, text.c_str(), (int)text.size(), &result[0], size, nullptr, nullptr);
        return result;
    }

    // Quote an argument for an x64dbg command (same rules as Command::Escape)
    std::string Quote(const std::string & argument)
    {
        std::string result = "\"";
        size_t i = 0;
        while(i < argument.size())
        {
            char ch = argument[i];
            if(ch != '\\')
            {
                if(ch == '"' || ch == '{')
                    result.push_back('\\');
                result.push_back(ch);
                i++;
                continue;
            }
            size_t start = i;
            while(i < argument.size() && argument[i] == '\\')
                i++;
            size_t count = i - start;
            if(i == argument.size())
                result.append(count * 2, '\\');
            else if(argument[i] == '"' || argument[i] == '{')
            {
                result.append(count * 2 + 1, '\\');
                result.push_back(argument[i++]);
            }
            else
                result.append(count, '\\');
        }
        return result + "\"";
    }

    bool Exec(const std::string & command)
    {
        return DbgCmdExecDirect(command.c_str());
    }

    bool HasExtension(const std::string & file, std::initializer_list<const char*> extensions)
    {
        auto dot = file.find_last_of('.');
        if(dot == std::string::npos || file.find_first_of("\\/", dot) != std::string::npos)
            return false;
        auto extension = file.substr(dot);
        for(auto candidate : extensions)
            if(_stricmp(extension.c_str(), candidate) == 0)
                return true;
        return false;
    }

    bool IsDumpFile(const std::string & file)
    {
        return HasExtension(file, { ".dmp", ".mdmp", ".hdmp" });
    }

    // Folder that contains x32\ and x64\ (parent of the folder of the running executable)
    std::wstring X64dbgRoot()
    {
        wchar_t path[MAX_PATH] = L"";
        GetModuleFileNameW(nullptr, path, _countof(path));
        std::wstring result = path;
        for(int i = 0; i < 2; i++)
        {
            auto slash = result.find_last_of(L'\\');
            if(slash == std::wstring::npos)
                return L".";
            result.resize(slash);
        }
        return result;
    }

    std::wstring ArchFolder()
    {
        wchar_t path[MAX_PATH] = L"";
        GetModuleFileNameW(nullptr, path, _countof(path));
        std::wstring result = path;
        result.resize(result.find_last_of(L'\\'));
        return result;
    }

    bool OpenInMinidumpViewer(const std::string & dumpFile)
    {
        auto dumpPath = Utf8ToUtf16(dumpFile);
        if(GetFileAttributesW(dumpPath.c_str()) == INVALID_FILE_ATTRIBUTES)
        {
            _plugin_logprintf(LOG_PREFIX "file not found: %s\n", dumpFile.c_str());
            return false;
        }
        // The viewer is a 64-bit Qt application next to x64dbg.exe; it also reads dumps of 32-bit processes
        auto viewer = X64dbgRoot() + L"\\x64\\minidump.exe";
        if(GetFileAttributesW(viewer.c_str()) == INVALID_FILE_ATTRIBUTES)
        {
            _plugin_logprintf(LOG_PREFIX "minidump viewer not found: %s\n", Utf16ToUtf8(viewer).c_str());
            return false;
        }
        std::wstring commandLine = L"\"" + viewer + L"\" \"" + dumpPath + L"\"";
        STARTUPINFOW si = { sizeof(si) };
        PROCESS_INFORMATION pi = {};
        auto viewerFolder = viewer.substr(0, viewer.find_last_of(L'\\'));
        if(!CreateProcessW(viewer.c_str(), &commandLine[0], nullptr, nullptr, FALSE, 0, nullptr, viewerFolder.c_str(), &si, &pi))
        {
            _plugin_logprintf(LOG_PREFIX "cannot start the minidump viewer (error %u)\n", GetLastError());
            return false;
        }
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
        _plugin_logprintf(LOG_PREFIX "a dump is not a running process: x64dbg cannot debug it. "
                                     "Opened %s in the minidump viewer (memory map, disassembly, hex dump, threads).\n", dumpFile.c_str());
        return true;
    }

    // .init file[, arguments[, folder]]
    bool CbInit(int argc, char* argv[])
    {
        if(argc < 2)
        {
            _plugin_logputs(LOG_PREFIX "usage: .init file[, arguments[, folder]]   (a .dmp file opens the minidump viewer)");
            return false;
        }
        if(IsDumpFile(argv[1]))
            return OpenInMinidumpViewer(argv[1]);
        std::string command = "init " + Quote(argv[1]);
        for(int i = 2; i < argc && i < 4; i++)
            command += ", " + Quote(argv[i]);
        return Exec(command);
    }

    // .save [file[, address[, size]]]
    bool CbSave(int argc, char* argv[])
    {
        switch(argc)
        {
        case 1: // program database (comments, labels, breakpoints...)
            return Exec("dbsave");
        case 2:
            if(IsDumpFile(argv[1]))
                return Exec("minidump " + Quote(argv[1])); // whole process
            return Exec("dbsave " + Quote(argv[1])); // database to a specific file
        case 3: // the memory region (page range) that contains the address
            return Exec("savedata " + Quote(argv[1]) + ", mem.base(" + argv[2] + "), mem.size(" + argv[2] + ")");
        case 4:
            return Exec("savedata " + Quote(argv[1]) + ", " + argv[2] + ", " + argv[3]);
        default:
            _plugin_logputs(LOG_PREFIX "usage:\n"
                                       "  .save                      save the program database (comments, labels, breakpoints)\n"
                                       "  .save file.dmp             full minidump of the process\n"
                                       "  .save file.dd64            program database to this file\n"
                                       "  .save file, address        memory region containing address\n"
                                       "  .save file, address, size  memory range");
            return false;
        }
    }

    std::wstring ScyllaHideIni()
    {
        return ArchFolder() + L"\\plugins\\scylla_hide.ini";
    }

    std::wstring ScyllaHideCurrentProfile()
    {
        wchar_t profile[256] = L"";
        GetPrivateProfileStringW(L"SETTINGS", L"CurrentProfile", L"", profile, _countof(profile), ScyllaHideIni().c_str());
        return profile;
    }

    std::vector<std::wstring> ScyllaHideProfiles()
    {
        std::vector<wchar_t> buffer(32 * 1024);
        DWORD size = GetPrivateProfileSectionNamesW(buffer.data(), (DWORD)buffer.size(), ScyllaHideIni().c_str());
        std::vector<std::wstring> profiles;
        for(const wchar_t* name = buffer.data(); name < buffer.data() + size && *name; name += wcslen(name) + 1)
            if(_wcsicmp(name, L"SETTINGS") != 0)
                profiles.push_back(name);
        return profiles;
    }

    // Exact match first (case-insensitive), then a unique prefix ("vmprotect" -> "VMProtect x86/x64")
    bool FindProfile(const std::wstring & wanted, std::wstring & found)
    {
        auto profiles = ScyllaHideProfiles();
        for(auto & profile : profiles)
            if(_wcsicmp(profile.c_str(), wanted.c_str()) == 0)
                return found = profile, true;
        std::vector<std::wstring> matches;
        for(auto & profile : profiles)
            if(_wcsnicmp(profile.c_str(), wanted.c_str(), wanted.size()) == 0)
                matches.push_back(profile);
        if(matches.size() == 1)
            return found = matches[0], true;
        return false;
    }

    void LogProfiles()
    {
        std::string list;
        for(auto & profile : ScyllaHideProfiles())
            list += (list.empty() ? "" : ", ") + Utf16ToUtf8(profile);
        _plugin_logprintf(LOG_PREFIX "ScyllaHide profiles: %s\n", list.c_str());
    }

    bool ScyllaHideInstalled()
    {
        if(GetFileAttributesW(ScyllaHideIni().c_str()) != INVALID_FILE_ATTRIBUTES)
            return true;
        _plugin_logprintf(LOG_PREFIX "ScyllaHide is not installed (%s not found)\n", Utf16ToUtf8(ScyllaHideIni()).c_str());
        return false;
    }

    // ScyllaHide reads scylla_hide.ini only when it is loaded: write the profile, then reload the plugin
    bool SetScyllaHideProfile(const std::wstring & profile)
    {
        auto current = ScyllaHideCurrentProfile();
        if(_wcsicmp(current.c_str(), profile.c_str()) != 0)
        {
            if(_wcsicmp(current.c_str(), ScyllaHideDisabledProfile) != 0 && !current.empty())
                BridgeSettingSet(PLUGIN_NAME, "ScyllaHideLastProfile", Utf16ToUtf8(current).c_str());
            if(!WritePrivateProfileStringW(L"SETTINGS", L"CurrentProfile", profile.c_str(), ScyllaHideIni().c_str()))
            {
                _plugin_logprintf(LOG_PREFIX "cannot write %s (error %u)\n", Utf16ToUtf8(ScyllaHideIni()).c_str(), GetLastError());
                return false;
            }
            // plugunload + plugload: plugreload would ask for confirmation in a message box
            std::string name = ScyllaHidePluginName;
            if(!Exec("plugunload " + name) || !Exec("plugload " + name))
            {
                _plugin_logputs(LOG_PREFIX "the profile was saved but ScyllaHide could not be reloaded: restart x64dbg to apply it");
                return false;
            }
        }
        _plugin_logprintf(LOG_PREFIX "ScyllaHide profile: %s\n", Utf16ToUtf8(profile).c_str());
        if(DbgIsDebugging())
            _plugin_logputs(LOG_PREFIX "ScyllaHide applies its hooks when a process starts or is attached: "
                                       "restart the debuggee (or attach again) for the change to take effect");
        return true;
    }

    // scylla_hide.enable [profile]
    bool CbScyllaHideEnable(int argc, char* argv[])
    {
        if(!ScyllaHideInstalled())
            return false;
        std::wstring profile;
        if(argc > 1)
        {
            if(!FindProfile(Utf8ToUtf16(argv[1]), profile))
            {
                _plugin_logprintf(LOG_PREFIX "unknown ScyllaHide profile \"%s\"\n", argv[1]);
                LogProfiles();
                return false;
            }
        }
        else
        {
            auto current = ScyllaHideCurrentProfile();
            if(!current.empty() && _wcsicmp(current.c_str(), ScyllaHideDisabledProfile) != 0)
                profile = current; // already enabled
            else
            {
                char last[MAX_SETTING_SIZE] = "";
                if(!BridgeSettingGet(PLUGIN_NAME, "ScyllaHideLastProfile", last) || !FindProfile(Utf8ToUtf16(last), profile))
                    profile = ScyllaHideDefaultProfile;
            }
        }
        if(_wcsicmp(profile.c_str(), ScyllaHideDisabledProfile) == 0)
        {
            _plugin_logputs(LOG_PREFIX "use scylla_hide.disable to disable ScyllaHide");
            return false;
        }
        return SetScyllaHideProfile(profile);
    }

    bool CbScyllaHideDisable(int, char*[])
    {
        if(!ScyllaHideInstalled())
            return false;
        return SetScyllaHideProfile(ScyllaHideDisabledProfile);
    }

    bool CbScyllaHideStatus(int, char*[])
    {
        if(!ScyllaHideInstalled())
            return false;
        auto current = ScyllaHideCurrentProfile();
        bool disabled = _wcsicmp(current.c_str(), ScyllaHideDisabledProfile) == 0;
        _plugin_logprintf(LOG_PREFIX "ScyllaHide is %s, profile: %s\n", disabled ? "disabled" : "enabled", Utf16ToUtf8(current).c_str());
        LogProfiles();
        return true;
    }
}

extern "C" __declspec(dllexport) bool pluginit(PLUG_INITSTRUCT* initStruct)
{
    initStruct->pluginVersion = PLUGIN_VERSION;
    initStruct->sdkVersion = PLUG_SDKVERSION;
    strncpy_s(initStruct->pluginName, PLUGIN_NAME, _TRUNCATE);
    gPluginHandle = initStruct->pluginHandle;

    _plugin_registercommand(gPluginHandle, ".init", CbInit, false);
    _plugin_registercommand(gPluginHandle, ".save", CbSave, false);
    _plugin_registercommand(gPluginHandle, "scylla_hide.enable", CbScyllaHideEnable, false);
    _plugin_registercommand(gPluginHandle, "scylla_hide.disable", CbScyllaHideDisable, false);
    _plugin_registercommand(gPluginHandle, "scylla_hide.status", CbScyllaHideStatus, false);
    return true;
}

extern "C" __declspec(dllexport) void plugstop()
{
}

extern "C" __declspec(dllexport) void plugsetup(PLUG_SETUPSTRUCT*)
{
}
