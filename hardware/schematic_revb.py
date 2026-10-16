"""CW keyer – USB-avainnusrajapinta rev B (luonnos), kaksi lähtövaihtoehtoa.
    python schematic_revb.py          -> B1 PhotoMOS:  cw-keyer-revb.svg / .png
    python schematic_revb.py reed     -> B2 ULN2803A + reed-rele: cw-keyer-revb-reed.svg / .png
Vaatii: pip install schemdraw

Muutokset rev A:han (M0-proto.md):
  * relemoduuli + JP2 -> PhotoMOS U2 CPC1025N (400 V, napaisuudeton, SOP-4)
  * 74HC132 SOIC-14, passiivit 0805, D1 BAT54 (SOT-23) -> uunijuotos
  * lisätty melajakki J2 (D2/D5) ja valinnainen sivuäänisummeri BZ1 (D4)
"""
import sys
import schemdraw
import schemdraw.elements as elm
import schemdraw.logic as logic

REED = len(sys.argv) > 1 and sys.argv[1] == 'reed'
BASE = 'cw-keyer-revb-reed' if REED else 'cw-keyer-revb'
schemdraw.config(fontsize=11, font='DejaVu Sans', lw=1.4)


def box(d, x0, y0, x1, y1, dashed=False):
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                 ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        ln = elm.Line().at(a).to(b)
        if dashed:
            ln.linestyle('--')
        d += ln


def vdd(d, p, txt='+5V'):
    d += elm.Vdd().at(p).theta(0).label(txt, loc='right', fontsize=9)


def gnd(d, p):
    d += elm.Ground().at(p).theta(0)


def pinlabel(d, p, txt, side):
    ha = 'right' if side == 'R' else 'left'
    dx = -0.15 if side == 'R' else 0.15
    d += elm.Label().at((p[0] + dx, p[1])).label(txt, halign=ha, valign='center', fontsize=10)


def wire(d, *pts, dashed=False):
    for a, b in zip(pts, pts[1:]):
        ln = elm.Line().at(a).to(b)
        if dashed:
            ln.linestyle('--')
        d += ln


