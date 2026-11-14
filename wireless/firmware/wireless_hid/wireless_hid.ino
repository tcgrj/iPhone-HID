#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <esp_random.h>
#include <cJSON.h>
#include <errno.h>
#include <lwip/sockets.h>
#include "BleKeyboardMouse.h"

// Mac --Wi-Fi--> ESP32 --BLE HID--> iPhone. No camera or USB HID.
BleKeyboardMouse hid;
WebServer web(80);
WiFiServer commandServer(8768, 2);
WiFiClient commandClient;
String commandLine;
Preferences preferences;
String networkSSID;
String networkPassword;
String deviceToken;
String pendingSSID;
String pendingPassword;
bool pendingNetwork = false;
bool storageReady = false;
bool mdnsReady = false;
String serialLine;
bool serialOverflow = false;
uint32_t nextReconnect = 0;

String encode(cJSON* value) {
  if (!value) return "{\"error\":\"out of memory\"}";
  char* serialized = cJSON_PrintUnformatted(value);
  const String result = serialized ? String(serialized) : "{\"error\":\"out of memory\"}";
  if (serialized) cJSON_free(serialized);
  cJSON_Delete(value);
  return result;
}

String errorJSON(const char* message) {
  cJSON* value = cJSON_CreateObject();
  if (value) cJSON_AddStringToObject(value, "error", message);
  return encode(value);
}

cJSON* parseObject(const String& body) {
  if (body.isEmpty() || body.length() > 2048) return nullptr;
  cJSON* value = cJSON_ParseWithLengthOpts(body.c_str(), body.length() + 1, nullptr, true);
  if (value && !cJSON_IsObject(value)) {
    cJSON_Delete(value);
    return nullptr;
  }
  return value;
}

String statusJSON() {
  cJSON* value = cJSON_CreateObject();
  if (value) {
    cJSON_AddBoolToObject(value, "paired", hid.isPaired());
    cJSON_AddBoolToObject(value, "mouse", hid.mouseReady());
    cJSON_AddBoolToObject(value, "keyboard", hid.keyboardReady());
    cJSON_AddBoolToObject(value, "connected", WiFi.status() == WL_CONNECTED);
    cJSON_AddNumberToObject(value, "uptime", millis() / 1000);
  }
  return encode(value);
}

String networkJSON() {
  cJSON* value = cJSON_CreateObject();
  if (value) {
    const bool connected = WiFi.status() == WL_CONNECTED;
    cJSON_AddStringToObject(value, "ip", connected ? WiFi.localIP().toString().c_str() : "");
    cJSON_AddBoolToObject(value, "connected", connected);
    cJSON_AddStringToObject(value, "token", deviceToken.c_str());
    cJSON_AddStringToObject(value, "ssid", networkSSID.c_str());
  }
  return encode(value);
}

bool allHex(const String& value) {
  for (size_t i = 0; i < value.length(); ++i) if (!isxdigit(static_cast<unsigned char>(value[i]))) return false;
  return true;
}

bool validNetwork(const String& ssid, const String& password) {
  if (ssid.isEmpty() || ssid.length() > 32) return false;
  for (size_t i = 0; i < ssid.length(); ++i) if (static_cast<uint8_t>(ssid[i]) < 32) return false;
  return password.isEmpty() || (password.length() >= 8 && password.length() <= 63)
         || (password.length() == 64 && allHex(password));
}

void configureNetwork(const String& body) {
  cJSON* value = parseObject(body);
  if (!value) {
    Serial.println(errorJSON("expected wifi JSON object"));
    return;
  }
  const cJSON* ssidValue = cJSON_GetObjectItemCaseSensitive(value, "ssid");
  const cJSON* passwordValue = cJSON_GetObjectItemCaseSensitive(value, "password");
  const bool strings = cJSON_IsString(ssidValue) && cJSON_IsString(passwordValue);
  const String ssid = strings ? ssidValue->valuestring : "";
  const String password = strings ? passwordValue->valuestring : "";
  cJSON_Delete(value);
  if (!strings || !validNetwork(ssid, password)) {
    Serial.println(errorJSON("invalid SSID or password length"));
    return;
  }
  // One NVS record keeps SSID and password consistent if power is lost.
  cJSON* record = cJSON_CreateObject();
  if (!record) {
    Serial.println(errorJSON("out of memory"));
    return;
  }
  cJSON_AddStringToObject(record, "ssid", ssid.c_str());
  cJSON_AddStringToObject(record, "password", password.c_str());
  const String saved = encode(record);
  if (!storageReady || preferences.putString("network", saved) == 0) {
    Serial.println(errorJSON("could not save Wi-Fi configuration"));
    return;
  }
  pendingSSID = ssid;
  pendingPassword = password;
  pendingNetwork = true;
  Serial.println("{\"ok\":true}");
}

