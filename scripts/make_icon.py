#!/usr/bin/env python3
"""Render the editorial DN app icon as a valid 180px PNG (stdlib only)."""
from pathlib import Path
import math
import struct
import zlib

S = 180
K = 3
W = S * K
BLUE = (6, 57, 245)
WHITE = (246, 244, 237)
PINK = (255, 156, 206)
ORANGE = (255, 126, 69)
pixels = bytearray(BLUE * (W * W))

def rect(x0, y0, x1, y1, color):
    for y in range(max(0, int(y0*K)), min(W, int(y1*K))):
        for x in range(max(0, int(x0*K)), min(W, int(x1*K))):
            p = (y*W+x)*3
            pixels[p:p+3] = bytes(color)

def circle(cx, cy, radius, color):
    for y in range(max(0, int((cy-radius)*K)), min(W, int((cy+radius)*K)+1)):
        for x in range(max(0, int((cx-radius)*K)), min(W, int((cx+radius)*K)+1)):
            if (x/K-cx)**2 + (y/K-cy)**2 <= radius**2:
                p = (y*W+x)*3
                pixels[p:p+3] = bytes(color)

FONT = {
    "D": ("11110","10001","10001","10001","10001","10001","11110"),
    "N": ("10001","11001","10101","10011","10001","10001","10001"),
    "T": ("11111","00100","00100","00100","00100","00100","00100"),
    "H": ("10001","10001","10001","11111","10001","10001","10001"),
    "E": ("11111","10000","10000","11110","10000","10000","11111"),
    "A": ("01110","10001","10001","11111","10001","10001","10001"),
    "I": ("11111","00100","00100","00100","00100","00100","11111"),
    "L": ("10000","10000","10000","10000","10000","10000","11111"),
    "Y": ("10001","10001","01010","00100","00100","00100","00100"),
    "O": ("01110","10001","10001","10001","10001","10001","01110"),
    "S": ("01111","10000","10000","01110","00001","00001","11110"),
    "/": ("00001","00001","00010","00100","01000","10000","10000"),
    "0": ("01110","10001","10011","10101","11001","10001","01110"),
    "1": ("00100","01100","00100","00100","00100","00100","01110"),
    " ": ("00000",)*7,
}

def label(text, x, y, scale, color, spacing=1):
    for letter in text:
        glyph = FONT[letter]
        for row, bits in enumerate(glyph):
            for col, bit in enumerate(bits):
                if bit == "1":
                    rect(x + col*scale, y + row*scale,
                         x + (col+1)*scale, y + (row+1)*scale, color)
        x += (5 + spacing)*scale

# Minimal editorial monogram, matching docs/icon.svg.
rect(18, 21, 162, 25, WHITE)
label("THE DAILY", 22, 34, 1.55, WHITE, 1)
label("DN", 18, 69, 12.5, WHITE, 1)
rect(18, 145, 162, 150, WHITE)
label("NOISE", 22, 157, 2.3, WHITE, 1)

# Downsample supersampled RGB for softer diagonals and smooth curves.
raw = bytearray()
for y in range(S):
    raw.append(0)
    for x in range(S):
        for channel in range(3):
            total = 0
            for dy in range(K):
                for dx in range(K):
                    total += pixels[((y*K+dy)*W + (x*K+dx))*3 + channel]
            raw.append(round(total/(K*K)))

def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

png = b"\x89PNG\r\n\x1a\n"
png += chunk(b"IHDR", struct.pack(">IIBBBBB", S, S, 8, 2, 0, 0, 0))
png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
png += chunk(b"IEND", b"")
Path("docs/apple-touch-icon.png").write_bytes(png)
print("Generated valid docs/apple-touch-icon.png")
