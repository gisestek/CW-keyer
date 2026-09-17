# Keyer-protokolla v1 (WebSocket JSON)

TX-moduulin ja keyer-laitteen välinen rajapinta (NFR-04). Sama protokolla on tarkoitettu myöhemmälle ESP32-S3-levylle.

- Yhteys: `ws://cwkeyer.local:81/` (tai laitteen IP). Varatukiasematilassa `ws://192.168.4.1:81/`.
- Jokainen viesti on yksi JSON-olio tekstikehyksessä. Isäntä → keyer: kenttä `cmd`. Keyer → isäntä: kenttä `ev`.
- Merkistö: CW-teksti ASCII (NFR-08). Tukemattomat merkit ohitetaan hiljaa.

## Ohjaus ja turvallisuus

- Useita asiakkaita voi olla yhteydessä, mutta vain yksi **ohjaa**. Ohjaajaksi tullaan komennolla `hello`. Uusi `hello` ottaa ohjauksen; jos lähetys on käynnissä, se pysäytetään ja edellinen ohjaaja saa `control`-viestin.
- `stop`, `ping`, `status` ja `hello` hyväksytään keneltä tahansa. Muut komennot vain ohjaajalta (`NOT_CONTROLLER`).
- **Heartbeat (SR-04):** ohjaajan on lähetettävä jokin viesti (esim. `ping`) vähintään `heartbeat_ms`-välein, kun lähetys on käynnissä. Muuten keyer pysäyttää lähetyksen (`HEARTBEAT_LOST`). Suositus: `ping` kerran sekunnissa aina yhteyden ollessa auki.
- **Ohjaajan yhteys katkeaa** → lähetys pysähtyy (`controller_lost`).
- Turvarajat valvotaan 1 ms:n laitteistokeskeytyksessä. Isäntä voi laskea rajoja `set`-komennolla, mutta ei nostaa yli firmwaren `config.h`-arvojen.

| Raja | Oletus / yläraja | Alaraja | Vaatimus |
| --- | --- | --- | --- |
| `keydown_max_ms` avain yhtäjaksoisesti alhaalla | 10 500 ms | 1 000 ms | SR-02 |
| `tune_max_ms` TUNE-kesto | 10 000 ms | 500 ms | FR-TX-08 |
| `tx_max_ms` lähetys ilman uutta `send`/`tune`-komentoa | 120 000 ms | 10 000 ms | SR-03 |
| `heartbeat_ms` ohjaajan hiljaisuus lähetyksen aikana | 3 000 ms | 500 ms | SR-04 |

## Komennot (isäntä → keyer)

| `cmd` | Kentät | Vastaus |
| --- | --- | --- |
| `hello` | `client` (vapaa teksti) | `hello` |
| `send` | `text` | `queued`; jos jono täynnä, lisäksi `error` `QUEUE_FULL` |
| `stop` | – | `stopped` (`reason: "host"`) kaikille |
| `tune` | `ms` | ei vastausta onnistuessa (`state` busy → true); `error` `BUSY`, jos lähetys käynnissä |
| `set` | mikä tahansa yhdistelmä: `wpm`, `weight`, `keydown_max_ms`, `tune_max_ms`, `tx_max_ms`, `heartbeat_ms` | `config` kaikille |
| `ping` | `t` (vapaa luku) | `pong` samalla `t`:llä |
| `status` | – | `state` |
| `wifi_reset` | – | tyhjentää WiFi-asetukset ja käynnistää uudelleen (varatukiasema aukeaa) |

Tekstin erikoismerkinnät:

- Välilyönti = sanaväli (7 yksikköä).
- `<SK>`, `<AR>`, `<BT>`, `<KN>`… = prosign: kulmasulkeiden sisällä kirjaimet lähetetään ilman merkkiväliä.
- Tuetut merkit: A–Z, 0–9, `. , ? / = + - ( ) " ' : ; @ !`

## Tapahtumat (keyer → isäntä)

| `ev` | Kentät | Milloin |
| --- | --- | --- |
| `hello` | `fw`, `version`, `proto`, `caps[]`, `controller` (bool), `cfg{}` | yhteyden avautuessa ja `hello`-komentoon |
| `queued` | `accepted`, `pending` | `send`-komennon jälkeen |
| `echo` | `ch` | merkin ensimmäinen elementti alkaa (FR-TX-03). Myös `" "`, `"<"`, `">"` |
| `state` | `busy`, `key`, `pending`, `controller` | lähetys alkaa tai päättyy, ja `status`-komentoon |
| `stopped` | `reason`: `host`, `controller_lost`, `controller_changed`, `ota`, `wifi_reset`, `KEYDOWN_LIMIT`, `TX_LIMIT`, `HEARTBEAT_LOST` | aina kun jono tyhjennetään pakolla |
| `fault` | `code`: `KEYDOWN_LIMIT`, `TX_LIMIT`, `HEARTBEAT_LOST` | turvaraja laukesi (seuraa aina `stopped`) |
| `config` | `cfg{}` | `set`-komennon jälkeen |
| `control` | `owner: false` | toinen asiakas otti ohjauksen |
| `pong` | `t` | `ping`-komentoon |
| `error` | `code`, `msg` | `BAD_JSON`, `NOT_CONTROLLER`, `QUEUE_FULL`, `BUSY`, `UNKNOWN_CMD`, `RESTARTING` |

`cfg` = `{"wpm", "weight", "keydown_max_ms", "tune_max_ms", "tx_max_ms", "heartbeat_ms"}`

## Esimerkki

```
→ {"cmd":"hello","client":"cw-asema"}
← {"ev":"hello","fw":"cwkeyer-esp8266","version":"0.1.0","proto":1,"caps":["cw","tune","echo"],"controller":true,"cfg":{"wpm":20,"weight":50,"keydown_max_ms":10500,"tune_max_ms":10000,"tx_max_ms":120000,"heartbeat_ms":3000}}
→ {"cmd":"set","wpm":22}
← {"ev":"config","cfg":{"wpm":22, ...}}
→ {"cmd":"send","text":"CQ DE OH0XX K"}
← {"ev":"queued","accepted":13,"pending":13}
← {"ev":"state","busy":true,"key":true,"pending":12,"controller":0}
← {"ev":"echo","ch":"C"}
← {"ev":"echo","ch":"Q"}
→ {"cmd":"ping","t":1726570000123}
← {"ev":"pong","t":1726570000123}
...
← {"ev":"state","busy":false,"key":false,"pending":0,"controller":0}
```

## Ajoitus

- PARIS-standardi: yksikkö = 1200 / WPM ms. Piste 1, viiva 3, elementtiväli 1, merkkiväli 3, sanaväli 7 yksikköä.
- Painotus `weight` 25–75 (50 = normaali) siirtää aikaa avaimen alhaalla- ja ylhäälläolon välillä; elementin kokonaispituus ei muutu.
- Teksti muunnetaan elementeiksi vasta juuri ennen lähetystä, joten `wpm`-muutos vaikuttaa heti jonossa oleviin merkkeihin (noin 1–2 merkin viiveellä).
