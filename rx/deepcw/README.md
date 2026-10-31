# rx/deepcw – DeepCW reaaliajassa (M0-kokeilu)

Versio 0.1 · 2026-09-17 · AGPL-3.0-or-later

M0-kokeilu vaatimusmäärittelystä: *DeepCW reaaliajassa DigiRigiltä. Sama äänite tulkkautuu vähintään Morse Expertin tasoisesti.*

Tämä kansio sisältää komentorivin tulkin, joka lukee äänikorttia (tai WAV-tiedostoa), ajaa [DeepCW-mallin](https://github.com/e04/deepcw-engine) paikallisesti ja tulostaa tekstin UTC-aikaleimoin. Siitä tulee myöhemmin RX-moduulin perusta.

## Tulokset synteettisellä CW:llä (pilvikone, 2 vCPU)

Ennen oikeita äänitteitä striimaava tulkki ajettiin 140 minuutin synteettisen QSO-tekstin läpi (`benchmark.py`, raaka tulos `benchmark-2026-09-17.txt`). Kohina on valkoista, SNR 2500 Hz:n kaistassa.

| Olosuhde | CER, SNR ≥ −6 dB | CER, −9 dB | CER, −12 dB |
| --- | --- | --- | --- |
| Tasainen signaali, tarkka ajoitus, 12–32 WPM | 0,0 % | 0,0 % | 0–7 % |
| QSB 10 dB + käsiavaimen ajoitusvirhe 10 % | 0–4,5 % | 5–17 % | 22–34 % |

| Mittari | Tulos | Vaatimus |
| --- | --- | --- |
| Sana näkyy esikatselussa sanan jälkeen | mediaani 0,75 s, 90 % alle 1,85 s | FR-RX-02: < 2 s ✅ |
| Sana vahvistetaan (lopullinen teksti) | mediaani 2,1 s, 90 % alle 6 s | – |
| CPU-aika | 3,5 % äänen kestosta | NFR-03 ✅ |

- **Huom:** synteettinen kohina ei vastaa bändiä. Oikealla bändillä on QRM:ää, QRN:ää ja useita signaaleja samassa kaistassa. Varsinainen M0-hyväksyntä tehdään TS-515:n äänitteillä (alla).
- Heikoimpien signaalien viiveen pitkät p90-arvot johtuvat mittaustavasta: väärin tulkittu sana viivästää seuraavien sanojen tunnistusta vertailussa.
- "20 s palat" -sarake on vertailukohta: kiinteät palat katkeavat kesken merkkien, striimaava logiikka ei.

## DeepCW v2 -malli (2026-10-31)

Malli päivitettiin upstreamin versioon `79104fb` (v2, lisenssi MIT). Muutokset mallin käytössä:

- **Normalisointi:** spektrogrammi jaetaan ennen `log1p`:tä kohinatasolla, joka arvioidaan ikkunan magnitudien 90 %:n kvantiilista (`noise_q90_log1p`).
- **Aika-askel:** malli antaa yhden tuloskehyksen kahta spektrikehystä kohti (`output_time_stride: 2`, eli 96 näytettä = 30 ms).
- **Haamumerkit:** v2 "kuulee" puhtaasta kohinasta joskus lyhyen kirjaimen (E, I, S…). Siksi merkki pudotetaan, jos sen varmin kehys on alle 0,90 (`MIN_CHAR_CONFIDENCE`). v1:n merkit ovat aina ~1,0, joten suodatin ei muuta sen tuloksia.

Molemmat tulkit (`cwstation/rx/deepcw.py` ja tämän kansion `deepcw_decoder.py`) toimivat sekä v1- että v2-mallilla.

Vertailu ohjelman omalla striimaavalla tulkilla (`stream_benchmark.py`, pilvikone 2 vCPU, 6 tekstiä × ~100 merkkiä per rivi, 18 ja 26 WPM). Merkkivirhe (CER) %:

| Olosuhde | v1 | v2 ilman suodatinta | v2, 0,80 | **v2, 0,90** | v2, 0,95 |
| --- | --- | --- | --- | --- | --- |
| Tasainen, ≥ −9 dB | 0–0,3 | 0 | 0 | **0** | 0–0,3 |
| Tasainen, −12 dB | 4,8 | 1,7 | 2,1 | **2,4** | 2,8 |
| Tasainen, −15 dB | 51,4 | 14,5 | 27,9 | **36,6** | 43,8 |
| QSB 10 dB + käsiavain 10 %, −6 dB | 1,7 | 2,4 | 2,8 | **3,4** | 4,1 |
| QSB + käsiavain, −9 dB | 13,8 | 10,0 | 11,4 | **13,4** | 15,5 |
| QSB + käsiavain, −12 dB | 37,9 | 30,3 | 29,0 | **31,0** | 33,4 |
| QSB + käsiavain, −15 dB | 65,2 | 44,8 | 49,7 | **54,1** | 59,3 |
| Haamumerkit / min puhtaassa kohinassa | 0 | 5,6 | 0,4 | **0** | 0 |
| CPU-aika / äänen kesto | 5,6 % | 3,1 % | 2,9 % | **3,0 %** | 3,0 % |

- v2 on heikoilla signaaleilla selvästi parempi ja vie noin puolet v1:n laskenta-ajasta. Alle 2 %-yksikön erot ovat tällä otoksella kohinaa.
- Synteettinen valkoinen kohina ei vastaa bändiä (QRN, QRM). Haamumerkkien määrä ja suodatinraja kannattaa tarkistaa oikeilla äänitteillä.

## Asennus (Windows)

1. Asenna [Python 3.11 tai 3.12](https://www.python.org/downloads/) ja valitse asennuksessa *Add python.exe to PATH*.
2. Malli on valmiina kansiossa `third_party/deepcw-engine` (`model.onnx`, `model.onnx.json`, MIT-lisenssi; upstream-versio ja tarkistussummat tiedostossa `UPSTREAM`).
3. Komentokehotteessa projektikansiossa:

```
cd "rx\deepcw"
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Käyttö

```
python rx_live.py --list-devices                     # äänilaitteet
python rx_live.py --device "USB Audio"               # kuuntele DigiRigiä ja tulkitse
python rx_live.py --device 3 --record ts515_01.wav --log rx.txt --jsonl rx.jsonl
python rx_live.py --wav ts515_01.wav                 # tiedosto reaaliaikanopeudella
python rx_live.py --wav ts515_01.wav --fast --log deepcw_01.txt
```

Näytöllä:

- **Lihavoitu rivi** = vahvistettu teksti ja sen alun UTC-aika.
- **Alarivi** = tulotaso, voimakkain äänitaajuus, CPU-käyttö ja himmeänä esikatselu, joka voi vielä muuttua.
- **Varoitukset:** `YLIOHJAUS` (huippu yli −1 dBFS), `HEIKKO` (alle −50 dBFS), `SÄVEL ULKOPUOLELLA` (malli tulkitsee vain 400–1200 Hz).

`--jsonl` kirjoittaa tapahtumat `rx_start`, `rx_text` (UTC, teksti), `rx_level` ja `rx_stop` (FR-RX-03). `--log` kirjoittaa tekstilokin muodossa `aika<TAB>RX<TAB>teksti`.

## Radio ja DigiRig

- **Kytkentä:** TS-515:n kuuloke- tai kaiutinlähtö → DigiRigin äänitulo. Kytke kaapeli DigiRigin ohjeen mukaan.
- **Laite Windowsissa:** DigiRig näkyy yleensä nimellä *USB PnP Sound Device* tai *USB Audio Device*.
- **Taso:** säädä TS-515:n AF GAIN ja Windowsin äänitystaso niin, että `rx_live` näyttää CW:n aikana noin −30…−10 dBFS eikä `YLIOHJAUS`-varoitusta tule. Jos taso on liian korkea minimiasetuksillakin, lisää vaimennin tai erotusmuuntaja.
- **Kaista:** käytä kapeaa CW-suodinta, jos mahdollista. Malli tulkitsee koko 400–1200 Hz:n kaistan, joten useampi signaali samassa kaistassa häiritsee. Signaalin valinta (FR-RX-07) on vielä toteuttamatta.

## M0-koe: DeepCW vs. Morse Expert

Hyväksymiskriteeri: *sama äänite tulkkautuu vähintään Morse Expertin tasoisesti.*

1. **Äänitä 3–5 näytettä** komennolla `rx_live.py --device … --record ts515_NN.wav`, kukin 2–5 min. Hyviä kohteita ovat vahva hidas QSO, heikko tai häipyvä asema, nopea kilpailuliikenne ja käsiavaimella lähetetty CW.
2. **Morse Expert:** soita WAV tietokoneen kaiuttimesta puhelimen vieressä. Kopioi puhelimen teksti tiedostoon `me_NN.txt`.
3. **DeepCW:** `python rx_live.py --wav ts515_NN.wav --fast --log dc_NN.txt`
4. **Viiteteksti:** kirjoita `ref_NN.txt` kuuntelemalla. Apuna voi käyttää kummankin tulkin tulosta, mutta tarkista korvalla.
5. **Vertailu:** `python compare.py ref_NN.txt dc_NN.txt me_NN.txt`
6. **Kirjaa tulokset** alla olevaan taulukkoon.

| Näyte | Kuvaus | WPM | DeepCW CER | Morse Expert CER |
| --- | --- | --- | --- | --- |
| 01 | | | | |
| 02 | | | | |
| 03 | | | | |

Kokeile lisäksi livenä: viive merkin kuulumisesta esikatseluun pitäisi olla alle 2 s (FR-RX-02).

## Tiedostot

| Tiedosto | Sisältö |
| --- | --- |
| `rx_live.py` | Komentorivin tulkki: äänikortti/WAV → teksti, tasomittari, tallennus, JSONL |
| `deepcw_decoder.py` | Mallin kääre (spektrogrammi, CTC) ja striimaava dekooderi |
| `benchmark.py`, `cwgen.py` | Synteettinen CW-generaattori ja mittaukset |
| `compare.py` | CER/WER-vertailu viitetekstiin |
| `benchmark-2026-09-17.txt` | Benchmarkin raakatulos |

## Miten striimaus toimii

Striimaus mukailee DeepCW-verkkosovelluksen algoritmia:

1. Ääni muunnetaan 3200 Hz:iin (soxr) ja puskuroidaan.
2. Noin kerran sekunnissa malli tulkitsee koko puskurin (enintään 20 s). Tulos näytetään esikatseluna.
3. Teksti vahvistetaan viimeisen sanavälin kohdalta, joka on vähintään 1,25 s puskurin lopusta. Vahvistettu ääni poistetaan puskurista, mutta 1,5 s jätetään kontekstiksi. Ilman kontekstia uuden pätkän alkuun ilmestyi ylimääräisiä E-kirjaimia.
4. Jos 20 s:iin ei tule sanaväliä, koko puskuri vahvistetaan.

Mallin syöte: 3200 Hz, FFT 256, hop 48 (15 ms/kehys), 400–1200 Hz, log1p. Tuloste: CTC-todennäköisyydet 41 merkille per kehys.
