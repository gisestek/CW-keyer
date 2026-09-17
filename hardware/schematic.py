"""CW keyer – M0 hardware proto schematic (rev A).
Generates cw-keyer-m0-proto.svg / .png with schemdraw:  pip install schemdraw
"""
import schemdraw
import schemdraw.elements as elm
import schemdraw.logic as logic

schemdraw.config(fontsize=11, font='DejaVu Sans', lw=1.4)


def box(d, x0, y0, x1, y1):
    d += elm.Line().at((x0, y0)).to((x1, y0))
    d += elm.Line().at((x1, y0)).to((x1, y1))
    d += elm.Line().at((x1, y1)).to((x0, y1))
    d += elm.Line().at((x0, y1)).to((x0, y0))


def vdd(d, p, txt='+5V'):
    d += elm.Vdd().at(p).theta(0).label(txt, loc='right', fontsize=9)


def gnd(d, p):
    d += elm.Ground().at(p).theta(0)


def pinlabel(d, p, txt, side):
    # side: 'in' (label inside box to the left of a right-edge pin) etc.
    ha = 'right' if side == 'R' else 'left'
    dx = -0.15 if side == 'R' else 0.15
    d += elm.Label().at((p[0] + dx, p[1])).label(txt, halign=ha, valign='center', fontsize=10)


def wire(d, *pts, dashed=False):
    for a, b in zip(pts, pts[1:]):
        ln = elm.Line().at(a).to(b)
        if dashed:
            ln.linestyle('--')
        d += ln


