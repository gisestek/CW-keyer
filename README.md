# CW Station

Versio 0.1.0 · 2026-09-17 · AGPL-3.0-or-later

Tietokoneohjelma, jolla CW-yhteydet onnistuvat ilman omaa sähkötystaitoa. [DeepCW](https://github.com/e04/deepcw-engine) tulkitsee vastaanotetun äänen tekstiksi, ja samasta ikkunasta kirjoitettu teksti lähtee radioon WiFi-keyerin kautta. Vaatimukset: `docs/CW-asema – vaatimusmäärittely.md`.

## Projektin osat

| Kansio | Sisältö |
| --- | --- |
| `cwstation/` | Ohjelma (Python + PySide6): RX, TX, ydin, GUI |
| `firmware/cwkeyer-esp8266/` | WiFi-keyerin firmware (Wemos D1 mini) ja protokolla |
| `hardware/` | Kytkentäkaaviot |
| `rx/deepcw/` | M0-kokeilun komentorivityökalut: tulkki, benchmark, vertailu |
| `docs/` | Vaatimusmäärittely, viestiskeemat (`messages.md`) |
| `packaging/` | Windows-paketointi (PyInstaller) |
| `tests/` | Automaattiset testit |
| `third_party/deepcw-engine/` | DeepCW-malli (AGPL-3.0) |

## Ensimmäisen version sisältö

| Vaatimus | Toteutus |
| --- | --- |
| FR-RX-01 äänilähteen valinta | Asetukset → Audio, valinta tallentuu |
| FR-RX-02 viive alle 2 s | Esikatselurivi päivittyy noin sekunnin välein (synteettisessä testissä mediaani 0,75 s) |
| FR-RX-03 aikaleimatut tapahtumat | `rx.text` UTC-alku- ja loppuaikoineen |
| FR-RX-04 tasomittari ja varoitukset | Tilarivi: taso, sävelkorkeus, YLIOHJAUS / heikko / sävel kaistan ulkopuolella |
| FR-TX-01 tekstin syöttö | Syöttörivi + Enter. Rivi on muokattavissa ennen lähetystä. Jonossa oleva teksti näkyy punaisena rivinä |
| FR-TX-02 keyerin ohjaus | WebSocket JSON (PROTOCOL.md), heartbeat 1 s |
| FR-TX-03 merkkikohtainen kaiku | Lähetetyt merkit ilmestyvät tekstivirtaan punaisella sitä mukaa kuin keyer ne lähettää |
| FR-TX-04 nopeus ja painotus | WPM-valitsin (lennossa), painotus asetuksissa |
| FR-TX-05 kolme makroa | F1 CQ, F2 oma tunnus, F3 73 |
| FR-CORE-01 asetukset | `%APPDATA%\CWStation\settings.json` |
| FR-CORE-02 tekstiloki | `Documents\CWStation\logs\cw-YYYY-MM-DD.txt`, RX/TX-rivit UTC-aikaleimoin |
| SR-01 STOP | Aina näkyvä STOP-painike ja Esc mistä tahansa; keyer nostaa avaimen alle 3 ms:ssa |
| SR-02, SR-03 aikarajat | Keyer: avain alhaalla enintään 10,5 s, lähetys enintään 120 s ilman uutta tekstiä. Asetuksissa voi laskea |
| SR-04 yhteyskatkos tai kaatuminen | Keyer pysähtyy 3 s:ssa, jos ohjelmasta ei kuulu mitään, ja heti, jos yhteys katkeaa |
| SR-05 käynnistys ja sulkeminen | Yhteyden avautuessa lähetetään STOP. Ikkunan sulkeminen lähettää STOPin ennen kuin ohjelma sulkeutuu |
| SR-07 tilan näyttö | TX/RX-lamppu, keyerin yhteystila. Simulaattoritilassa keltainen varoituspalkki |
| NFR-08 kieli | Englanti; kielitiedostot `cwstation/i18n/*.json` |

Automaattiset testit (`tests/`, 20 kpl) kattavat mm. STOP-painikkeen, Escin syöttörivillä, F1-makron, ikkunan sulkemisen kesken lähetyksen, yhteyskatkoksen, tekstilokin rivityksen ja RX-tulkinnan WAV-tiedostosta.

## Rakentaminen (kehityskone, Windows)

Tarvitaan Python 3.12 (python.org) ja internet-yhteys. Projektikansiossa:

```
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

Skripti tekee seuraavat, 5–15 min:

1. Luo `.venv-build`-ympäristön ja asentaa riippuvuudet.
2. Ajaa testit.
3. Rakentaa ohjelman PyInstallerilla.
4. Ajaa valmiin ohjelman itsetestin: ikkuna näkyy noin 15 s, ja testi tarkistaa, että tulkinta ja lähetys toimivat.
5. Pakkaa tuloksen tiedostoksi `dist\CWStation-0.1.0-win64.zip`.

Vaihtoehto: GitHub Actions (`.github/workflows/build-windows.yml`) rakentaa saman zipin, kun repositorio on GitHubissa.

## Asennus radiokoneelle

1. Kopioi `CWStation-0.1.0-win64.zip` radiokoneelle ja pura se esimerkiksi kansioon `C:\CWStation`. Pythonia ei tarvita.
2. Käynnistä `CWStation\CWStation.exe`.
   - Windows SmartScreen voi varoittaa allekirjoittamattomasta ohjelmasta: *Lisätietoja → Suorita silti*.
   - Windowsin palomuuri voi kysyä verkkolupaa. Salli yksityiset verkot, jotta yhteys keyeriin toimii.
3. Avaa **CW Station → Settings…**:
   - **Station:** oma tunnus (tarvitaan makroihin), nimi, QTH, lokaattori.
   - **Audio:** DigiRigin äänitulo, yleensä *USB PnP Sound Device (MME)*. Jos taso tai ääni ei toimi, kokeile saman laitteen *Windows WASAPI*- tai *DirectSound*-versiota.
   - **Keyer:** osoite `ws://cwkeyer.local:81/`. Jos nimi ei löydy, käytä keyerin IP-osoitetta, esim. `ws://192.168.1.50:81/`.
4. Keyerin tilan pitää muuttua vihreäksi (*Keyer: connected*), ja tilarivillä pitää näkyä äänitaso.

## Käyttöönottotesti asemalla

Tee testit järjestyksessä. Radio tekokuormaan pienellä teholla, kunnes kohdat 1–8 ovat kunnossa.

| # | Testi | Hyväksytty kun |
| --- | --- | --- |
| 1 | Käynnistys | Keyer yhdistyy, rele ei naksahda, TX-lamppu harmaa |
| 2 | Äänitaso | CW:n aikana taso noin −30…−10 dBFS, ei YLIOHJAUS-varoitusta, sävel 400–1200 Hz |
| 3 | Kuuntelu (UC12) | Bändin CW näkyy mustana tekstinä UTC-aikaleimoin. Esikatselu (harmaa) päivittyy noin sekunnin välein |
| 4 | Lähetys | Kirjoita `TEST` ja paina Enter: punainen teksti ilmestyy merkki kerrallaan, TX-lamppu palaa, radio lähettää |
| 5 | Makrot | F1, F2 ja F3 lähettävät oikean tekstin omalla tunnuksella |
| 6 | STOP | Pitkä teksti, sitten STOP-painike ja uudelleen Esc syöttörivillä: lähetys katkeaa heti |
| 7 | Nopeus | WPM-valitsimen muutos kuuluu lähetyksessä 1–2 merkin viiveellä |
| 8 | Sulkeminen | Pitkä teksti ja ikkunan sulkeminen rististä: lähetys katkeaa heti |
| 9 | Yhteyskatkos | Pitkä teksti ja keyerin tai reitittimen virrat pois: lähetys katkeaa noin 3 s:ssa |
| 10 | Tekstiloki | *CW Station → Open log folder*: päivän tiedostossa RX- ja TX-rivit aikaleimoin |
| 11 | Kokonainen QSO (M1) | Yhteys tekokuormaan ja sitten ilmaan ilman muita ohjelmia |

Ongelmatilanteissa ohjelman loki on `%APPDATA%\CWStation\cwstation.log`.

## Tiedossa olevat rajoitukset (0.1.0)

- **Kaista:** tulkki käsittelee koko 400–1200 Hz:n kaistan. Useampi signaali samassa kaistassa sotkee tulkinnan, joten käytä kapeaa CW-suodinta. Signaalin valinta (FR-RX-07) tulee myöhemmin.
- **Oma sivuääni:** jos radio vie sivuäänen kuulokelähtöön, oma lähetys näkyy myös RX-tekstinä. Siitä on hyötyä lähetyksen tarkistukseen (UC13), mutta automaattista vertailua ei vielä ole.
- **Makrot:** makrojen tekstiä voi muuttaa vain `settings.json`-tiedostossa (muokattavat makrot ovat P2).
- **TUNE:** puuttuu (P2). Firmware tukee sitä jo.
- **Laitteistoinen aikaraja:** keyerin laitteistoinen aikarajapiiri puuttuu vielä. Jumittuneen ESP:n varmistuksena on vain sen oma watchdog.

## Kehittäjälle

```
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python -m cwstation --sim-keyer --wav oma_aanite.wav  # ilman radiota ja keyeriä
python -m pytest -q tests
python -m cwstation.tx.keyer_sim --port 8181          # erillinen keyer-simulaattori
```

- `--sim-keyer` käyttää sisäänrakennettua keyer-simulaattoria. Mitään ei avainneta, ja ikkunassa näkyy keltainen varoituspalkki.
- `--wav` käyttää tiedostoa äänikortin sijaan (toistetaan silmukkana reaaliajassa).
- `--selftest 15` ajaa automaattisen savutestin.
