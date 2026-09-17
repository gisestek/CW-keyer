# CW Station – moduulien väliset viestit (v1)

Vaatimus NFR-04: moduulit (RX, TX, ydin, GUI) keskustelevat vain näillä JSON-viesteillä. Nyt ne kulkevat prosessin sisäisellä väylällä (`cwstation/core/bus.py`), myöhemmin samat viestit voi välittää verkon yli.

Jokaisessa viestissä on kentät `type` ja `utc` (ISO 8601, esim. `2026-09-17T12:34:56.789Z`). Ajat `t_start`/`t_end` ovat Unix-aikaa sekunteina (UTC).

## RX-moduuli → muut

| type | Kentät | Milloin |
| --- | --- | --- |
| `rx.status` | `state` (`running`/`stopped`/`error`), `source`, `msg` | äänilähde käynnistyy, pysähtyy tai vikaantuu; `msg` = `model_missing:<polku>` jos malli puuttuu |
| `rx.level` | `rms_dbfs`, `peak_dbfs`, `tone_hz`, `warning` (`""`/`clip`/`weak`/`tone`) | noin 4 kertaa sekunnissa (FR-RX-04) |
| `rx.pending` | `text` | esikatselu muuttui (voi vielä muuttua) |
| `rx.text` | `text`, `t_start`, `t_end` | vahvistettu tulkinta (FR-RX-03) |

## GUI → TX-moduuli

| type | Kentät | Merkitys |
| --- | --- | --- |
| `tx.send` | `text` | lähetettävä teksti; makromuuttujat `{MYCALL}` ym. laajennetaan TX-moduulissa |
| `tx.stop` | `reason` (`button`/`esc`/`shutdown`/…) | STOP (SR-01, SR-05) |
| `tx.set` | `wpm`?, `weight`? | nopeus ja painotus lennossa (FR-TX-04) |

## TX-moduuli ja keyer → muut

| type | Kentät | Milloin |
| --- | --- | --- |
| `tx.queued` | `text` | teksti hyväksytty keyerille (tarkat merkit, jotka kaiutetaan) |
| `tx.warning` | `code` (`not_connected`/`dropped_chars`/`no_callsign`), `detail` | lähetystä ei tehty tai merkkejä pudotettiin |
| `tx.echo` | `ch` | keyer aloitti merkin lähettämisen (FR-TX-03); myös `" "`, `"<"`, `">"` |
| `tx.state` | `busy`, `key`, `pending` | lähetys alkoi tai päättyi |
| `tx.stopped` | `reason` | jono tyhjennettiin (STOP, vika, yhteyskatkos) |
| `tx.fault` | `code` (`KEYDOWN_LIMIT`/`TX_LIMIT`/`HEARTBEAT_LOST`) | keyerin turvaraja laukesi (SR-02…SR-04) |
| `keyer.status` | `state` (`connecting`/`connected`/`disconnected`), `url`, `host`, `fw`, `version`, `simulated` | yhteyden tila |
| `keyer.config` | `cfg` | keyerin asetukset muuttuivat |
| `keyer.error` | `code`, `msg` | keyer vastasi virheellä tai toinen ohjelma otti ohjauksen (`CONTROL_LOST`) |

Keyerin oma protokolla (WebSocket JSON) on kuvattu tiedostossa `firmware/cwkeyer-esp8266/PROTOCOL.md`.
