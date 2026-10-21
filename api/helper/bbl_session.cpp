// EXPERIMENT: loads Bambu's own network plug-in (downloaded by the user, never shipped) and gives it a sign-in the user did in their browser,
// to find out what the plug-in then reports. One JSON object on stdin; one JSON object per step on stdout (so a crash still leaves what ran).
// Secrets (tokens) are read from stdin only and never written to stdout; device identifiers and access codes are never written either.
#include <dlfcn.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <atomic>
#include <functional>
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
  static const char* shown[] = {"dev_name", "dev_product_name", "dev_online", "dev_model_name"};
  json out = json::object();
  for (auto it = device.begin(); it != device.end(); ++it) {
    bool show = false;
    for (const char* key : shown) show = show || it.key() == key;
    out[it.key()] = show ? it.value() : json(it.value().type_name());
  }
  return out;
}

// The few fields of an account printer the server needs to add it (including the serial number and access code, which `describe` masks).
static json account_entry(const json& device) {
  json out = json::object();
  for (const char* key : {"dev_id", "dev_access_code", "dev_name", "dev_online", "dev_product_name", "dev_model_name"})
    if (device.contains(key)) out[key] = device[key];
  return out;
}

// The print job as the 02.08.04 series of Bambu's plug-in expects it: the field order and types are those of `PrintParams` in OrcaSlicer's
// bambu_networking.hpp (the plug-in takes it by value, so a field out of place misreads every one after it).
struct PrintParams {
  string dev_id, task_name, project_name, preset_name, filename, config_filename;
  int plate_index = 0;
  string ftp_folder, ftp_file, ftp_file_md5, nozzle_mapping, ams_mapping, ams_mapping2, ams_mapping_info, nozzles_info, connection_type, comments;
  int origin_profile_id = 0;
  int stl_design_id = 0;
  string origin_model_id, print_type, dst_file, dev_name, dev_ip;
  bool use_ssl_for_ftp = false, use_ssl_for_mqtt = false;
  string username, password;
  bool task_bed_leveling = false, task_flow_cali = false, task_vibration_cali = false, task_layer_inspect = false;
  bool task_record_timelapse = false, task_timelapse_use_internal = false, task_use_ams = false;
  string task_bed_type, extra_options;
  int auto_bed_leveling = 0, auto_flow_cali = 0, auto_offset_cali = 0, extruder_cali_manual_mode = -1;
  bool task_ext_change_assist = false, try_emmc_print = false;
  string svc_context, slicer_uid, queue_plate_id;
};

using StatusFn = std::function<void(int, int, string)>;
using CancelFn = std::function<bool()>;
using WaitFn = std::function<bool(int, string)>;

