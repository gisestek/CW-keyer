#!/usr/bin/env python3
"""M0-kokeilu: WinKeyer-komennot K3NG-keyerille komentoriviltä.

Käyttö:
  pip install pyserial
  python wk_test.py COM5 send "TEST TEST"      # lähetä teksti
  python wk_test.py COM5 key 3                 # avain alas 3 s (TUNE-testi)
  python wk_test.py COM5 key 30                # aikarajatesti: rele päästää ~12 s kohdalla
Ctrl+C lähettää aina clear buffer + key up + host close.
"""
import sys
import time
import serial

WPM = 20


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return
    port, cmd, arg = sys.argv[1], sys.argv[2], sys.argv[3]
    ser = serial.Serial(port, 1200, bytesize=8, parity='N', stopbits=2, timeout=1)
    time.sleep(2.0)                      # jos JP1 puuttuu, Nano resetoituu portin avauksessa
    ser.reset_input_buffer()
    ser.write(b'\x00\x02')               # Admin: Host Open
    ver = ser.read(1)
    print('WinKeyer-versio:', ver[0] if ver else 'ei vastausta')
    ser.write(bytes([0x02, WPM]))        # nopeus
    try:
        if cmd == 'send':
            text = arg.upper().encode('ascii', 'ignore')
            ser.write(text)
            # odota, kunnes keyer on lähettänyt (status-bitti BUSY = 0x04)
            t_end = time.time() + 2 + len(text) * 60 / WPM / 5 * 1.5
            while time.time() < t_end:
                b = ser.read(1)
                if b and (b[0] & 0xC0) == 0xC0:
                    if not (b[0] & 0x04):
                        break
                elif b:
                    print(chr(b[0]), end='', flush=True)   # kaiku
            print()
        elif cmd == 'key':
            secs = float(arg)
            print(f'avain alas {secs} s ...')
            ser.write(b'\x0B\x01')       # Key Immediate: down
            t0 = time.time()
            while time.time() - t0 < secs:
                time.sleep(0.5)
                print(f'  {time.time() - t0:5.1f} s', end='\r', flush=True)
            print()
    except KeyboardInterrupt:
        print('\nSTOP')
    finally:
        ser.write(b'\x0A')               # Clear Buffer
        ser.write(b'\x0B\x00')           # Key Immediate: up
        time.sleep(0.2)
        ser.write(b'\x00\x03')           # Admin: Host Close
        ser.close()


if __name__ == '__main__':
    main()
