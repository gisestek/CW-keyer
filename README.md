# CW Keyer

Tietokoneohjelma, joka tulkitsee radiosta kuuluvan sähkötyksen tekstiksi ja lähettää kirjoittamasi tekstin takaisin CW:nä, eli CW-yhteydet onnistuvat ilman omaa sähkötystaitoa.

![CW Station 0.3.0](docs/screenshot-0.3.0.png)

Radion avainnus hoituu mikrokontrollerilla (Wemos D1 mini, ESP8266), joka sulkee WiFi-käskystä radion avainlinjan kytkimellä: kokeiluun riittää tavallinen mekaaninen relekortti, mutta pysyvään asennukseen kannattaa vaihtaa reed-rele tai PhotoMOS-rele, esim. PVT412 (400 V, napaisuudeton, ei kulu – kestää myös putkiradion negatiivisen hilajännitteen).

```
radio --ääni--> PC (CW Station) --WiFi--> Wemos D1 mini --D1--> rele --> radion KEY-jakki
                                                                          tip = avain
                                                                          sleeve = maa
```

| Kansio | Sisältö |
| --- | --- |
| [`hardware/`](hardware/) | Kytkentä, osaluettelo ja laitteistotestit |
| [`firmware/cwkeyer-esp8266/`](firmware/cwkeyer-esp8266/) | Keyerin firmware, kytkentäohje ja WebSocket-protokolla |
| [`cwstation/`](cwstation/) | Ohjelma (Python + PySide6) – käyttöohje ja asennus: [`docs/cwstation.md`](docs/cwstation.md) |

**Release 0.3.0 on karkea demo**, mutta jo täysin kokeilukelpoinen: sillä on tehty oikeita QSO:ita, ja mukana ovat vesiputousnäyttö, makrot, ADIF-loki ja Wavelog-lähetys.

AGPL-3.0-or-later. Sähkötyksen tulkinta perustuu [DeepCW](https://github.com/e04/deepcw-engine)-malliin.
