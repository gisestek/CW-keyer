# cwkeyer-esp8266 – WiFi-keyerin firmware (Wemos D1 mini)

Versio 0.1.0 · 2026-09-17 · AGPL-3.0-or-later

ESP8266-firmware, joka lähettää CW:tä relekortin kautta ja jota ohjataan WiFin yli WebSocket JSON -viesteillä ([PROTOCOL.md](PROTOCOL.md)).

## Ominaisuudet

- CW-ajoitus ja turvarajat 1 ms:n laitteistoajastimen keskeytyksessä (timer1). Toimivat, vaikka WiFi tai pääsilmukka jumittuisi.
- Teksti puskuroidaan keyerissä (1024 merkkiä): verkon viive ei vaikuta rytmiin.
- Kaiku merkki kerrallaan, WPM ja painotus lennossa, prosignit `<SK>`, TUNE.
- Turvarajat: STOP < 3 ms, avain alhaalla enintään 10,5 s, lähetys enintään 120 s ilman uutta komentoa, heartbeat 3 s, ohjaajan yhteyskatkos pysäyttää.
- WiFi: kotiverkko, varalla oma tukiasema asetuksia varten (WiFiManager). mDNS `cwkeyer.local`, OTA-päivitys.

## Kytkentä (proto, hyväksytty 17.9.2026)

```
Wemos D1 (GPIO5) ──┬──── relekortin IN   (H-ohjattu FL817C-kortti)
                   │
                 [10k]
                   │
Wemos GND ─────────┴──── relekortin GND
Wemos 5V ─────────────── relekortin VCC
Releen NO ────────────── avainjakin tip
Releen COM ───────────── avainjakin sleeve
```

Asetukset `config.h`: `KEY_PIN D1`, `KEY_ACTIVE_LOW 0`.

- **Älä käytä D4:ää (GPIO2):** ESP8266 pulssittaa sitä käynnistyksessä, resetissä ja flashauksessa, jolloin rele naksahtaa.
- **10k D1 → GND** pitää IN-nastan matalana käynnistyksen aikana.
- **NO-koskettimet:** kun Wemos on ilman virtaa tai resetissä, radio ei lähetä.
- Jos käytössä on L-ohjattu kortti, lisää NPN-transistori (D1 → 4,7k → kanta, 100k kanta–GND, kollektori → IN, emitteri → GND) ja pidä `KEY_ACTIVE_LOW 0`.
- Laitteistoinen aikarajapiiri (74HCT132, R1 200 k, M0-proto.md) puuttuu vielä; jumittuneen ESP:n varmistuksena on sen oma watchdog.

## Kääntäminen ja lataus

### PlatformIO (suositus)

```
cd cwkeyer-esp8266
pio run -t upload            # USB
pio device monitor           # sarjaloki 115200
pio run -e d1_mini_ota -t upload   # WiFi (OTA), kun laite on verkossa
```

Kirjastot latautuvat automaattisesti (`platformio.ini`).

### Arduino IDE

1. Board Manager: *esp8266 by ESP8266 Community* 3.1.x, kortti *LOLIN(WEMOS) D1 R2 & mini*.
2. Library Manager: *WebSockets* (Markus Sattler) 2.6.x, *ArduinoJson* 7.x, *WiFiManager* (tzapu) 2.0.x.
3. Avaa `cwkeyer/cwkeyer.ino` ja lataa.

### Valmis binääri (ilman kääntämistä)

`bin/cwkeyer-0.1.0-d1mini-D4-activelow.bin` on **vanha D4-versio, älä käytä sitä nykyisessä kytkennässä**. Käännä nykyinen `config.h` PlatformIO:lla. Binäärin lataus tapahtuisi näin:

```
pip install esptool
esptool.py --port COM5 write_flash 0x0 bin/cwkeyer-0.1.0-d1mini-D4-activelow.bin
```

Käännös on testattu ESP8266-ytimellä 3.1.2, WebSockets 2.6.1, ArduinoJson 7.4.2 ja WiFiManager 2.0.17: flash 410 kt, RAM 36,7 kt (45 %).

## Ensimmäinen käynnistys

