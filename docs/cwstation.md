# CW Station – ohjelman käyttöohje

Versio 0.3.0 · 2026-09-17 · AGPL-3.0-or-later

Tietokoneohjelma, jolla CW-yhteydet onnistuvat ilman omaa sähkötystaitoa. [DeepCW](https://github.com/e04/deepcw-engine) tulkitsee vastaanotetun äänen tekstiksi, ja samasta ikkunasta kirjoitettu teksti lähtee radioon WiFi-keyerin kautta. Vaatimukset: `CW-asema – vaatimusmäärittely.md`.

![CW Station 0.3.0](screenshot-0.3.0.png)

## Projektin osat

| Kansio | Sisältö |
| --- | --- |
| `cwstation/` | Ohjelma (Python + PySide6): RX, TX, ydin, GUI |
| `firmware/cwkeyer-esp8266/` | WiFi-keyerin firmware (Wemos D1 mini) ja protokolla |
| `hardware/` | Kytkentäkaaviot |
| `rx/deepcw/` | M0-kokeilun komentorivityökalut: tulkki, benchmark, vertailu |
| `docs/` | Vaatimusmäärittely, tämä käyttöohje, viestiskeemat (`messages.md`) |
| `packaging/` | Windows-paketointi (PyInstaller) |
| `tests/` | Automaattiset testit |
| `third_party/deepcw-engine/` | DeepCW-malli (AGPL-3.0) |

## Uutta versiossa 0.3.0

- **QSO-ikkuna ja ADIF-loki:** *Log QSO* (Ctrl+L) avaa yhteenvedon, jossa kentät voi tarkistaa ennen tallennusta. Yhteys kirjoittuu ADIF-tiedostoon (oletus `Documents\CWStation\logs\cwstation.adi`, vaihdettavissa asetuksista).
- **Kenttien poiminta tekstistä:** ohjelma lukee vastaaseman tulkitusta tekstistä tunnuksen, RST:n (`RST 599` / `UR 579`), nimen (`NAME PEKKA` / `OP PEKKA`) ja QTH:n sekä lokaattorin. Oma lähetys jätetään huomiotta, paitsi että lähettämäsi RST tallentuu `RST_SENT`-kenttään. Poimitut kentät näkyvät työkalurivin alla ja niitä voi muokata.
- **Tunnusten tunnistus ja klikkaus:** tekstivirran tunnukset ovat linkkejä. Klikkaus asettaa tunnuksen nykyiseksi vastaasemaksi, jolloin `{CALL}`-makro ja loki käyttävät sitä.
- **Taajuus ja bändi:** työkalurivin taajuuskenttä (MHz) ratkaisee bändin automaattisesti (`FREQ` ja `BAND` ADIF-tietueeseen). Taajuus tallentuu asetuksiin, joten se säilyy käynnistysten yli.
- **Wavelog:** tallennettu QSO lähtee samalla Wavelogin API:in (`POST <url>/api/qso`). Asetuksissa on URL, API-avain, `station_profile_id` ja *Test connection*. Jos verkko tai palvelin ei vastaa, QSO jää jonoon (`%APPDATA%\CWStation\wavelog-queue.jsonl`) ja lähtee automaattisesti uudelleen 30 s välein. Tilarivi näyttää jonon pituuden.
- **CQ-toisto:** *CQ*-painike toistaa CQ-makroa valitulla välillä (oletus 8 s), kunnes vastaasema vastaa, painat STOPia tai kytket toiston pois.
- **Muokattavat makrot F1–F6:** asetusten *Macros*-välilehdellä. Makroissa toimivat `{MYCALL}`, `{CALL}`, `{NAME}`, `{QTH}`, `{RST}`, `{RSTR}`, `{MYNAME}`, `{MYQTH}`, `{MYLOC}`.

## Uutta versiossa 0.2.0

- **Vesiputous** DeepCW:n tapaan tekstivirran yläpuolella:
  - Aika kulkee vasemmalta oikealle ja taajuus 100–1500 Hz alhaalta ylös.
  - Katkoviivat rajaavat tulkin kaistan 400–1200 Hz.
  - Punainen palkki alareunassa näyttää omat lähetykset, joten näkee, kuka lähettää ja milloin.
  - Ikkunan pituus valitaan yläpalkista (6, 12, 18 tai 30 s). Vesiputouksen ja tekstin välistä rajaa voi vetää.
- **Oma lähetys yhdellä rivillä:** lähetyksen aikana TX-teksti pysyy yhdellä rivillä. Vastaanottimen tulkitsema oma sivuääni kirjoittuu harmaana `ref`-rivinä suoraan sen alle, eikä sekoitu vastaaseman tekstiin.
  - Omat ja vastaaseman merkit erotellaan merkkikohtaisesti. Näin ne erottuvat, vaikka vastaasema aloittaisi heti oman K:n jälkeen.
  - Lähetyksen alussa myöhässä tulkittu vastaaseman teksti lisätään edelliselle RX-riville TX-rivin yläpuolelle.
- **Nopeampi lopullinen teksti lähetyksen loputtua:** kun signaali loppuu, viimeinen sana vahvistetaan noin 1–2 s:ssa. Aiemmin se odotti sanaväliä tai jopa 20 s.
- **Tekstiloki:** oman lähetyksen sivuääni kirjoitetaan `REF`-riviksi TX-rivin perään.
- **Kehittäjätila:** `--sim-keyer` simuloi nyt myös radion äänen, eli kohinan ja keyer-simulaattorin sivuäänen, joten vesiputousta ja ref-riviä voi kokeilla ilman radiota.

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
| FR-TX-05 kolme makroa | F1 CQ, F2 oma tunnus, F3 73 (0.3.0: myös F4 vastaus, F5 raportti, F6 QSL) |
| FR-TX-06 muokattavat makrot (0.3.0) | Asetukset → Macros: F1–F6, teksti ja painikkeen nimi |
| FR-TX-07 CQ-toisto (0.3.0) | CQ-painike toistaa CQ-makroa, väli asetuksissa; pysähtyy vastaukseen tai STOPiin |
| FR-CORE-01 asetukset | `%APPDATA%\CWStation\settings.json` |
| FR-CORE-02 tekstiloki | `Documents\CWStation\logs\cw-YYYY-MM-DD.txt`, RX/TX-rivit UTC-aikaleimoin |
| FR-CORE-03 QSO-kentät (0.3.0) | Tunnus, RST, nimi, QTH ja lokaattori poimitaan tekstistä; kenttäpalkissa muokattavissa |
| FR-CORE-04 ADIF-loki (0.3.0) | *Log QSO* (Ctrl+L) → ADIF 3.1.4 -tietue tiedostoon `cwstation.adi` |
| FR-CORE-05 Wavelog (0.3.0) | `POST <url>/api/qso`, uudelleenyritys jonosta 30 s välein |
| FR-CORE-06 tunnusten tunnistus (0.3.0) | Tekstivirran tunnukset ovat linkkejä; klikkaus asettaa vastaaseman |
| SR-01 STOP | Aina näkyvä STOP-painike ja Esc mistä tahansa; keyer nostaa avaimen alle 3 ms:ssa |
| SR-02, SR-03 aikarajat | Keyer: avain alhaalla enintään 10,5 s, lähetys enintään 120 s ilman uutta tekstiä. Asetuksissa voi laskea |
| SR-04 yhteyskatkos tai kaatuminen | Keyer pysähtyy 3 s:ssa, jos ohjelmasta ei kuulu mitään, ja heti, jos yhteys katkeaa |
| SR-05 käynnistys ja sulkeminen | Yhteyden avautuessa lähetetään STOP. Ikkunan sulkeminen lähettää STOPin ennen kuin ohjelma sulkeutuu |
| SR-07 tilan näyttö | TX/RX-lamppu, keyerin yhteystila. Simulaattoritilassa keltainen varoituspalkki |
| NFR-08 kieli | Englanti; kielitiedostot `cwstation/i18n/*.json` |
| Vesiputous (0.2.0) | 100–1500 Hz, tulkin kaista ja omat lähetykset merkittyinä |
| UC13 oman lähetyksen viite (0.2.0) | `ref`-rivi TX-rivin alla näytöllä ja `REF`-rivi lokissa. Automaattinen vertailu ja varoitus puuttuvat vielä |

Automaattiset testit (`tests/`, 41 kpl) kattavat mm. STOP-painikkeen, Escin syöttörivillä, F1-makron, ikkunan sulkemisen kesken lähetyksen, yhteyskatkoksen, tekstilokin rivityksen, RX-tulkinnan WAV-tiedostosta, ref-rivin sijoittelun, omien ja vastaaseman merkkien erottelun, vesiputousdatan sekä 0.3.0:n osalta ADIF-muotoilun ja bänditaulukon, tunnusten tunnistuksen, kenttien poiminnan tekstistä, CQ-toiston ja Wavelog-lähetyksen (paikallinen testipalvelin, myös virhetilanne ja jono).

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
5. Pakkaa tuloksen tiedostoksi `dist\CWStation-0.3.0-win64.zip`.

Vaihtoehto: GitHub Actions rakentaa saman zipin. Siirrä `packaging/github-build-windows.yml` polkuun `.github/workflows/build-windows.yml` ja pushaa GitHubiin; rakennus käynnistyy Actions-välilehdeltä (*Run workflow*) tai `v*`-tagista.

## Asennus radiokoneelle

1. Kopioi `CWStation-0.3.0-win64.zip` radiokoneelle ja pura se esimerkiksi kansioon `C:\CWStation`. Pythonia ei tarvita.
2. Käynnistä `CWStation\CWStation.exe`.
   - Windows SmartScreen voi varoittaa allekirjoittamattomasta ohjelmasta: *Lisätietoja → Suorita silti*.
   - Windowsin palomuuri voi kysyä verkkolupaa. Salli yksityiset verkot, jotta yhteys keyeriin toimii.
3. Avaa **CW Station → Settings…**:
   - **Station:** oma tunnus (tarvitaan makroihin), nimi, QTH, lokaattori.
   - **Audio:** DigiRigin äänitulo, yleensä *USB PnP Sound Device (MME)*. Jos taso tai ääni ei toimi, kokeile saman laitteen *Windows WASAPI*- tai *DirectSound*-versiota.
   - **Keyer:** osoite `ws://cwkeyer.local:81/`. Jos nimi ei löydy, käytä keyerin IP-osoitetta, esim. `ws://192.168.1.50:81/`.
   - **QSO (0.3.0):** ADIF-tiedoston polku (tyhjä = `Documents\CWStation\logs\cwstation.adi`), teho watteina ja CQ-toiston väli.
   - **Wavelog (0.3.0):** rasti *Enabled*, palvelimen osoite ilman `/api`-osaa (esim. `https://wavelog.example.com`), API-avain ja `station_profile_id` (Wavelogissa *Station Locations* -sivulla). Paina *Test connection*: se lähettää yhden testi-QSO:n tunnuksella `TEST`. Poista testitietue Wavelogista jälkeenpäin.
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
| 12 | Vesiputous (0.2.0) | Bändin signaalit näkyvät viivoina oikealla sävelkorkeudella. Oman lähetyksen aikana alareunassa on punainen palkki |
| 13 | Ref-rivi (0.2.0) | Lähetyksen aikana TX-rivi pysyy yhtenäisenä, ja harmaa `ref`-rivi sen alla näyttää, miten oma sivuääni tulkittiin |
| 14 | Tunnuksen klikkaus (0.3.0) | Tekstivirran tunnuksen klikkaus siirtää sen *Call*-kenttään, ja F4 lähettää `<tunnus> DE <oma tunnus>` |
| 15 | Kenttien poiminta (0.3.0) | Vastaaseman `RST 599 NAME PEKKA QTH OULU` täyttää kentät ilman käsityötä |
| 16 | ADIF (0.3.0) | Taajuus työkaluriville, *Log QSO* → Ctrl+L, tarkista bändi ja paina *Log*. `cwstation.adi` sisältää tietueen, jonka esim. Wavelog tai LoTW-työkalu lukee |
| 17 | Wavelog (0.3.0) | Tallennettu QSO näkyy Wavelogissa muutamassa sekunnissa. Katkaise verkko, tallenna QSO, kytke verkko: QSO lähtee itsestään noin 30 s:ssa ja tilarivin jono tyhjenee |
| 18 | CQ-toisto (0.3.0) | CQ-painike toistaa makroa. Painikkeen napsautus uudelleen, STOP tai vastaaseman vastaus lopettaa toiston |

Ongelmatilanteissa ohjelman loki on `%APPDATA%\CWStation\cwstation.log`.

## Tiedossa olevat rajoitukset (0.3.0)

- **Kaista:** tulkki käsittelee koko 400–1200 Hz:n kaistan. Useampi signaali samassa kaistassa sotkee tulkinnan, joten käytä kapeaa CW-suodinta. Signaalin valinta (FR-RX-07) tulee myöhemmin.
- **Oma sivuääni:** oma sivuääni näkyy `ref`-rivinä. Ohjelma ei vielä vertaa sitä lähetettyyn tekstiin eikä varoita eroista (UC13, P2). Jos radio ei vie sivuääntä kuulokelähtöön, ref-riviä ei tule.
- **Taajuus:** ohjelma ei lue taajuutta radiosta (CAT puuttuu), vaan taajuus kirjoitetaan työkalurivin kenttään käsin. Bändi päätellään siitä.
- **Kenttien poiminta:** poiminta perustuu tavallisiin CW-lyhenteisiin (`RST`, `UR`, `NAME`, `OP`, `QTH`). Tulkintavirhe tai poikkeava sanajärjestys jää huomaamatta, joten tarkista kentät ennen tallennusta.
- **Wavelog:** vain QSO:n lähetys. Ohjelma ei lue lokia takaisin eikä tarkista, onko asema jo työskennelty (ei *worked before* -tietoa).
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

- `--sim-keyer` käyttää sisäänrakennettua keyer-simulaattoria ja simuloitua radioääntä (kohina ja sivuääni 600 Hz). Mitään ei avainneta, ja ikkunassa näkyy keltainen varoituspalkki.
- `--wav` käyttää tiedostoa äänikortin sijaan (toistetaan silmukkana reaaliajassa). Yhdessä `--sim-keyer`in kanssa tiedosto sekoitetaan simuloituun sivuääneen, joten sillä voi harjoitella QSO:ta.
- `--selftest 15` ajaa automaattisen savutestin.
