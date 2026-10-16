# CW Station – moduulien väliset viestit (v1)

Vaatimus NFR-04: moduulit (RX, TX, ydin, GUI) keskustelevat vain näillä JSON-viesteillä. Nyt ne kulkevat prosessin sisäisellä väylällä (`cwstation/core/bus.py`), myöhemmin samat viestit voi välittää verkon yli.

Jokaisessa viestissä on kentät `type` ja `utc` (ISO 8601, esim. `2026-09-17T12:34:56.789Z`). Ajat `t_start`/`t_end` ovat Unix-aikaa sekunteina (UTC).

## RX-moduuli → muut

| type | Kentät | Milloin |
| --- | --- | --- |
| `rx.status` | `state` (`running`/`stopped`/`error`), `source`, `msg` | äänilähde käynnistyy, pysähtyy tai vikaantuu; `msg` = `model_missing:<polku>` jos malli puuttuu |
| `rx.level` | `rms_dbfs`, `peak_dbfs`, `tone_hz`, `warning` (`""`/`clip`/`weak`/`tone`) | noin 4 kertaa sekunnissa (FR-RX-04) |
| `rx.pending` | `text` | esikatselu muuttui (voi vielä muuttua) |
| `rx.text` | `text`, `t_start`, `t_end`, `own_tx`, `words` (`[[sana, alku, loppu], …]`), `wpm`, `tone_hz`, `delta_hz`, `station`, `snr_db`, `rst` | vahvistettu tulkinta (FR-RX-03). `own_tx: true` = oman lähetyksen sivuääni (UC13); omat ja vastaaseman merkit erotellaan merkkikohtaisesti eri viesteiksi. 0.4.0: `wpm` = lähetysnopeus (tai `null`, jos merkkejä on liian vähän), `tone_hz` = sävelkorkeus, `delta_hz` = ero omaan sivuääneen, `station` = aseman numero (0 = työskentelyn kohde, `-1` = oma sivuääni). 0.5.0: `snr_db` = signaali-kohinasuhde 500 Hz:n kaistassa ja `rst` = siitä johdettu raporttiehdotus |
| `rx.signal` | `wpm`, `tone_hz`, `delta_hz`, `own_tone_hz`, `station`, `snr_db`, `rst` | vastaaseman nopeus ja taajuus muuttui (FR-RX-09). Lähetetään vain vastaaseman riveistä, ja vain jos nopeus tai sävelkorkeus saatiin mitattua |
| `rx.spectrum` | `t0`, `dt`, `f0`, `df`, `cols` (`[[dB×2, …], …]`) | vesiputousnäytön sarakkeet, noin 10 viestiä sekunnissa (15 ms/sarake, 6,25 Hz/bin, 100–1500 Hz) |

## GUI → TX-moduuli

| type | Kentät | Merkitys |
| --- | --- | --- |
| `tx.send` | `text` | lähetettävä teksti; makromuuttujat `{MYCALL}` ym. laajennetaan TX-moduulissa |
| `tx.stop` | `reason` (`button`/`esc`/`shutdown`/…) | STOP (SR-01, SR-05) |
| `tx.set` | `wpm`?, `weight`? | nopeus ja painotus lennossa (FR-TX-04) |
| `tx.tune` | `seconds`? | TUNE: avain alhaalla viritystä varten (FR-TX-08). Oletus `keyer.tune_s`, enintään 10 s. Ei kesken lähetyksen |

## TX-moduuli ja keyer → muut

