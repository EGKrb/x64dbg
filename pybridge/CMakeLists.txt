cmake_minimum_required(VERSION 3.15)
project(pybridge CXX)

# Path to the x64dbg plugin SDK (the "pluginsdk" folder of an x64dbg release)
set(X64DBG_SDK "$ENV{LOCALAPPDATA}/Microsoft/WinGet/Packages/x64dbg.x64dbg_Microsoft.Winget.Source_8wekyb3d8bbwe/pluginsdk"
    CACHE PATH "x64dbg pluginsdk directory")

if(NOT EXISTS "${X64DBG_SDK}/_plugins.h")
    message(FATAL_ERROR "x64dbg plugin SDK not found in '${X64DBG_SDK}', pass -DX64DBG_SDK=<path to pluginsdk>")
endif()

if(CMAKE_SIZEOF_VOID_P EQUAL 8)
    set(ARCH x64)
    set(PLUGIN_EXT .dp64)
    set(JANSSON_ARCH x64)
else()
    set(ARCH x32)
    set(PLUGIN_EXT .dp32)
    set(JANSSON_ARCH x86)
endif()

add_library(pybridge SHARED
    src/api.cpp
    src/plugin.cpp
    src/server.cpp
    src/server.h
)
target_compile_features(pybridge PRIVATE cxx_std_17)
target_include_directories(pybridge PRIVATE "${X64DBG_SDK}")
target_compile_definitions(pybridge PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX _CRT_SECURE_NO_WARNINGS)
target_link_libraries(pybridge PRIVATE
    "${X64DBG_SDK}/${ARCH}dbg.lib"
    "${X64DBG_SDK}/${ARCH}bridge.lib"
    "${X64DBG_SDK}/jansson/jansson_${JANSSON_ARCH}.lib"
    ws2_32
)
set_target_properties(pybridge PROPERTIES SUFFIX "${PLUGIN_EXT}" PREFIX "")
if(MSVC)
    target_compile_options(pybridge PRIVATE /W4 /utf-8)
endif()
