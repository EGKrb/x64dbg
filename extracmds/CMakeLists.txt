cmake_minimum_required(VERSION 3.15)
project(extracmds CXX)

# Path to the x64dbg plugin SDK (the "pluginsdk" folder of an x64dbg release)
set(X64DBG_SDK "$ENV{LOCALAPPDATA}/Microsoft/WinGet/Packages/x64dbg.x64dbg_Microsoft.Winget.Source_8wekyb3d8bbwe/pluginsdk"
    CACHE PATH "x64dbg pluginsdk directory")

if(NOT EXISTS "${X64DBG_SDK}/_plugins.h")
    message(FATAL_ERROR "x64dbg plugin SDK not found in '${X64DBG_SDK}', pass -DX64DBG_SDK=<path to pluginsdk>")
endif()

if(CMAKE_SIZEOF_VOID_P EQUAL 8)
    set(ARCH x64)
    set(PLUGIN_EXT .dp64)
else()
    set(ARCH x32)
    set(PLUGIN_EXT .dp32)
endif()

add_library(extracmds SHARED src/extracmds.cpp)
target_compile_features(extracmds PRIVATE cxx_std_17)
target_include_directories(extracmds PRIVATE "${X64DBG_SDK}")
target_compile_definitions(extracmds PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX _CRT_SECURE_NO_WARNINGS UNICODE _UNICODE)
target_link_libraries(extracmds PRIVATE "${X64DBG_SDK}/${ARCH}dbg.lib" "${X64DBG_SDK}/${ARCH}bridge.lib")
set_target_properties(extracmds PROPERTIES SUFFIX "${PLUGIN_EXT}" PREFIX "" OUTPUT_NAME "ExtraCmds")
if(MSVC)
    target_compile_options(extracmds PRIVATE /W4 /utf-8)
endif()