| type | Kentät | Milloin |
| --- | --- | --- |
| `tx.queued` | `text` | teksti hyväksytty keyerille (tarkat merkit, jotka kaiutetaan) |
| `tx.tuning` | `ms` | TUNE alkoi (keyer otti sen vastaan). Loppu näkyy `tx.state`-viestinä `busy: false` |
| `tx.warning` | `code` (`not_connected`/`dropped_chars`/`no_callsign`/`no_call`/`tune_busy`), `detail` | lähetystä ei tehty tai merkkejä pudotettiin. `no_call` = makro tarvitsee `{CALL}`-muuttujan, mutta vastaaseman tunnusta ei ole. `tune_busy` = TUNE pyydettiin kesken lähetyksen |
| `tx.echo` | `ch` | keyer aloitti merkin lähettämisen (FR-TX-03); myös `" "`, `"<"`, `">"` |
| `tx.state` | `busy`, `key`, `pending` | lähetys alkoi tai päättyi |
| `tx.stopped` | `reason` | jono tyhjennettiin (STOP, vika, yhteyskatkos) |
| `tx.fault` | `code` (`KEYDOWN_LIMIT`/`TX_LIMIT`/`HEARTBEAT_LOST`) | keyerin turvaraja laukesi (SR-02…SR-04) |
| `keyer.status` | `state` (`connecting`/`connected`/`disconnected`), `url`, `host`, `fw`, `version`, `simulated` | yhteyden tila. WinKeyer-laitteella (0.6.0) `fw` on `winkeyer`, `version` laitteen firmware-numero ja `url` sarjaportti |
| `keyer.config` | `cfg` | keyerin asetukset muuttuivat |
| `keyer.error` | `code`, `msg` | keyer vastasi virheellä tai toinen ohjelma otti ohjauksen (`CONTROL_LOST`). WinKeyerillä myös `PORT_ERROR` (portti ei aukea), `PORT_LOST` (portti katosi) ja `BREAKIN` (melaa käytettiin kesken lähetyksen, jolloin laite tyhjensi puskurinsa) |

## QSO ja loki (0.3.0)

| type | Kentät | Milloin |
| --- | --- | --- |
| `qso.update` | `fields` (`call`, `name`, `qth`, `gridsquare`, `rst_sent`, `rst_rcvd`, `comment`) | käynnissä olevan QSO:n kentät muuttuivat: tulkittu teksti, tunnuksen klikkaus tai käsin muokattu kenttä |
| `qso.logged` | `call`, `path` (ADIF-tiedosto), `adif` (tietue), `wavelog` (`true`/`false`) | QSO kirjoitettiin ADIF-tiedostoon (FR-CORE-04). Tämän jälkeen kentät nollataan (`qso.update` tyhjillä kentillä) |
| `wavelog.status` | `state` (`queued`/`sent`/`duplicate`/`rejected`/`error`), `pending` (jonon pituus), `call`, `msg`? | QSO lisättiin lähetysjonoon, lähti Wavelogiin, oli siellä jo (`duplicate`, poistetaan jonosta), hylättiin pysyvästi (`rejected`, siirretään tiedostoon `wavelog-rejected.jsonl`) tai lähetys epäonnistui tilapäisesti (`error`: jono säilyy ja sitä yritetään uudelleen 30 s välein) (FR-CORE-05) |
| `qrz.result` | `call`, `state` (`busy`/`ok`/`not_found`/`error`/`no_login`), `data` (QRZ:n Callsign-kentät, esim. `fname`, `name`, `addr2`, `country`, `grid`, `lat`, `lon`, `lotw`), `web` (qrz.com-sivun osoite), `image_b64`?, `subscriber`?, `msg`? | Tunnuksen QRZ.com-haun tulos tunnuspaneelille (FR-CORE-08). `busy` tulee heti haun alkaessa, välimuistista vastaus tulee suoraan |
| `update.available` | `version`, `name`, `notes` (julkaisutiedote, Markdown), `page`, `size`, `one_click`, `reason` (`source`/`platform`/`readonly`/`no_checksum`, kun `one_click` on `false`), `manual` | GitHubissa on uudempi versio (FR-CORE-10) |
| `update.none` | `manual`, `version` | käsin pyydetty tarkistus: uusin versio on jo käytössä |
| `update.error` | `msg`, `manual`, `stage` (`check`/`download`/`unpack`) | tarkistus, lataus tai purku epäonnistui |
| `update.progress` | `done`, `total` (tavuja) | lataus etenee, enintään 5 kertaa sekunnissa |
| `update.ready` | `version` | ladattu, tarkistettu ja purettu: ikkuna käynnistää apuskriptin ja sulkeutuu |
| `cq.state` | `active`, `reason` (`start`/`toggle`/`answer`/`manual`/`stop`/`no_macro`/`shutdown`) | CQ-toisto alkoi tai päättyi (FR-TX-07). `answer` = vastaanotettiin tekstiä, `manual` = operaattori lähetti itse, `stop` = STOP |

CQ-toisto lähettää makronsa tavallisena `tx.send`-viestinä, joten se näkyy muille moduuleille samoin kuin käsin kirjoitettu lähetys.

Keyerin oma protokolla (WebSocket JSON) on kuvattu tiedostossa `firmware/cwkeyer-esp8266/PROTOCOL.md`.
