// CW keyer – settings page for human emulation: http://cwkeyer.local/
// Speed comes from CW Station; this page only sets the "human effect".
// No password (local network only).
#include "webui.h"

#include <ArduinoJson.h>
#include <ESP8266WebServer.h>

#include "config.h"
#include "human.h"
#include "keyer.h"
#include "settings_store.h"

namespace webui {

namespace {

ESP8266WebServer server(HTTP_PORT);
bool started = false;
bool savePending = false;  // flash writes pause interrupts: save only when not sending

const char PAGE[] PROGMEM = R"HTML(<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CW keyer – human emulation</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--fg:#1d1d1b;--mut:#6b6a66;--line:#dedcd6;--acc:#b4531f;--ok:#2f7d4f}
@media (prefers-color-scheme:dark){:root{--bg:#171716;--card:#222220;--fg:#ecebe7;--mut:#a3a19b;--line:#3a3936;--acc:#e0874f;--ok:#6cc08f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}
main{max-width:560px;margin:0 auto;padding:20px 16px 40px}h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--mut);margin:0 0 18px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:14px}
.row{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:10px 0}
label{font-weight:600}select,input[type=number]{font:inherit;color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 8px}
input[type=number]{width:90px;text-align:right}input[type=range]{width:100%;accent-color:var(--acc)}
.amount{display:flex;gap:12px;align-items:center}.amount b{min-width:48px;text-align:right}
.hint{color:var(--mut);font-size:13px;margin:2px 0 0}summary{cursor:pointer;font-weight:600}
.grid .row{margin:6px 0}.grid label{font-weight:400}.grid .row>span{display:flex;align-items:center;gap:6px;flex:none}.unit{color:var(--mut);font-size:13px;width:30px}
button{font:inherit;border:0;border-radius:8px;padding:10px 18px;background:var(--acc);color:#fff;font-weight:600;cursor:pointer}
button.sec{background:transparent;color:var(--acc);border:1px solid var(--acc)}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}#msg{color:var(--ok);font-size:14px}
.switch{position:relative;width:46px;height:26px;flex:none}.switch input{opacity:0;width:0;height:0}
.slider{position:absolute;inset:0;background:var(--line);border-radius:26px;transition:.15s}
.slider:before{content:"";position:absolute;width:20px;height:20px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.15s}
.switch input:checked+.slider{background:var(--acc)}.switch input:checked+.slider:before{transform:translateX(20px)}
</style></head><body><main>
<h1>Human emulation</h1>
<p class="sub">Makes the keyer sound like a real operator. Speed is set by CW Station (now <span id="wpm">–</span> WPM).</p>
<div class="card">
 <div class="row"><label for="en">Human emulation</label><label class="switch"><input id="en" type="checkbox"><span class="slider"></span></label></div>
 <div class="row"><label for="st">Style</label><select id="st">
  <option value="old_timer">Old timer (bug key)</option><option value="self_taught">Self-taught</option>
  <option value="straight_key">Straight key</option><option value="random">Random</option><option value="custom">Custom</option></select></div>
 <p class="hint" id="sth"></p>
 <div class="row" style="display:block"><label for="am">Amount</label>
  <div class="amount"><input id="am" type="range" min="0" max="100" step="1"><b id="amv"></b></div>
  <p class="hint">0 % = perfect keyer. Mistakes grow with the square of the amount, so low settings stay clean.</p></div>
</div>
<div class="card"><details id="adv"><summary>Fine-tune the fist (values at 100 %)</summary>
 <p class="hint">Changing any value switches the style to Custom. The settings are the operator's handwriting.</p>
 <div class="grid" id="grid"></div></details></div>
<div class="bar"><button id="save">Save</button><button class="sec" id="roll" hidden>Roll a new random fist</button><span id="msg"></span></div>
</main><script>
const P=[["ratio","Dah/dit ratio","×",1,0.05],["ratio_spread","Ratio differs per letter ±","×",1,0.05],["weight","Weighting (marks longer)","%",100,1],
["sigma_dit","Dit jitter","%",100,1],["sigma_dah","Dah jitter","%",100,1],["sigma_gap","Gap jitter inside a letter","%",100,1],
["sigma_space","Letter/word space jitter","%",100,1],["char_space","Letter space","×",1,0.05],["word_space","Word space","×",1,0.05],
["word_tempo","Tempo change per word","%",100,1],["drift","Slow tempo wander","%",100,1],["drift_tau","Wander time scale","s",1,0.5],
["fatigue","Fatigue slowdown per minute","%",100,0.5],["fatigue_max","Fatigue at most","%",100,1],["last_stretch","Last element of letter longer","%",100,1],
["last_prob","…how often","%",100,1],["common","Common words (CQ, 73, 5NN, call) faster","%",100,1],["rare","Numbers/punctuation slower","%",100,1],
["hesitate","Pause before a number","%",100,1],["hesitate_dits","…pause length","dits",1,0.5],["split","Letter splits in two","%",100,0.5],
["run","Letters run together","%",100,0.5],["error","Wrong letter (8 dits, word again)","%",100,0.1]];
const H={old_timer:"Bug key: machine-steady dits, long dahs, heavy weighting, roomy spacing, very few mistakes.",
self_taught:"Uneven dah lengths per letter, jumpy tempo, split or merged letters, hesitates before numbers, corrects mistakes.",
straight_key:"Everything jitters a little, last element of a letter stretched, slows down over long overs.",
random:"A random style with randomized values. Saved values stay the same until you roll again.",custom:"Your own values below."};
const $=id=>document.getElementById(id);let cur=null;
const g=$("grid");for(const[n,l,u,s,st]of P){g.insertAdjacentHTML("beforeend",
`<div class="row"><label for="p_${n}">${l}</label><span><input id="p_${n}" type="number" step="${st}" min="0"><span class="unit">${u}</span></span></div>`);
$("p_"+n).addEventListener("input",()=>{$("st").value="custom";hint();});}
function hint(){$("sth").textContent=H[$("st").value]||"";$("roll").hidden=$("st").value!=="random";}
function fill(p){for(const[n,,,s]of P){$("p_"+n).value=+(p[n]*s).toFixed(3);}}
function read(){const p={};for(const[n,,,s]of P){p[n]=parseFloat($("p_"+n).value||"0")/s;}return p;}
function show(c){cur=c;$("en").checked=c.enabled;$("st").value=c.style;$("am").value=c.amount;$("amv").textContent=c.amount+" %";
$("wpm").textContent=c.wpm;fill(c.params);hint();}
async function preset(){const s=$("st").value;hint();if(s==="custom")return;
const r=await fetch("/api/preset?style="+s);fill(await r.json());}
$("st").addEventListener("change",preset);$("roll").addEventListener("click",preset);
$("am").addEventListener("input",()=>$("amv").textContent=$("am").value+" %");
$("save").addEventListener("click",async()=>{const body={enabled:$("en").checked,style:$("st").value,amount:+$("am").value,params:read()};
const r=await fetch("/api/human",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
if(r.ok){show(await r.json());$("msg").textContent="Saved";setTimeout(()=>$("msg").textContent="",2500);}else $("msg").textContent="Error "+r.status;});
fetch("/api/human").then(r=>r.json()).then(show);
</script></body></html>)HTML";

void addParams(JsonObject o, const human::Params& p) {
  for (size_t i = 0; i < human::PARAM_COUNT; ++i) o[human::paramName(i)] = human::param(p, i);
}

void sendConfig() {
  const human::Config& c = keyer::humanConfig();
  JsonDocument d;
  d["enabled"] = c.enabled;
  d["style"] = human::styleName(c.style);
  d["amount"] = c.amount;
  d["wpm"] = keyer::wpm();
  addParams(d["params"].to<JsonObject>(), c.p);
  String s;
  serializeJson(d, s);
  server.send(200, "application/json", s);
}

void handlePreset() {
  int st = human::styleFromName(server.arg("style").c_str());
  human::Params p;
  if (st == human::RANDOM) p = human::randomParams(ESP.random());
  else if (st >= 0 && st < human::RANDOM) p = human::preset((uint8_t)st);
  else p = keyer::humanConfig().p;
  JsonDocument d;
  addParams(d.to<JsonObject>(), p);
  String s;
  serializeJson(d, s);
  server.send(200, "application/json", s);
}

void handleSave() {
  JsonDocument d;
  if (deserializeJson(d, server.arg("plain"))) {
    server.send(400, "text/plain", "bad json");
    return;
  }
  human::Config c = keyer::humanConfig();
  if (d["enabled"].is<bool>()) c.enabled = d["enabled"].as<bool>();
  if (d["amount"].is<int>()) c.amount = (uint8_t)constrain(d["amount"].as<int>(), 0, 100);
  int st = human::styleFromName(d["style"] | "");
  if (st >= 0) c.style = (uint8_t)st;
  JsonObject p = d["params"];
  if (!p.isNull())
    for (size_t i = 0; i < human::PARAM_COUNT; ++i)
      if (p[human::paramName(i)].is<float>()) human::param(c.p, i) = p[human::paramName(i)].as<float>();
  human::sanitize(c.p);
  keyer::setHuman(c);  // in use for text sent from now on
  savePending = true;
  Serial.printf("[human] %s %s %u %%\n", c.enabled ? "on" : "off", human::styleName(c.style), c.amount);
  sendConfig();
}

}  // namespace

bool begin() {
  if (started) return true;
  server.on("/", HTTP_GET, []() { server.send_P(200, "text/html; charset=utf-8", PAGE); });
  server.on("/api/human", HTTP_GET, sendConfig);
  server.on("/api/human", HTTP_POST, handleSave);
  server.on("/api/preset", HTTP_GET, handlePreset);
  server.onNotFound([]() { server.send(404, "text/plain", "not found"); });
  server.begin();
  started = true;
  return true;
}

void loop() {
  if (!started) return;
  server.handleClient();
  if (savePending && !keyer::busy()) {
    savePending = false;
    Serial.printf("[human] %s\n", store::save(keyer::humanConfig()) ? "saved" : "save FAILED");
  }
}

}  // namespace webui