1. Lataa firmware. Sarjalokissa näkyy `cwkeyer-esp8266 0.1.0`.
2. Liity puhelimella tai koneella WiFi-verkkoon **CWKeyer-Setup** (salasana `cwkeyer73`). Asetussivu aukeaa (tai avaa `http://192.168.4.1`). Valitse kotiverkko ja anna salasana.
3. Laite liittyy kotiverkkoon. Sarjalokiin tulee `ws://cwkeyer.local:81/` ja IP-osoite.
4. Vaihda `OTA_PASSWORD` (`config.h` ja `platformio.ini`) ennen kuin laite jää verkkoon.

WiFi-asetukset nollataan komennolla `{"cmd":"wifi_reset"}` tai testiasiakkaan `/raw {"cmd":"wifi_reset"}`.

## Testiasiakas

```
pip install websockets
python tools/ws_keyer.py ws://cwkeyer.local:81/
```

Kirjoita teksti ja Enter → CW. Tyhjä rivi = STOP. `/tune 5`, `/wpm 25`, `/hb off` (heartbeat-testi), `/quit`. Jos `cwkeyer.local` ei löydy Windowsilla, käytä sarjalokin IP-osoitetta.

## Testit

### PC:llä (ilman laitetta)

```
cd test
g++ -std=c++17 -Ishim -I../cwkeyer test_keyer.cpp ../cwkeyer/keyer.cpp -o test_keyer && ./test_keyer
```

26 testiä: PARIS-ajoitus, painotus, prosignit, kaiku, STOP-viive, TUNE-rajat, heartbeat, 120 s lähetysraja, avain alhaalla -raja ja rajojen lukitus. Keskeytyskoodi ajetaan simuloidulla 1 ms:n kellolla.

### Laitteella (pöytätesti, ei radiota)

| # | Testi | Hyväksytty kun |
| --- | --- | --- |
| E1 | Käynnistys: virta päälle ja pois, reset-nappi | Rele ei naksahda kertaakaan. |
| E2 | Lepotila | Rele ei vedä eikä surise, NO–COM auki. |
| E3 | `CQ TEST` 20 WPM | Kaiku näkyy, rele vetää pisteiden ja viivojen ajan. |
| E4 | Tyhjä rivi kesken lähetyksen | Rele päästää heti, `stopped host`. |
| E5 | `/tune 30` | Rele päästää 10 s:n kohdalla. |
| E6 | Pitkä teksti, sitten `/hb off` | `fault HEARTBEAT_LOST` noin 3 s:n päästä. |
| E7 | Pitkä teksti, sulje testiasiakkaan ikkuna rististä | Rele päästää 1–3 s:ssa (`controller_lost` tai heartbeat). |
| E8 | Pitkä teksti, katkaise WiFi-reititin tai vie laite kantaman ulkopuolelle | Rele päästää noin 3 s:ssa. |
| E9 | Pitkä teksti, Wemosin USB irti | Rele päästää heti (relekortti saa virtansa Wemosilta). |

### Testiloki

| Päivä | Kokoonpano | Tulos |
| --- | --- | --- |
| 2026-09-17 | Wemos D1 mini, D1 → H-ohjattu relekortti (FL817C), 10k D1–GND, fw 0.1.0, `KEY_ACTIVE_LOW 0`, OTA | E1–E5 OK. Aiempi `KEY_ACTIVE_LOW 1` toimi käänteisesti (rele veti lepotilassa). |
| 2026-09-17 | sama, releen NO/COM → radion avainlinja | E6–E9 ja radiotesti: toimii suunnitellusti. **M0 hardware proto hyväksytty.** |

Radio (G90 tekokuormaan) vasta, kun E1–E5 ovat kunnossa.

## Tiedostot

| Tiedosto | Sisältö |
| --- | --- |
| `cwkeyer/config.h` | Pinnit, oletukset, turvarajat, verkko – muokkaa tätä |
| `cwkeyer/cwkeyer.ino` | WiFi, WebSocket-palvelin, komennot |
| `cwkeyer/keyer.cpp/.h` | Avainnusmoottori ja turvarajat (keskeytys) |
| `cwkeyer/feeder.h`, `morse.h` | Tekstijono, morsetaulukko, ajoitus (laitteistoriippumaton) |
| `test/` | PC-testit ja Arduino-shim |
| `tools/ws_keyer.py` | Komentorivin testiasiakas |
| `PROTOCOL.md` | JSON-viestit |
