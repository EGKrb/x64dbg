#include "server.h"

#include <ws2tcpip.h>
#include <algorithm>
#include <vector>

namespace
{
    // Refuse absurdly long request lines instead of growing the buffer forever
    constexpr size_t MaxRequestSize = 256 * 1024 * 1024;

    bool SendAll(SOCKET s, const std::string & data)
    {
        size_t sent = 0;
        while(sent < data.size())
        {
            int n = send(s, data.data() + sent, (int)std::min<size_t>(data.size() - sent, 1 << 20), 0);
            if(n <= 0)
                return false;
            sent += n;
        }
        return true;
    }

    void CloseSocket(std::atomic<SOCKET> & s)
    {
        SOCKET old = s.exchange(INVALID_SOCKET);
        if(old != INVALID_SOCKET)
        {
            shutdown(old, SD_BOTH);
            closesocket(old);
        }
    }
}

BridgeServer::~BridgeServer()
{
    Stop();
}

bool BridgeServer::Start(unsigned short port, std::string & error)
{
    if(mRunning)
    {
        error = "already running on port " + std::to_string(mPort);
        return false;
    }

    WSADATA wsa;
    if(WSAStartup(MAKEWORD(2, 2), &wsa) != 0)
    {
        error = "WSAStartup failed";
        return false;
    }

    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if(s == INVALID_SOCKET)
    {
        error = "socket() failed, error " + std::to_string(WSAGetLastError());
        WSACleanup();
        return false;
    }
    BOOL exclusive = TRUE;
    setsockopt(s, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, (const char*)&exclusive, sizeof(exclusive));

    // Only accept local connections: a client can fully control the debugger
    sockaddr_in addr = {};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if(bind(s, (sockaddr*)&addr, sizeof(addr)) != 0 || listen(s, 1) != 0)
    {
        error = "cannot listen on 127.0.0.1:" + std::to_string(port) + ", error " + std::to_string(WSAGetLastError());
        closesocket(s);
        WSACleanup();
        return false;
    }
    int addrSize = sizeof(addr);
    getsockname(s, (sockaddr*)&addr, &addrSize);
    mPort = ntohs(addr.sin_port);

    mListen = s;
    mRunning = true;
    mThread = std::thread(&BridgeServer::ServeLoop, this);
    return true;
}

void BridgeServer::Stop()
{
    if(!mRunning.exchange(false))
        return;
    CloseSocket(mListen);
    CloseSocket(mClient);
    if(mThread.joinable())
        mThread.join();
    WSACleanup();
}

void BridgeServer::ServeLoop()
{
    while(mRunning)
    {
        SOCKET client = accept(mListen, nullptr, nullptr);
        if(client == INVALID_SOCKET)
        {
            if(!mRunning)
                break;
            Sleep(10);
            continue;
        }
        mClient = client;
        ServeClient(client);
        CloseSocket(mClient);
    }
}

void BridgeServer::ServeClient(SOCKET client)
{
    std::string buffer;
    std::vector<char> chunk(64 * 1024);
    while(mRunning)
    {
        int n = recv(client, chunk.data(), (int)chunk.size(), 0);
        if(n <= 0)
            return;
        buffer.append(chunk.data(), n);

        size_t start = 0, end;
        while((end = buffer.find('\n', start)) != std::string::npos)
        {
            std::string line = buffer.substr(start, end - start);
            start = end + 1;
            if(!line.empty() && line.back() == '\r')
                line.pop_back();
            if(line.empty())
                continue;
            if(!SendAll(client, BridgeHandleRequest(line, mRunning) + "\n"))
                return;
        }
        buffer.erase(0, start);
        if(buffer.size() > MaxRequestSize)
            return;
    }
}