with schemdraw.Drawing(file='cw-keyer-m0-proto.svg', show=False) as d:
    d.config(unit=2.5)

    # ---------------- Title ----------------
    d += elm.Label().at((-2.0, 7.2)).label(
        'CW keyer – M0 hardware proto  ·  Arduino Nano + relemoduuli + laitteistoinen aikaraja  ·  rev A  2026-09-17',
        halign='left', fontsize=14)

    # ---------------- Arduino Nano ----------------
    box(d, 0, -2.5, 3.2, 5.5)
    d += elm.Label().at((1.6, 5.0)).label('Arduino Nano', fontsize=12)
    d += elm.Label().at((1.6, 4.4)).label('K3NG, WinKeyer', fontsize=9)
    P5V, PRST, PD11, PGND = (3.2, 3.5), (3.2, 2.0), (3.2, 0.0), (3.2, -1.8)
    PUSB = (0, 1.0)
    for p, t in ((P5V, '5V'), (PRST, 'RST'), (PD11, 'D11'), (PGND, 'GND')):
        pinlabel(d, p, t, 'R')
    pinlabel(d, PUSB, 'USB (CH340)', 'L')
    wire(d, PUSB, (-1.2, 1.0))
    d += elm.Label().at((-1.3, 1.0)).label('PC', halign='right', valign='center')

    wire(d, P5V, (4.0, 3.5))
    vdd(d, (4.0, 3.5))
    wire(d, PGND, (4.0, -1.8))
    gnd(d, (4.0, -1.8))

    # JP1 + C3: disable auto-reset (remove JP1 when uploading firmware)
    wire(d, PRST, (4.8, 2.0))
    d += elm.Switch().at((4.8, 2.0)).right(1.4)
    d += elm.Label().at((5.5, 2.55)).label('JP1', fontsize=9)
    d += elm.Capacitor(polar=True).at((6.2, 2.0)).down(1.2).label('C3 10µF', loc='bottom', fontsize=9, ofst=0.3)
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
    # fast discharge: T -> D1 (anode at T) -> R2 -> KEY
    wire(d, K2, (9.0, 1.5))
    d += elm.Resistor().at((9.0, 1.5)).to((10.5, 1.5)).label('R2 330', loc='top', fontsize=10)
    d += elm.Diode().at((12.0, 1.5)).to((10.5, 1.5)).label('D1 BAT85', loc='top', fontsize=10)
    wire(d, (12.0, 1.5), T)

    # ---------------- 74HC132 ----------------
    # U1A: /TO = NOT T
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

    # U1B: /KEY = NAND(KEY, /TO)
    ub = logic.SchmittNand(inputs=2).right().anchor('in2').at((19.2, NTO[1]))
    d += ub
    d += elm.Label().at((20.4, 1.05)).label('U1B', fontsize=10)
    wire(d, NTO, ub.in2)
    TOPY = 3.8
    wire(d, KEY, (7.5, TOPY), (18.6, TOPY), (18.6, ub.in1[1]), ub.in1)
    NKEY = (21.8, ub.out[1])
    wire(d, ub.out, NKEY)
    d += elm.Dot().at(NKEY)
    d += elm.Label().at((21.8, 0.75)).label('/KEY', fontsize=10)

    # U1C: KEY_SAFE = NOT /KEY
    uc = logic.SchmittNand(inputs=2).right().anchor('in1').at((23.2, NKEY[1] + 0.25))
    d += uc
    d += elm.Label().at((24.1, 1.05)).label('U1C', fontsize=10)
    CJ = (22.6, NKEY[1])
    wire(d, NKEY, CJ, (22.6, uc.in1[1]), uc.in1)
    wire(d, CJ, (22.6, uc.in2[1]), uc.in2)
    d += elm.Dot().at(CJ)
    KS = (26.2, uc.out[1])
    wire(d, uc.out, KS)
    d += elm.Dot().at(KS)
    d += elm.Label().at((26.0, 0.75)).label('KEY_SAFE', fontsize=10)

    # U1D: TO = NOT /TO -> LED1
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
    d += elm.LED().down(1.6).label('LED1 punainen\n"TIMEOUT"', loc='bottom', fontsize=9)
    gnd(d, d.here)

    d += elm.Label().at((13.0, -6.4)).label(
        'U1 = 74HC132 (DIP-14, Schmitt-NAND): pin 14 → +5V, pin 7 → GND,\n'
        'C2 100 nF pinnien 14 ja 7 väliin. Kaikki neljä porttia käytössä.',
        halign='left', fontsize=9)

    # ---------------- Relay module ----------------
    RX0, RX1 = 29.0, 33.4
    box(d, RX0, 1.2, RX1, -3.4)
    d += elm.Label().at(((RX0 + RX1) / 2, 0.75)).label('5 V relemoduuli', fontsize=11)
    RIN, RVCC, RGND = (RX0, KS[1]), (RX0, -1.5), (RX0, -2.7)
    RNO, RCOM, RNC = (RX1, KS[1]), (RX1, -1.5), (RX1, -2.7)
    for p, t in ((RIN, 'IN'), (RVCC, 'VCC'), (RGND, 'GND')):
        pinlabel(d, p, t, 'L')
    for p, t in ((RNO, 'NO'), (RCOM, 'COM'), (RNC, 'NC')):
        pinlabel(d, p, t, 'R')
    d += elm.Label().at(((RX0 + RX1) / 2, -3.9)).label('esim. SRD-05VDC-SL-C', fontsize=8)

    # JP2 selects trigger polarity
    J2 = (27.4, KS[1])
    wire(d, KS, J2)
    d += elm.Switch().at(J2).to((28.6, KS[1]))
    wire(d, (28.6, KS[1]), RIN)
    d += elm.Label().at((28.0, 1.0)).label('JP2', fontsize=9)
    wire(d, NKEY, (21.8, -0.8), (27.0, -0.8), dashed=True)
    d += elm.Label().at((24.4, -1.15)).label('L-ohjattu moduuli: JP2 auki, /KEY → IN', fontsize=8)
    wire(d, (27.0, -0.8), (28.6, -0.8), (28.6, KS[1]), dashed=True)
    wire(d, RVCC, (28.2, -1.5))
    d += elm.Label().at((28.1, -1.5)).label('+5V', halign='right', valign='center', fontsize=9)
    wire(d, RGND, (28.4, -2.7))
    gnd(d, (28.4, -2.7))

    # ---------------- Output jack ----------------
    JX = 37.2
    wire(d, RNO, (JX, KS[1]))
    wire(d, RCOM, (JX, -1.5))
    d += elm.Label().at((35.3, 0.6)).label('KEY', fontsize=9)
    d += elm.Label().at((35.3, -1.15)).label('maa', fontsize=9)
    box(d, JX, 0.6, JX + 3.0, -2.3)
    pinlabel(d, (JX, KS[1]), 'TIP', 'L')
    pinlabel(d, (JX, -1.5), 'SLEEVE', 'L')
    d += elm.Label().at((JX + 1.5, 1.0)).label('J1  3,5 mm stereo', fontsize=10)
    d += elm.Label().at((JX + 1.5, -2.0)).label('RING: ei kytketty', fontsize=8)

    d += elm.Label().at((29.0, -4.6)).label(
        'Radiokaapelit J1:stä:\n'
        '• G90 KEY: 3,5 mm stereo, tip + sleeve, KEY-tila suora avain\n'
        '• TS-515 KEY: 6,3 mm mono, tip = negatiivinen avainjännite\n'
        'Relekoskettimet ovat galvaanisesti erillään Nanosta ja USB:stä.',
        halign='left', valign='top', fontsize=9)

    # ---------------- Notes ----------------
    d += elm.Label().at((-2.0, -4.6)).label(
        'Toiminta: KEY (D11) = korkea → avain alas. R3 pitää KEY:n alhaalla, kun Nano käynnistyy tai on irti.\n'
        'Aikaraja: jatkuva KEY-korkea lataa C1:tä R1:n kautta (τ = 15 s). Kun T ylittää U1A:n kynnyksen (tyyp. ~2,6 V, n. 12 s),\n'
        '/TO laskee → KEY_SAFE laskee → rele päästää ja LED1 syttyy. Avaimen nosto purkaa C1:n D1+R2:n kautta (~33 ms),\n'
        'joten normaali sähkötys ei kerrytä ajastinta. Nollautuu, kun KEY laskee.\n'
        'JP1 (C3 RST–GND) estää Nanon resetin sarjaportin avauksessa; poista JP1 firmwaren latauksen ajaksi.',
        halign='left', valign='top', fontsize=9)

d.save('cw-keyer-m0-proto.png', dpi=130)
