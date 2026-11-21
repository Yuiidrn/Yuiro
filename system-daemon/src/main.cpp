// yuiro SystemDaemon entrypoint.
#include <yuiro/mcp/server_stdio.hpp>
#include <iostream>

int main() {
  try {
    return yuiro::run_stdio_server();
  } catch (const std::exception& e) {
    std::cerr << "yuiro fatal: " << e.what() << "\n";
    return 1;
  }
}
