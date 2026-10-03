#pragma once

#include <winsock2.h>
#include <atomic>
#include <string>
#include <thread>

// Line-based JSON server bound to 127.0.0.1. One client is served at a time.
class BridgeServer
{
public:
    ~BridgeServer();
    bool Start(unsigned short port, std::string & error);
    void Stop();
    bool IsRunning() const { return mRunning; }
    unsigned short Port() const { return mPort; }

private:
    void ServeLoop();
    void ServeClient(SOCKET client);

    std::atomic<bool> mRunning{ false };
    std::atomic<SOCKET> mListen{ INVALID_SOCKET };
    std::atomic<SOCKET> mClient{ INVALID_SOCKET };
    std::thread mThread;
    unsigned short mPort = 0;
};

// Handles one request line and returns the response line (without the trailing newline).
// Long waits are aborted when serverRunning becomes false.
std::string BridgeHandleRequest(const std::string & line, const std::atomic<bool> & serverRunning);