void handleSerial() {
  while (Serial.available()) {
    const char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (serialOverflow) Serial.println(errorJSON("serial line too long"));
      else if (serialLine == "network") Serial.println(networkJSON());
      else if (serialLine == "status") Serial.println(statusJSON());
      else if (serialLine.startsWith("wifi ")) configureNetwork(serialLine.substring(5));
      else if (!serialLine.isEmpty()) Serial.println(errorJSON("unknown USB command"));
      serialLine = "";
      serialOverflow = false;
    } else if (!serialOverflow) {
      if (serialLine.length() >= 1030) serialOverflow = true;
      else serialLine += c;
    }
  }
}

bool authorizedToken(const String& supplied) {
  if (deviceToken.length() != 32 || supplied.length() != deviceToken.length()) return false;
  uint8_t difference = 0;
  for (size_t i = 0; i < deviceToken.length(); ++i) difference |= supplied[i] ^ deviceToken[i];
  return difference == 0;
}

bool authorized() { return authorizedToken(web.header("X-Device-Token")); }

void jsonResponse(int status, const String& content) {
  web.client().setNoDelay(true);
  web.sendHeader("Cache-Control", "no-store");
  web.send(status, "application/json", content);
}

bool moveOverTime(int dx, int dy, int duration, bool drag) {
  const uint32_t epoch = hid.generation();
  if (!hid.mouseReady() || (drag && !hid.press(MouseButton::Left))) return false;
  const int steps = max(1, duration / 15);
  int sentX = 0, sentY = 0;
  const uint32_t started = millis();
  bool ok = true;
  for (int step = 1; step <= steps; ++step) {
    const uint32_t scheduled = started + duration * step / steps;
    const int32_t remaining = static_cast<int32_t>(scheduled - millis());
    if (remaining > 0) delay(remaining);
    if (!hid.mouseReady() || hid.generation() != epoch) { ok = false; break; }
    const float t = static_cast<float>(step) / steps;
    const float eased = t * t * (3.0f - 2.0f * t);
    const int x = lroundf(dx * eased), y = lroundf(dy * eased);
    if ((x != sentX || y != sentY) && !hid.move(x - sentX, y - sentY)) { ok = false; break; }
    sentX = x;
    sentY = y;
  }
  // Never release on a different connection. Disconnect resets local button state.
  if (drag && hid.generation() == epoch) {
    delay(15);
    if (!hid.release(MouseButton::Left)) ok = false;
  }
  return ok && hid.mouseReady() && hid.generation() == epoch;
}

bool movementArguments(const char* text, int* values, size_t count) {
  for (size_t i = 0; i < count; ++i) {
    while (*text == ' ') ++text;
    if (!*text) return false;
    char* end = nullptr;
    errno = 0;
    const long value = strtol(text, &end, 10);
    if (end == text || errno == ERANGE || value < -600 || value > 600) return false;
    if (*end && *end != ' ') return false;
    values[i] = value;
    text = end;
  }
  while (*text == ' ') ++text;
  return !*text;
}