// Sends a sliced 3MF to a printer through the plug-in, as OrcaSlicer's print job does for a printer in cloud mode that has an address, an
// access code and storage: the plug-in uploads the file to the printer and starts it with a command only it can sign. Needs the sign-in that
// an earlier run left in the plug-in's settings folder.
static int run_print(void* lib, void* agent, const json& in) {
  auto logged = need<bool (*)(void*)>(lib, "bambu_network_is_user_login");
  auto connect_server = need<int (*)(void*)>(lib, "bambu_network_connect_server");
  auto select_machine = need<int (*)(void*, string)>(lib, "bambu_network_set_user_selected_machine");
  auto print = need<int (*)(void*, PrintParams, StatusFn, CancelFn, WaitFn)>(lib, "bambu_network_start_local_print_with_record");
  if (!logged || !print) return 4;
  step("is_user_login", logged(agent));
  auto connected = need<bool (*)(void*)>(lib, "bambu_network_is_server_connected");
  auto subscribe = need<int (*)(void*, string)>(lib, "bambu_network_start_subscribe");
  auto install_cert = need<void (*)(void*, string, bool)>(lib, "bambu_network_install_device_cert");
  const string dev_id = in.value("dev_id", "");
  auto set_on_message = need<int (*)(void*, std::function<void(string, string)>)>(lib, "bambu_network_set_on_message_fn");
  auto set_on_connected = need<int (*)(void*, std::function<void(string)>)>(lib, "bambu_network_set_on_printer_connected_fn");
  auto send_message = need<int (*)(void*, string, string, int, int)>(lib, "bambu_network_send_message");
  // What Studio asks of a printer once it is connected: its full state and its version (the plug-in works out the printer's encryption flag
  // from what comes back), and the printer's certificate.
  const string push_all = R"({"pushing":{"sequence_id":"1","command":"pushall","version":1,"push_target":1}})";
  const string get_version = R"({"info":{"sequence_id":"2","command":"get_version"}})";
  static std::atomic<int> messages{0};
  auto ask = [=](const string& id) {
    if (send_message) { send_message(agent, id, push_all, 0, 0); send_message(agent, id, get_version, 0, 0); }
  };
  if (set_on_message) set_on_message(agent, [](string, string) { messages++; });
  if (set_on_connected) set_on_connected(agent, [=](string) { ask(dev_id); });
  if (connect_server) step("connect_server", connect_server(agent));
  if (select_machine) step("select_machine", select_machine(agent, dev_id));
  // As Studio does once it is signed in: the plug-in learns the printer's encryption flag (which it signs the start command with) over the
  // cloud connection, so give it that connection, ask for the printer's messages and its certificate, and wait a little for it.
  for (int i = 0; i < 80 && connected && !connected(agent); i++) usleep(500 * 1000);
  if (connected) step("server_connected", connected(agent));
  if (subscribe) step("subscribe", subscribe(agent, "app"));
  // The connection may be slow: wait until the printer has answered (up to 60 s), then a little longer for the rest of what it sends.
  for (int i = 0; i < 30 && (i < 4 || messages.load() == 0); i++) { if (install_cert) install_cert(agent, dev_id, false); ask(dev_id); sleep(2); }
  sleep(3);
  step("printer_messages", messages.load());

  PrintParams p;
  p.dev_id = in.value("dev_id", "");
  p.dev_name = in.value("dev_name", "");
  p.dev_ip = in.value("dev_ip", "");
  p.username = "bblp";
  p.password = in.value("access_code", "");
  p.use_ssl_for_ftp = true;
  p.use_ssl_for_mqtt = true;
  p.filename = in.value("file", "");
  p.config_filename = p.filename;
  p.plate_index = in.value("plate_index", 1);
  p.project_name = in.value("project_name", "print");
  p.preset_name = p.project_name;
  p.task_name = p.project_name;
  p.connection_type = "cloud";
  p.print_type = "from_normal";
  p.ams_mapping = in.value("ams_mapping", "[]");
  p.ams_mapping2 = in.value("ams_mapping2", "[]");
  p.ams_mapping_info = in.value("ams_mapping_info", "[]");
  p.task_bed_leveling = p.task_flow_cali = p.task_vibration_cali = p.task_layer_inspect = true;
  p.task_use_ams = in.value("use_ams", false);
  p.task_bed_type = "auto";

  int rc = 0;
  for (int attempt = 0; attempt < 3; attempt++) {
    rc = print(
        agent, p,
        [](int status, int code, string msg) { step("progress", {{"stage", status}, {"code", code}, {"message", msg}}); },
        []() { return false; },
        [](int status, string info) { step("waiting", {{"status", status}, {"info", info}}); return true; });
    if (rc != -3140) break;  // the printer's flag was not ready yet (the plug-in's own "try again later"): wait and ask again
    if (install_cert) install_cert(agent, dev_id, false);
    sleep(5);
  }
  // As Bambu Studio does when the cloud route fails (PrintJob.cpp): send it over the LAN directly, as a "lan" connection, which the plug-in
  // signs and sends to the printer itself.
  auto print_lan = need<int (*)(void*, PrintParams, StatusFn, CancelFn)>(lib, "bambu_network_start_local_print");
  if (rc < 0 && rc != -3140 && print_lan) {
    step("lan_direct", true);
    p.connection_type = "lan";
    rc = print_lan(
        agent, p, [](int status, int code, string msg) { step("progress", {{"stage", status}, {"code", code}, {"message", msg}}); },
        []() { return false; });
  }
  step("print_result", rc);
  return 0;
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
  if (in.value("action", "") == "print") { int done = run_print(lib, agent, in); sleep(1); _exit(done); }

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
  json summary = json::array(), account = json::array();
  if (devices.is_object() && devices.contains("devices") && devices["devices"].is_array())
    for (const auto& d : devices["devices"]) {
      summary.push_back(describe(d));
      account.push_back(account_entry(d));
    }
  step("get_user_print_info", {{"result", rc}, {"http_code", code}, {"devices", summary}});
  // The same printers with what the server needs to add them; the server never passes these on to a browser.
  step("account_devices", account);
  _exit(0);  // the plug-in's own threads may still be running; this is a one-shot check
}
