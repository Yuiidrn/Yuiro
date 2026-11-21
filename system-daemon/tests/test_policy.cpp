#include <yuiro/security/policy.hpp>

#include <cassert>
#include <iostream>

int main() {
  assert(yuiro::Policy::requires_approval("terminal_exec") == true);
  assert(yuiro::Policy::requires_approval("app_open") == false);
  assert(yuiro::Policy::requires_approval("process_kill") == true);
  // path guard: allow inside base, reject traversal
  assert(yuiro::Policy::path_allowed("C:/safe/a.txt", "C:/safe") == true);
  assert(yuiro::Policy::path_allowed("C:/outside/a.txt", "C:/safe") == false);
  std::cout << "policy tests passed\n";
  return 0;
}
