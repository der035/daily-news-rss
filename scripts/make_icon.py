#!/usr/bin/env python3
"""Generate a self-contained iOS home-screen icon using Python standard library."""
from pathlib import Path
import struct
import zlib

SIZE = 180
BLUE = (6, 57, 245)
PINK = (255, 156, 206)
ORANGE = (255, 126, 69)
WHITE = (245, 243, 237)
D = ["11110", "10001", "10001", "10001", "10001", "10001", "11110"]
N = ["10001", "11001", "10101", "10011", "10001", "10001", "10001"]
pixels = bytearray()
for y in range(SIZE):
    pixels.append(0)
    for x in range(SIZE):
        color = BLUE
        if 17 <= x < 163 and 20 <= y < 32:
            color = PINK
        if 17 <= x < 163 and 147 <= y < 157:
            color = ORANGE
        for glyph, start in ((D, 23), (N, 94)):
            gx = (x - start) // 12
            gy = (y - 48) // 12
            if start <= x < start + 60 and 48 <= y < 132 and glyph[gy][gx] == "1":
                color = WHITE
        pixels.extend(color)

def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

png = b"\\x89PNG\\r\\n\\x1a\\n"
png += chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0))
png += chunk(b"IDAT", zlib.compress(bytes(pixels), 9))
png += chunk(b"IEND", b"")
Path("docs/apple-touch-icon.png").write_bytes(png)
print("Generated docs/apple-touch-icon.png")
