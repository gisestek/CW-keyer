// CW keyer – ESP8266 (Wemos D1 mini) firmware
// WebSocket JSON -rajapinta (PROTOCOL.md), kotiverkko + varatukiasema.
// Lisenssi: AGPL-3.0-or-later (projektin lisenssi, NFR-06)

#include "config.h"

#include <ArduinoJson.h>
#include <ESP8266WiFi.h>
#include <ESP8266mDNS.h>
#include <WebSocketsServer.h>
#include <WiFiManager.h>
#if ENABLE_OTA
#include <ArduinoOTA.h>
#endif

#include "keyer.h"

static WebSocketsServer ws(WS_PORT);
static WiFiManager wm;
static int controller = -1;          // ohjaava asiakas (hello), -1 = ei ketään
static bool lastBusy = false;
static bool mdnsStarted = false;

// ---------------------------------------------------------------------------
// Viestit
// ---------------------------------------------------------------------------
static void sendDoc(int num, JsonDocument& doc) {
  String s;
  serializeJson(doc, s);
  if (num < 0) ws.broadcastTXT(s);
  else ws.sendTXT((uint8_t)num, s);
}

static void addConfig(JsonObject cfg) {
  keyer::Limits l = keyer::limits();
  cfg["wpm"] = keyer::wpm();
  cfg["weight"] = keyer::weight();
  cfg["keydown_max_ms"] = l.keydownMs;
  cfg["tune_max_ms"] = l.tuneMs;
  cfg["tx_max_ms"] = l.txMs;
  cfg["heartbeat_ms"] = l.heartbeatMs;
}

static void sendError(int num, const char* code, const char* msg) {
  JsonDocument d;
  d["ev"] = "error";
  d["code"] = code;
  d["msg"] = msg;
  sendDoc(num, d);
}

static void sendState(int num) {
  JsonDocument d;
  d["ev"] = "state";
  d["busy"] = keyer::busy();
  d["key"] = keyer::keyDown();
  d["pending"] = keyer::pendingChars();
  d["controller"] = controller;
  sendDoc(num, d);
}

static void sendStopped(const char* reason) {
  JsonDocument d;
  d["ev"] = "stopped";
  d["reason"] = reason;
  sendDoc(-1, d);
}

static void sendHello(int num) {
  JsonDocument d;
  d["ev"] = "hello";
  d["fw"] = FW_NAME;
  d["version"] = FW_VERSION;
  d["proto"] = PROTO_VERSION;
  JsonArray caps = d["caps"].to<JsonArray>();
  caps.add("cw");
  caps.add("tune");
  caps.add("echo");
  d["controller"] = (controller == num);
  addConfig(d["cfg"].to<JsonObject>());
  sendDoc(num, d);
}

static void doStop(const char* reason) {
  keyer::stop();
  Serial.printf("[keyer] STOP (%s)\n", reason);
  sendStopped(reason);
}

// ---------------------------------------------------------------------------
// Komennot
// ---------------------------------------------------------------------------
static void handleCommand(uint8_t num, uint8_t* payload, size_t length) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) {
    sendError(num, "BAD_JSON", err.c_str());
    return;
  }
  const char* cmd = doc["cmd"] | "";
  bool isController = (controller == (int)num);
  if (isController) keyer::hostActivity();

  if (!strcmp(cmd, "hello")) {
    if (controller >= 0 && controller != (int)num) {
      if (keyer::busy()) doStop("controller_changed");
      JsonDocument d;
      d["ev"] = "control";
      d["owner"] = false;
      sendDoc(controller, d);
    }
    controller = num;
    keyer::hostActivity();
    Serial.printf("[ws] #%u ohjaa\n", num);
    sendHello(num);
    return;
  }
  if (!strcmp(cmd, "ping")) {
    JsonDocument d;
    d["ev"] = "pong";
    d["t"] = doc["t"];
    sendDoc(num, d);
    return;
  }
  if (!strcmp(cmd, "status")) {
    sendState(num);
    return;
  }
  if (!strcmp(cmd, "stop")) {  // STOP hyväksytään keneltä tahansa (SR-01)
    doStop("host");
    return;
  }

  if (!isController) {
    sendError(num, "NOT_CONTROLLER", "send hello first");
    return;
  }

  if (!strcmp(cmd, "send")) {
    const char* text = doc["text"] | "";
    size_t len = strlen(text);
    size_t acc = keyer::queueText(text, len);
    JsonDocument d;
    d["ev"] = "queued";
    d["accepted"] = acc;
    d["pending"] = keyer::pendingChars();
    sendDoc(num, d);
    if (acc < len) sendError(num, "QUEUE_FULL", "text truncated");
  } else if (!strcmp(cmd, "tune")) {
    uint32_t ms = doc["ms"] | 0;
    if (!keyer::tune(ms)) sendError(num, "BUSY", "tune only when idle");
    else Serial.printf("[keyer] TUNE %u ms\n", ms);
  } else if (!strcmp(cmd, "set")) {
    if (doc["wpm"].is<unsigned>()) keyer::setWpm(doc["wpm"].as<unsigned>());
    if (doc["weight"].is<unsigned>()) keyer::setWeight(doc["weight"].as<unsigned>());
    keyer::Limits l = keyer::limits();
    l.keydownMs = doc["keydown_max_ms"] | l.keydownMs;
    l.tuneMs = doc["tune_max_ms"] | l.tuneMs;
    l.txMs = doc["tx_max_ms"] | l.txMs;
    l.heartbeatMs = doc["heartbeat_ms"] | l.heartbeatMs;
    keyer::setLimits(l);
    JsonDocument d;
    d["ev"] = "config";
    addConfig(d["cfg"].to<JsonObject>());
    sendDoc(-1, d);
  } else if (!strcmp(cmd, "wifi_reset")) {
    doStop("wifi_reset");
    sendError(num, "RESTARTING", "wifi settings cleared, restarting");
    ws.loop();
    delay(200);
    wm.resetSettings();
    ESP.restart();
  } else {
    sendError(num, "UNKNOWN_CMD", cmd);
  }
}

