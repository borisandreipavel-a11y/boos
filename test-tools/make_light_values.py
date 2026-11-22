"""Generate the kernel's sRGB relative luminance channel values.

Usage: python test-tools/make_light_values.py
The scale is one million for a full channel. This runs outside the kernel.
https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum
"""
from pathlib import Path


def linear(channel):
    srgb = channel / 255
    return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4


def main():
    values = [round(1_000_000 * linear(channel)) for channel in range(256)]
    lines = ["    " + ", ".join(str(entry) for entry in values[i:i + 8]) + "," for i in range(0, 256, 8)]
    path = Path(__file__).resolve().parents[1] / "src" / "light_values.rs"
    text = "//! sRGB channel values scaled to one million, made by test-tools/make_light_values.py.\n"
    text += "pub const LIGHT: [u32; 256] = [\n" + "\n".join(lines) + "\n];\n"
    path.write_text(text, encoding="utf-8", newline="\r\n")


if __name__ == "__main__":
    main()
