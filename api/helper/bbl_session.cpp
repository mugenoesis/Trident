// EXPERIMENT: loads Bambu's own network plug-in (downloaded by the user, never shipped) and gives it a sign-in the user did in their browser,
// to find out what the plug-in then reports. One JSON object on stdin; one JSON object per step on stdout (so a crash still leaves what ran).
// Secrets (tokens) are read from stdin only and never written to stdout; device identifiers and access codes are never written either.
#include <dlfcn.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <string>

#include <nlohmann/json.hpp>

using nlohmann::json;
using std::string;

static void step(const char* name, json value) {
  json line = {{"step", name}, {"value", std::move(value)}};
  std::cout << line.dump() << std::endl;
}

template <class F>
static F need(void* lib, const char* name) {
  F fn = reinterpret_cast<F>(dlsym(lib, name));
  if (!fn) step("missing_function", name);
  return fn;
}

// What a device entry looks like, without anything that identifies it or unlocks it: values only for a few harmless keys.
static json describe(const json& device) {
  static const char* shown[] = {"name", "dev_product_name", "online", "print_status", "dev_model_name"};
  json out = json::object();
  for (auto it = device.begin(); it != device.end(); ++it) {
    bool show = false;
    for (const char* key : shown) show = show || it.key() == key;
    out[it.key()] = show ? it.value() : json(it.value().type_name());
  }
  return out;
}

int main() {
  // As Orca does in CurlGlobalInit (Http.cpp): the plug-in has its own TLS built in and cannot find the distro CA bundle by itself.
  setenv("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt", 0);
  json in = json::parse(std::cin, nullptr, false);
  if (in.is_discarded()) { step("error", "stdin is not JSON"); return 2; }
  const string plugin_dir = in.value("plugin_dir", ""), config_dir = in.value("config_dir", ""), cert_dir = in.value("cert_dir", "");
  mkdir(config_dir.c_str(), 0700);
  mkdir((config_dir + "/log").c_str(), 0700);

  void* lib = dlopen((plugin_dir + "/libbambu_networking.so").c_str(), RTLD_LAZY);
  if (!lib) { step("error", string("dlopen: ") + dlerror()); return 3; }
  auto create = need<void* (*)(string)>(lib, "bambu_network_create_agent");
  auto init_log = need<int (*)(void*)>(lib, "bambu_network_init_log");
  auto set_cfg = need<int (*)(void*, string)>(lib, "bambu_network_set_config_dir");
  auto set_cert = need<int (*)(void*, string, string)>(lib, "bambu_network_set_cert_file");
  auto set_cc = need<int (*)(void*, string)>(lib, "bambu_network_set_country_code");
  auto start = need<int (*)(void*)>(lib, "bambu_network_start");
  auto profile = need<int (*)(void*, string, unsigned*, string*)>(lib, "bambu_network_get_my_profile");
  auto change_user = need<int (*)(void*, string)>(lib, "bambu_network_change_user");
  auto logged = need<bool (*)(void*)>(lib, "bambu_network_is_user_login");
  auto print_info = need<int (*)(void*, unsigned*, string*)>(lib, "bambu_network_get_user_print_info");
  if (!create || !init_log || !set_cfg || !set_cert || !set_cc || !start || !profile || !change_user || !logged || !print_info) return 4;

  void* agent = create(config_dir + "/log");
  if (!agent) { step("error", "create_agent returned null"); return 5; }
  step("agent", true);
  step("set_config_dir", set_cfg(agent, config_dir));
  step("init_log", init_log(agent));
  step("set_cert_file", set_cert(agent, cert_dir, "slicer_base64.cer"));
  step("set_country_code", set_cc(agent, "US"));
  step("start", start(agent));

  unsigned code = 0;
  string body;
  int rc = profile(agent, in.value("access_token", ""), &code, &body);
  step("get_my_profile", {{"result", rc}, {"http_code", code}});
  json who = json::parse(body, nullptr, false);
  if (!who.is_object()) who = json::object();

  json login = {{"command", "user_login"},
                {"data", {{"token", in.value("access_token", "")},
                          {"refresh_token", in.value("refresh_token", "")},
                          {"expires_in", in.value("expires_in", "")},
                          {"refresh_expires_in", in.value("refresh_expires_in", "")},
                          {"user", {{"uid", who.value("uidStr", "")}, {"name", who.value("name", "")},
                                    {"account", who.value("account", "")}, {"avatar", who.value("avatar", "")}}}}}};
  step("change_user", change_user(agent, login.dump()));
  step("is_user_login", logged(agent));
  step("user_name", who.value("name", ""));

  code = 0;
  body.clear();
  rc = print_info(agent, &code, &body);
  json devices = json::parse(body, nullptr, false);
  json summary = json::array();
  if (devices.is_object() && devices.contains("devices") && devices["devices"].is_array())
    for (const auto& d : devices["devices"]) summary.push_back(describe(d));
  step("get_user_print_info", {{"result", rc}, {"http_code", code}, {"devices", summary}});
  _exit(0);  // the plug-in's own threads may still be running; this is a one-shot check
}