String executeCommand(const String& command, int& status) {
  status = 400;
  if (command == "status") {
    status = 200;
    return statusJSON();
  }
  if (command.length() > 90) {
    return errorJSON("command too long");
  }
  bool ok = false;
  if (command.startsWith("type ")) {
    const String hex = command.substring(5);
    if (hex.isEmpty() || hex.length() > 80 || hex.length() % 2 || !allHex(hex)) {
      return errorJSON("type expects up to 40 printable ASCII bytes in hex");
    }
    uint8_t text[40];
    for (size_t i = 0; i < hex.length() / 2; ++i) {
      char pair[] = {hex[2 * i], hex[2 * i + 1], 0};
      text[i] = strtoul(pair, nullptr, 16);
      if (text[i] < 32 || text[i] > 126) {
        return errorJSON("type supports printable ASCII only");
      }
    }
    if (!hid.keyboardReady()) {
      status = 409;
      return errorJSON("iPhone keyboard is not connected and subscribed");
    }
    ok = hid.type(text, hex.length() / 2);
  } else {
    if (!hid.mouseReady()) {
      status = 409;
      return errorJSON("iPhone mouse is not connected and subscribed");
    }
    int arguments[3] = {};
    if (command == "click") ok = hid.click(MouseButton::Left, 30);
    else if (command.startsWith("move ") &&
             movementArguments(command.c_str() + 5, arguments, 2) &&
             arguments[0] >= -127 && arguments[0] <= 127 && arguments[1] >= -127 && arguments[1] <= 127) {
      ok = hid.move(arguments[0], arguments[1]);
    } else if (command.startsWith("glide ") || command.startsWith("drag ")) {
      const bool drag = command.startsWith("drag ");
      if (!movementArguments(command.c_str() + (drag ? 5 : 6), arguments, 3) ||
          (!arguments[0] && !arguments[1]) || arguments[2] < 120 || arguments[2] > 600) {
        return errorJSON("expected dx/dy within 600 and duration 120..600 ms");
      }
      ok = moveOverTime(arguments[0], arguments[1], arguments[2], drag);
    } else {
      return errorJSON("unknown command or invalid movement");
    }
  }
  status = ok ? 200 : 503;
  return ok ? "{\"ok\":true}" : errorJSON("HID send interrupted; inspect screen before retrying");
}

void handleCommand() {
  if (!authorized()) {
    jsonResponse(401, errorJSON("invalid device token"));
    return;
  }
  cJSON* value = parseObject(web.arg("plain"));
  const cJSON* item = value ? cJSON_GetObjectItemCaseSensitive(value, "command") : nullptr;
  if (!cJSON_IsString(item)) {
    if (value) cJSON_Delete(value);
    jsonResponse(400, errorJSON("expected JSON command string"));
    return;
  }
  const String command = item->valuestring;
  cJSON_Delete(value);
  int status = 400;
  const String response = executeCommand(command, status);
  jsonResponse(status, response);
}

bool lineResponse(const String& response) {
  // One write prevents a separate newline packet; a failed reply is never retried.
  const String line = response + '\n';
  const bool ok = commandClient.write(reinterpret_cast<const uint8_t*>(line.c_str()), line.length()) == line.length();
  if (!ok) commandClient.stop();
  return ok;
}

void handleCommandLine(const String& line) {
  cJSON* value = parseObject(line);
  const cJSON* token = value ? cJSON_GetObjectItemCaseSensitive(value, "token") : nullptr;
  const cJSON* command = value ? cJSON_GetObjectItemCaseSensitive(value, "command") : nullptr;
  if (!cJSON_IsString(token) || !authorizedToken(token->valuestring)) {
    if (value) cJSON_Delete(value);
    lineResponse(errorJSON("invalid device token"));
    commandClient.stop();
    return;
  }
  if (!cJSON_IsString(command)) {
    cJSON_Delete(value);
    lineResponse(errorJSON("expected JSON command string"));
    return;
  }
  const String action = command->valuestring;
  cJSON_Delete(value);
  int status = 400;
  lineResponse(executeCommand(action, status));
}