with schemdraw.Drawing(file=BASE + '.svg', show=False) as d:
    d.config(unit=2.5)

    d += elm.Label().at((-8.0, 7.2)).label(
        'CW keyer – USB-avainnusrajapinta  ·  Arduino Nano + '
        + ('ULN2803A + reed-rele' if REED else 'PhotoMOS')
        + ' + laitteistoinen aikaraja  ·  rev ' + ('B2' if REED else 'B1') + ' (luonnos)  2026-09-27',
        halign='left', fontsize=14)

    # ---------------- Arduino Nano (plug-in module) ----------------
    box(d, 0, -2.5, 3.2, 5.5)
    d += elm.Label().at((1.6, 5.0)).label('A1 Arduino Nano', fontsize=12)
    d += elm.Label().at((1.6, 4.4)).label('K3NG, WinKeyer', fontsize=9)
    d += elm.Label().at((1.6, -3.0)).label('naarasrimat 2×15', fontsize=8)
    P5V, PRST, PD11, PGND = (3.2, 3.5), (3.2, 2.0), (3.2, 0.0), (3.2, -1.8)
    PUSB, PD2, PD5, PD4 = (0, 3.5), (0, 1.5), (0, 0.5), (0, -1.8)
    for p, t in ((P5V, '5V'), (PRST, 'RST'), (PD11, 'D11'), (PGND, 'GND')):
        pinlabel(d, p, t, 'R')
    for p, t in ((PUSB, 'USB'), (PD2, 'D2'), (PD5, 'D5'), (PD4, 'D4')):
        pinlabel(d, p, t, 'L')
    wire(d, PUSB, (-1.2, 3.5))
    d += elm.Label().at((-1.3, 3.5)).label('PC', halign='right', valign='center')

    # J2 paddle jack (optional)
    JPX = -6.2
    box(d, JPX, 2.2, JPX + 2.6, -0.6)
    d += elm.Label().at((JPX + 1.3, 2.6)).label('J2 3,5 mm stereo', fontsize=10)
    d += elm.Label().at((JPX + 1.3, -1.0)).label('mela (valinnainen)', fontsize=8)
    pinlabel(d, (JPX + 2.6, 1.5), 'TIP dit', 'R')
    pinlabel(d, (JPX + 2.6, 0.5), 'RING dah', 'R')
    pinlabel(d, (JPX + 2.6, -0.2), 'SLEEVE', 'R')
    wire(d, (JPX + 2.6, 1.5), PD2)
    wire(d, (JPX + 2.6, 0.5), PD5)
    wire(d, (JPX + 2.6, -0.2), (-2.0, -0.2))
    gnd(d, (-2.0, -0.2))

    # BZ1 sidetone (optional, DNP)
    wire(d, PD4, (-1.0, -1.8))
    d += elm.Resistor().at((-1.0, -1.8)).left(2.0).label('R6 100', loc='top', fontsize=9)
    wire(d, (-3.0, -1.8), (-3.0, -2.4))
    box(d, -3.35, -2.4, -2.65, -3.0)
    gnd(d, (-3.0, -3.0))
    d += elm.Label().at((-3.5, -2.7)).label('BZ1 passiivisumeri\n(sivuääni, DNP)', halign='right', valign='center', fontsize=8)

    wire(d, P5V, (4.0, 3.5))
    vdd(d, (4.0, 3.5))
    wire(d, PGND, (4.0, -1.8))
    gnd(d, (4.0, -1.8))

    # JP1 + C3
    wire(d, PRST, (4.8, 2.0))
    d += elm.Switch().at((4.8, 2.0)).right(1.4)
    d += elm.Label().at((5.5, 2.55)).label('JP1', fontsize=9)
    d += elm.Capacitor().at((6.2, 2.0)).down(1.2).label('C3 10µF', loc='bottom', fontsize=9, ofst=0.3)
    gnd(d, (6.2, 0.8))

    # ---------------- KEY net ----------------
    KEY = (7.5, 0.0)
    wire(d, PD11, KEY)
    d += elm.Dot().at(KEY)
    d += elm.Label().at((5.0, 0.3)).label('KEY (D11)', fontsize=10)
    d += elm.Resistor().at(KEY).down(2.0).label('R3 100k', loc='bottom', fontsize=10)
    gnd(d, (7.5, -2.0))

    # ---------------- RC timer ----------------
    K2 = (9.0, 0.0)
    T = (12.0, 0.0)
    wire(d, KEY, K2)
    d += elm.Dot().at(K2)
    d += elm.Resistor().at(K2).to(T).label('R1 150k', loc='bottom', fontsize=10)
    d += elm.Dot().at(T)
    d += elm.Label().at((12.3, 0.35)).label('T', fontsize=10)
    d += elm.Capacitor(polar=True).at(T).down(2.0).label('C1 100µF', loc='bottom', fontsize=10)
    gnd(d, (12.0, -2.0))
    wire(d, K2, (9.0, 1.5))
    d += elm.Resistor().at((9.0, 1.5)).to((10.5, 1.5)).label('R2 330', loc='top', fontsize=10)
    d += elm.Diode().at((12.0, 1.5)).to((10.5, 1.5)).label('D1 BAT54', loc='top', fontsize=10)
    wire(d, (12.0, 1.5), T)

    # ---------------- 74HC132 ----------------
    ua = logic.SchmittNand(inputs=2).right().anchor('in1').at((15.0, 0.25))
    d += ua
    d += elm.Label().at((15.9, 1.0)).label('U1A', fontsize=10)
    TIN = (14.3, 0.0)
    wire(d, T, TIN, (14.3, 0.25), ua.in1)
    wire(d, TIN, (14.3, -0.25), ua.in2)
    d += elm.Dot().at(TIN)
    NTO = (17.6, ua.out[1])
    wire(d, ua.out, NTO)
    d += elm.Dot().at(NTO)
    d += elm.Label().at((17.6, 0.3)).label('/TO', fontsize=10)

    ub = logic.SchmittNand(inputs=2).right().anchor('in2').at((19.2, NTO[1]))
    d += ub
    d += elm.Label().at((20.4, 1.05)).label('U1B', fontsize=10)
    wire(d, NTO, ub.in2)
    TOPY = 3.8
    wire(d, KEY, (7.5, TOPY), (18.6, TOPY), (18.6, ub.in1[1]), ub.in1)
    NKEY = (21.8, ub.out[1])
    wire(d, ub.out, NKEY)
    d += elm.Label().at((21.8, 0.75)).label('/KEY', fontsize=10)

    uc = logic.SchmittNand(inputs=2).right().anchor('in1').at((23.2, NKEY[1] + 0.25))
    d += uc
    d += elm.Label().at((24.1, 1.05)).label('U1C', fontsize=10)
    CJ = (22.6, NKEY[1])
    wire(d, NKEY, CJ, (22.6, uc.in1[1]), uc.in1)
    wire(d, CJ, (22.6, uc.in2[1]), uc.in2)
    d += elm.Dot().at(CJ)
    KS = (26.2, uc.out[1])
    wire(d, uc.out, KS)
    d += elm.Label().at((26.0, 0.75)).label('KEY_SAFE', fontsize=10)

    ud = logic.SchmittNand(inputs=2).right().anchor('in1').at((19.2, -2.75))
    d += ud
    d += elm.Label().at((20.1, -2.0)).label('U1D', fontsize=10)
    DJ = (17.6, -3.0)
    wire(d, NTO, DJ)
    d += elm.Dot().at(DJ)
    wire(d, DJ, (18.6, -3.0), (18.6, ud.in1[1]), ud.in1)
    wire(d, (18.6, -3.0), (18.6, ud.in2[1]), ud.in2)
    d += elm.Dot().at((18.6, -3.0))
    d += elm.Resistor().at(ud.out).right(2.0).label('R4 1k', loc='top', fontsize=10)
    d += elm.LED().down(1.6).label('LED1 pun.\n"TIMEOUT"', loc='bottom', fontsize=9)
    gnd(d, d.here)

    d += elm.Label().at((13.0, -6.4)).label(
        'U1 = 74HC132D (SOIC-14, Schmitt-NAND, HC eikä HCT): pin 14 → +5V, pin 7 → GND,\n'
        'C2 100 nF pinnien 14 ja 7 viereen. Pinnit kuten DIP-versiossa (A 1,2→3 · B 4,5→6 · C 9,10→8 · D 12,13→11).',
        halign='left', fontsize=9)

    if not REED:
        # ---------------- B1: PhotoMOS U2 ----------------
        RX0, RX1 = 29.2, 33.4
        box(d, RX0, 1.4, RX1, -2.6)
        d += elm.Label().at(((RX0 + RX1) / 2, 1.9)).label('U2 CPC1025N', fontsize=11)
        d += elm.Label().at(((RX0 + RX1) / 2, -3.1)).label('PhotoMOS 400 V / 120 mA, SOP-4', fontsize=8)
        A_, K_ = (RX0, KS[1]), (RX0, -1.5)
        O3, O4 = (RX1, KS[1]), (RX1, -1.5)
        pinlabel(d, A_, '1 A', 'L')
        pinlabel(d, K_, '2 K', 'L')
        pinlabel(d, O3, '4', 'R')
        pinlabel(d, O4, '3', 'R')
        d += elm.Label().at(((RX0 + RX1) / 2, -0.7)).label('LED ⇒ MOSFET-pari', fontsize=8)
        d += elm.Resistor().at(KS).to((28.6, KS[1])).label('R5 560', loc='top', fontsize=10)
        wire(d, (28.6, KS[1]), A_)
        wire(d, K_, (28.4, -1.5))
        gnd(d, (28.4, -1.5))
        TIPN, SLVN = O3, O4
        BAR = 34.6
    else:
        # ---------------- B2: ULN2803A U2 + reed relay K1 ----------------
        RX0, RX1 = 27.4, 30.2
        box(d, RX0, 1.4, RX1, -2.6)
        d += elm.Label().at(((RX0 + RX1) / 2, 1.9)).label('U2 ULN2803A', fontsize=11)
        d += elm.Label().at(((RX0 + RX1) / 2, -3.1)).label('DIP-18, kanava 1', fontsize=8)
        IN1, GNDP = (RX0, KS[1]), (RX0, -1.5)
        OUT1, COMP = (RX1, KS[1]), (RX1, -1.5)
        pinlabel(d, IN1, '1 1B', 'L')
        pinlabel(d, GNDP, '9 GND', 'L')
        pinlabel(d, OUT1, '1C 18', 'R')
        pinlabel(d, COMP, 'COM 10', 'R')
        d += elm.Label().at(((RX0 + RX1) / 2, -0.7)).label('2,7k sis.', fontsize=8)
        wire(d, KS, IN1)
        wire(d, GNDP, (26.8, -1.5))
        gnd(d, (26.8, -1.5))
        wire(d, COMP, (30.9, -1.5))
        d += elm.Label().at((31.0, -1.5)).label('+5V', halign='left', valign='center', fontsize=9)
        # coil
        CX = 32.0
        wire(d, OUT1, (CX, KS[1]))
        d += elm.Dot().at((CX, KS[1]))
        d += elm.Inductor2(loops=3).at((CX, KS[1])).up(2.6).label('K1 kela\n5 V / 500 Ω', loc='bottom', fontsize=9)
        vdd(d, (CX, KS[1] + 2.6))
        # contact (reed, vertical)
        SX = 36.0
        TIPN, SLVN = (SX, KS[1]), (SX, -1.5)
        d += elm.Switch().at(SLVN).to(TIPN)
        d += elm.Dot().at(TIPN)
        d += elm.Dot().at(SLVN)
        d += elm.Label().at((SX + 0.35, (KS[1] - 1.5) / 2)).label('K1\nreed NO', halign='left', valign='center', fontsize=9)
        wire(d, (CX + 0.6, KS[1] + 1.3), (SX - 0.5, (KS[1] - 1.5) / 2 + 0.2), dashed=True)
        box(d, CX - 1.0, KS[1] + 3.0, SX + 1.6, -2.4, dashed=True)
        d += elm.Label().at(((CX + SX) / 2, -2.85)).label('K1 SIL-reed-rele, esim. Meder SIL05-1A72-71D', fontsize=8)
        d += elm.Label().at((27.2, -3.6)).label('ULN2803A: tulot 2–8 (pinnit 2–8) → GND, lähdöt 11–17 kytkemättä', halign='left', fontsize=8)
        BAR = 34.0

    # isolation barrier
    wire(d, (BAR, 5.0), (BAR, -3.3), dashed=True)
    d += elm.Label().at((BAR, 5.4)).label('eristysraja ≥ 3 mm (ei kuparia)', fontsize=8)

    # ---------------- Output jack ----------------
    JX = 39.8
    CAPX = 38.0 if REED else 36.2
    wire(d, TIPN, (JX, KS[1]))
    wire(d, SLVN, (JX, -1.5))
    d += elm.Capacitor().at((CAPX, KS[1])).down(-1.5 - KS[1]).label('C4 DNP\n1–10 nF 1 kV', loc='bottom', fontsize=8, ofst=0.2)
    d += elm.Dot().at((CAPX, KS[1]))
    d += elm.Dot().at((CAPX, -1.5))
    box(d, JX, 0.6, JX + 3.0, -2.3)
    pinlabel(d, (JX, KS[1]), 'TIP', 'L')
    pinlabel(d, (JX, -1.5), 'SLEEVE', 'L')
    d += elm.Label().at((JX + 1.5, 1.0)).label('J1 3,5 mm stereo', fontsize=10)
    d += elm.Label().at((JX + 1.5, -2.0)).label('RING: ei kytketty', fontsize=8)

    OUTTXT = ('K1:n reed-kosketin on napaisuudeton. Tarkista kytkentäjännite:\n'
              if REED else 'U2:n lähtö on napaisuudeton:\n')
    d += elm.Label().at((29.2, -4.3)).label(
        'Radion puoli (J1, C4) on galvaanisesti erillään\n'
        'Nanosta ja USB:stä. ' + OUTTXT +
        '• G90: 3,5 mm stereo, avaintyyppi suora avain\n'
        '• TS-515: 6,3 mm mono, jännite vielä mittaamatta (T7)',
        halign='left', valign='top', fontsize=9)

    OUTNOTE = ('KEY_SAFE ohjaa ULN2803A:n kanavaa 1 (tulossa sisäinen 2,7 kΩ), joka vetää K1:n kelan (10 mA); COM → +5V = kelan suojadiodi.'
               if REED else 'U2:n LED-virta (5 − 1,2 V) / 560 Ω ≈ 7 mA.')
    d += elm.Label().at((-8.0, -4.6)).label(
        'Toiminta kuten rev A: KEY (D11) korkea → avain alas. R3 pitää KEY:n alhaalla käynnistyksessä.\n'
        'Aikaraja: jatkuva KEY lataa C1:tä (τ = 15 s), U1A laukeaa n. 12 s:ssa → KEY_SAFE laskee, avain nousee, LED1 syttyy.\n'
        'Avaimen nosto purkaa C1:n D1+R2:n kautta (~33 ms). ' + OUTNOTE + '\n'
        'JP1 (C3 RST–GND) estää resetin sarjaportin avauksessa; JP1 pois firmwaren latauksen ajaksi.\n'
        'J2: melan painallus keskeyttää WinKeyer-puskurin (K3NG paddle break-in) → käsin STOP. BZ1/R6 valinnainen sivuääni.',
        halign='left', valign='top', fontsize=9)

d.save(BASE + '.png', dpi=130)
