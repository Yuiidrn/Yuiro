// MCP-like stdio transport. M0: accept newline-JSON requests, dispatch to
// capabilities, return SystemResult JSON. Full MCP SDK integration in M4.
#pragma once
#include <string>

namespace yuiro {

// Reads one JSON-RPC-style request from stdin, dispatches to the capability
// registry by method name (e.g. tools/call with {name, arguments}).
int run_stdio_server();

} // namespace yuiro