static void onWsEvent(uint8_t num, WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.printf("[ws] #%u yhdisti (%s)\n", num, ws.remoteIP(num).toString().c_str());
      sendHello(num);
      break;
    case WStype_DISCONNECTED:
      Serial.printf("[ws] #%u katkaisi\n", num);
      if ((int)num == controller) {
        controller = -1;
        if (keyer::busy()) doStop("controller_lost");  // SR-04
      }
      break;
    case WStype_TEXT:
      handleCommand(num, payload, length);
      break;
    default:
      break;
  }
}

// ---------------------------------------------------------------------------
// setup / loop
// ---------------------------------------------------------------------------
void setup() {
  keyer::begin();  // ensimmäisenä: avain ylös (SR-05)

  Serial.begin(115200);
  Serial.println();
  Serial.printf("%s %s\n", FW_NAME, FW_VERSION);

  WiFi.mode(WIFI_STA);
  WiFi.setSleepMode(WIFI_NONE_SLEEP);
  WiFi.hostname(HOSTNAME);
  wm.setHostname(HOSTNAME);
  wm.setConfigPortalBlocking(false);
  wm.setConfigPortalTimeout(PORTAL_TIMEOUT_S);
  if (wm.autoConnect(AP_NAME, AP_PASSWORD)) {
    Serial.printf("[wifi] %s, IP %s\n", WiFi.SSID().c_str(), WiFi.localIP().toString().c_str());
  } else {
    Serial.printf("[wifi] asetusportaali: liity verkkoon %s, avaa http://192.168.4.1\n", AP_NAME);
  }

  ws.begin();
  ws.onEvent(onWsEvent);
  ws.enableHeartbeat(1000, 1500, 2);  // kuollut TCP-yhteys -> katkaisu -> STOP

#if ENABLE_OTA
  ArduinoOTA.setHostname(HOSTNAME);
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.onStart([]() { doStop("ota"); });
  ArduinoOTA.begin();
#endif
}

void loop() {
  wm.process();
  ws.loop();
  keyer::service();

  if (!mdnsStarted && WiFi.status() == WL_CONNECTED) {
    mdnsStarted = MDNS.begin(HOSTNAME);
    if (mdnsStarted) {
      MDNS.addService("ws", "tcp", WS_PORT);
      Serial.printf("[wifi] IP %s, ws://%s.local:%d/\n", WiFi.localIP().toString().c_str(), HOSTNAME, WS_PORT);
    }
  }
  if (mdnsStarted) MDNS.update();
#if ENABLE_OTA
  ArduinoOTA.handle();
#endif

  // Vika keskeytyksestä (aikarajat, heartbeat)
  uint8_t f = keyer::takeFault();
  if (f != keyer::FAULT_NONE) {
    Serial.printf("[keyer] VIKA %s\n", keyer::faultName(f));
    JsonDocument d;
    d["ev"] = "fault";
    d["code"] = keyer::faultName(f);
    sendDoc(-1, d);
    sendStopped(keyer::faultName(f));
  }

  // Kaiku merkki kerrallaan (FR-TX-03)
  int c;
  while ((c = keyer::popEcho()) >= 0) {
    char s[2] = {(char)c, 0};
    JsonDocument d;
    d["ev"] = "echo";
    d["ch"] = s;
    sendDoc(-1, d);
  }

  bool b = keyer::busy();
  if (b != lastBusy) {
    lastBusy = b;
    sendState(-1);
  }
}