void handleCommandSocket() {
  if (!commandClient.connected()) {
    commandClient.stop();
    commandLine = "";  // A partial command never carries over into a new connection.
    commandClient = commandServer.accept();
    if (commandClient) {
      commandClient.setNoDelay(true);
      int enabled = 1, idle = 20, interval = 5, count = 3;
      commandClient.setSocketOption(SOL_SOCKET, SO_KEEPALIVE, &enabled, sizeof(enabled));
      commandClient.setOption(TCP_KEEPIDLE, &idle);
      commandClient.setOption(TCP_KEEPINTVL, &interval);
      commandClient.setOption(TCP_KEEPCNT, &count);
    }
  }
  // One owner at a time. Extra clients can reconnect after the current one closes.
  if (commandClient.connected() && commandServer.hasClient()) {
    WiFiClient extra = commandServer.accept();
    extra.stop();
  }
  while (commandClient.connected() && commandClient.available()) {
    const char c = commandClient.read();
    if (c == '\n') {
      if (commandLine.endsWith("\r")) commandLine.remove(commandLine.length() - 1);
      if (!commandLine.isEmpty()) handleCommandLine(commandLine);
      commandLine = "";
      return;  // Service USB and HTTP between complete commands.
    }
    if (c == '\0' || commandLine.length() >= 2048) {
      lineResponse(errorJSON("invalid or oversized command line"));
      commandClient.stop();
      commandLine = "";
      return;
    }
    commandLine += c;
  }
}

void setup() {
  Serial.begin(115200);
  serialLine.reserve(1032);
  commandLine.reserve(2048);
  WiFi.mode(WIFI_STA);
  WiFi.setHostname("techge-iphone");
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  storageReady = preferences.begin("techge-hid", false);
  if (storageReady) deviceToken = preferences.getString("token", "");
  if (deviceToken.length() != 32 || !allHex(deviceToken)) {
    uint8_t randomBytes[16];
    esp_fill_random(randomBytes, sizeof(randomBytes));
    char encoded[33];
    for (size_t i = 0; i < sizeof(randomBytes); ++i) snprintf(encoded + 2 * i, 3, "%02x", randomBytes[i]);
    deviceToken = encoded;
    if (storageReady) preferences.putString("token", deviceToken);
  }
  if (storageReady) {
    cJSON* saved = parseObject(preferences.getString("network", ""));
    if (saved) {
      const cJSON* ssid = cJSON_GetObjectItemCaseSensitive(saved, "ssid");
      const cJSON* password = cJSON_GetObjectItemCaseSensitive(saved, "password");
      if (cJSON_IsString(ssid) && cJSON_IsString(password) && validNetwork(ssid->valuestring, password->valuestring)) {
        pendingSSID = ssid->valuestring;
        pendingPassword = password->valuestring;
        pendingNetwork = true;
      }
      cJSON_Delete(saved);
    }
  }
  hid.begin();
  const char* headers[] = {"X-Device-Token"};
  web.collectHeaders(headers, 1);
  web.on("/status", HTTP_GET, []() {
    if (!authorized()) jsonResponse(401, errorJSON("invalid device token"));
    else jsonResponse(200, statusJSON());
  });
  web.on("/command", HTTP_POST, handleCommand);
  web.onNotFound([]() { jsonResponse(404, errorJSON("unknown endpoint")); });
  web.begin();
  commandServer.begin();
  commandServer.setNoDelay(true);
}

void loop() {
  handleSerial();
  if (pendingNetwork) {
    pendingNetwork = false;
    commandClient.stop();
    commandLine = "";
    if (mdnsReady) { MDNS.end(); mdnsReady = false; }
    WiFi.disconnect(false, false);
    networkSSID = pendingSSID;
    networkPassword = pendingPassword;
    pendingPassword = "";
    WiFi.begin(networkSSID.c_str(), networkPassword.c_str());
    nextReconnect = millis() + 20000;
  }
  if (WiFi.status() == WL_CONNECTED) {
    if (!mdnsReady) {
      mdnsReady = MDNS.begin("techge-iphone");
      if (mdnsReady) {
        MDNS.addService("http", "tcp", 80);
        MDNS.addService("techge-hid", "tcp", 8768);
      }
    }
  } else {
    commandClient.stop();
    commandLine = "";
    if (mdnsReady) { MDNS.end(); mdnsReady = false; }
    if (!networkSSID.isEmpty() && static_cast<int32_t>(millis() - nextReconnect) >= 0) {
      WiFi.reconnect();
      nextReconnect = millis() + 20000;
    }
  }
  handleCommandSocket();
  web.handleClient();
  delay(1);
}
