"""Aikarajapiirin simulointi (R1/C1/D1/R2 + 74HC132-kynnys)."""
import math
R1, C1, R2, VF, VOH = 150e3, 100e-6, 330, 0.30, 4.8
dt = 1e-3

def run(pattern, vt_plus, vt_minus=None, t_end=None):
    vt_minus = vt_minus or vt_plus - 0.9
    v, to, t = 0.0, False, 0.0
    first_to = None
    key_time_out = 0.0
    for key, dur in pattern:
        n = int(dur / dt)
        for _ in range(n):
            vk = VOH if key else 0.0
            i = (vk - v) / R1
            if v - vk > VF:
                i -= (v - vk - VF) / R2
            v += i * dt / C1
            if not to and v > vt_plus:
                to = True
                if first_to is None: first_to = t
            if to and v < vt_minus:
                to = False
            if key and not to:
                key_time_out += dt
            t += dt
    return first_to, v, key_time_out

for vt in (1.8, 2.5, 2.9, 3.5):
    print(f"VT+={vt}: jumittunut avain -> timeout {run([(1, 60)], vt)[0]:.1f} s")

# 12 WPM: dit 0.1 s. 'CQ CQ CQ DE OH...' ~ 50% duty for 120 s
dit = 0.1
pat = []
for _ in range(600):
    pat += [(1, 3*dit), (0, dit), (1, dit), (0, dit)]
r = run(pat, 1.8)
print("12 WPM, 50% duty, 120 s, pahin kynnys 1.8 V -> timeout:", r[0], " C1 lopussa %.2f V" % r[1])
# TUNE 10 s then release, again 10 s after 2 s pause
r = run([(1, 10), (0, 2), (1, 10)], 2.9)
print("TUNE 10s + 2s tauko + 10s (VT+=2.9) -> timeout:", r[0])
# sähkötys hitaasti: pitkä viiva 1 s (5 WPM) toistuva
r = run([(1, 1.0), (0, 0.3)] * 100, 1.8)
print("1 s viivat / 0.3 s tauot, VT+=1.8 -> timeout:", r[0], "V=%.2f" % r[1])
