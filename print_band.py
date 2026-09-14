#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
print_band.py — 把超長條碼帶切成 58mm 熱感印表機（ZJ-58 / GP-58）印得出來的片段。

為什麼要這支程式
----------------
hitem_band_0.png 是 77220 x 120 px，長寬比 643:1。直接 `lp` 印會讓 CUPS 的
imagetoraster 在把圖塞進 58mm 頁寬時算出 cupsWidth = 0，除以零而崩潰
（ERROR: imagetoraster crashed on signal 8）。

作法
----
1. 這種帶狀圖每一直行（column）在高度方向都是同一個值，也就是一維資料。
   取出模組（module）序列後可以用任意模組寬度重畫，不會失真。
   若圖不是這種形式，會自動退回「整張旋轉 90° 再切」的通用模式。
2. 旋轉 90°，讓條碼沿著「出紙方向」跑。一段之內本來就是連續的，
   段與段之間照裁切線剪齊接起來，就是一條完整連續的條碼。
3. 每段輸出 384px 寬（= 印表機全寬 48mm）的 PNG，尺寸剛好等於印表機像素，
   不需要任何縮放；可直接用 ESC/POS raw 送印，完全繞過 CUPS。

用法
----
  # 只估算，不輸出（先看要花多少紙）
  python3 print_band.py ~/barcode_video/hitem_band_0.png --estimate

  # 輸出 PNG 到 band_out/
  python3 print_band.py ~/barcode_video/hitem_band_0.png

  # 省紙：模組寬 6px -> 2px，資料完全不變，紙長剩三分之一
  python3 print_band.py ~/barcode_video/hitem_band_0.png --module 2

  # 直接印（Pi 上的印表機，barcode_with_midi.py 用的是 /dev/usb/lp1）
  python3 print_band.py ~/barcode_video/hitem_band_0.png --module 2 --print

  # 紙用完了，只補印第 7 到第 9 段
  python3 print_band.py ~/barcode_video/hitem_band_0.png --module 2 --print --from 7 --to 9

  # 驗證切出來的段接回去跟原圖一模一樣
  python3 print_band.py ~/barcode_video/hitem_band_0.png --verify
"""

import argparse
import os
import sys
from functools import reduce
from math import gcd

import numpy as np
from PIL import Image, ImageDraw, ImageFont

DPMM = 8.0          # 203 dpi ≒ 8 dots/mm
DEFAULT_HEAD = 384  # 58mm 機種的可印寬度（px）


def mm2px(mm, dpmm=DPMM):
    return int(round(mm * dpmm))


def px2mm(px, dpmm=DPMM):
    return px / dpmm


# ─────────────────────────────────────────────
#  帶狀資料
# ─────────────────────────────────────────────

class ModuleBand:
    """一維條碼帶：bits 是每個模組的 0/1，可用任意模組寬度重畫（無損）。"""

    kind = "1d"

    def __init__(self, bits, module_px, thickness_px, native_module):
        self.bits = bits
        self.module_px = int(module_px)
        self.thickness_px = int(thickness_px)
        self.native_module = int(native_module)
        self.length_px = len(bits) * self.module_px

    def rows(self, a, b):
        col = self.bits[np.arange(a, b) // self.module_px]
        return np.repeat(col[:, None], self.thickness_px, axis=1)


class ImageBand:
    """通用長圖：整張順時針轉 90°，原圖的 x 軸變成出紙方向。"""

    kind = "2d"

    def __init__(self, src, len_scale, thick_scale):
        self.rot = np.rot90(src, k=-1)          # (W, H)，row i = 原圖第 i 行
        self.len_scale = int(len_scale)
        self.thick_scale = int(thick_scale)
        self.length_px = self.rot.shape[0] * self.len_scale
        self.thickness_px = self.rot.shape[1] * self.thick_scale

    def rows(self, a, b):
        sub = self.rot[np.arange(a, b) // self.len_scale, :]
        return np.repeat(sub, self.thick_scale, axis=1)


def load_band(path, module_px=None, band_mm=None, head_px=DEFAULT_HEAD, dpmm=DPMM):
    """讀圖並判斷是一維帶狀圖還是一般長圖。"""
    src = np.array(Image.open(path).convert("L")) < 128      # True = 黑
    if src.ndim != 2:
        sys.exit(f"讀不懂的圖：{path}")
    h, w = src.shape

    uniform = bool((src.all(axis=0) | (~src).all(axis=0)).all())

    if uniform:
        row = src[0].astype(np.uint8)
        cuts = np.flatnonzero(np.diff(row)) + 1
        runs = np.diff(np.concatenate(([0], cuts, [w])))
        native = int(reduce(gcd, runs.tolist()))
        bits = row[::native].astype(bool)
        mod = native if module_px is None else int(module_px)
        if mod < 1:
            sys.exit("--module 至少要 1")
        thick = mm2px(band_mm, dpmm) if band_mm else h
        thick = max(1, min(thick, head_px))
        return ModuleBand(bits, mod, thick, native)

    # 不是一維帶狀圖 → 通用模式
    scale = 1
    if band_mm:
        scale = max(1, mm2px(band_mm, dpmm) // h)
    if h * scale > head_px:
        scale = max(1, head_px // h)
    return ImageBand(src, len_scale=1, thick_scale=scale)


# ─────────────────────────────────────────────
#  畫出一段
# ─────────────────────────────────────────────

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _font(size):
    for p in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:          # Pillow < 10.1
        return ImageFont.load_default()


def _vtext(text, margin_px):
    """做一張直式（轉 90°）的文字圖，高度不超過 margin_px。"""
    font = _font(max(8, margin_px - 6))
    tmp = Image.new("L", (400, margin_px), 255)
    ImageDraw.Draw(tmp).text((0, 0), text, font=font, fill=0)
    box = tmp.getbbox()
    if box is None:
        return None
    return tmp.crop(box).rotate(-90, expand=True)


def render_segment(band, a, b, idx, total, head_px, tick=True, label=True):
    """把 band 的 [a, b) 這段畫成一張 head_px 寬、可直接送印的圖。"""
    n = b - a
    canvas = np.zeros((n, head_px), dtype=bool)
    x0 = (head_px - band.thickness_px) // 2
    canvas[:, x0:x0 + band.thickness_px] = band.rows(a, b)

    img = Image.fromarray(np.where(canvas, 0, 255).astype(np.uint8), mode="L")

    margin = x0
    if margin >= 10:
        d = ImageDraw.Draw(img)
        x1 = x0 + band.thickness_px
        if tick:
            # 裁切線：只畫在左右留白，帶身保持乾淨。剪在這兩條線上就能無縫接起來。
            t = 3
            for y in (0, n - t):
                d.rectangle([0, y, x0 - 4, y + t - 1], fill=0)
                d.rectangle([x1 + 3, y, head_px - 1, y + t - 1], fill=0)
        if label:
            txt = _vtext(f"{idx}/{total}", margin)
            if txt is not None:
                for y in (mm2px(8), n - mm2px(8) - txt.height):
                    if 0 <= y <= n - txt.height:
                        img.paste(txt, (1, y))

    return img.convert("1")


# ─────────────────────────────────────────────
#  列印
# ─────────────────────────────────────────────

def send_to_printer(img, device, feed_lines, do_cut, profile="ZJ-5870"):
    from escpos.printer import File
    try:
        p = File(device, profile=profile)
    except Exception:          # 舊版 escpos 可能沒有這個 profile
        p = File(device)
    try:
        p.image(img, impl="bitImageRaster", fragment_height=2048, center=False)
        if feed_lines > 0:
            p.ln(feed_lines)
        if do_cut:
            if p.profile.supports("paperFullCut") or p.profile.supports("paperPartCut"):
                p.cut()
            else:
                # profile 標示沒有切刀，但多數 ZJ-58 其實吃這個指令；
                # 沒切刀的機器會直接忽略，所以照送。
                from escpos.constants import PAPER_FULL_CUT
                p.print_and_feed(6)
                p._raw(PAPER_FULL_CUT)
    finally:
        try:
            p.close()
        except Exception:
            pass


# ─────────────────────────────────────────────
#  主程式
# ─────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="把超長條碼帶切成 58mm 熱感印表機印得出來的連續片段",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", help="長條圖，例如 ~/barcode_video/hitem_band_0.png")
    ap.add_argument("--module", type=int, default=None,
                    help="每個模組的印表機像素寬（預設保持原圖的 6px；調小可省紙且無損）")
    ap.add_argument("--band-mm", type=float, default=40.0,
                    help="印出來的帶寬 mm（預設 40，留白用來放裁切線和段號）")
    ap.add_argument("--seg-mm", type=float, default=500.0,
                    help="每段紙長 mm（預設 500；設 0 = 不切，整條一次印完）")
    ap.add_argument("--head-px", type=int, default=DEFAULT_HEAD,
                    help="印表機可印寬度 px（58mm=384，80mm=576）")
    ap.add_argument("--out", default="band_out", help="PNG 輸出資料夾")
    ap.add_argument("--no-png", action="store_true", help="不要存 PNG（配合 --print 直接印）")
    ap.add_argument("--print", dest="do_print", action="store_true", help="直接送印")
    ap.add_argument("--device", default="/dev/usb/lp1", help="印表機裝置（預設 /dev/usb/lp1）")
    ap.add_argument("--profile", default="ZJ-5870",
                    help="python-escpos 的印表機 profile（58mm 用 ZJ-5870）")
    ap.add_argument("--feed-lines", type=int, default=4,
                    help="每段印完往前送幾行，讓最後幾列離開切紙口（預設 4）")
    ap.add_argument("--no-cut", action="store_true", help="不下切紙指令")
    ap.add_argument("--auto", action="store_true", help="連續印，不要每段等 Enter")
    ap.add_argument("--from", dest="first", type=int, default=1, help="從第幾段開始（1 起算）")
    ap.add_argument("--to", dest="last", type=int, default=0, help="印到第幾段（0 = 最後一段）")
    ap.add_argument("--no-tick", action="store_true", help="不畫裁切線")
    ap.add_argument("--no-label", action="store_true", help="不印段號")
    ap.add_argument("--estimate", action="store_true", help="只估算用紙，不輸出也不印")
    ap.add_argument("--verify", action="store_true", help="驗證切出來的段接回去等於原圖")
    args = ap.parse_args()

    path = os.path.expanduser(args.image)
    if not os.path.exists(path):
        sys.exit(f"找不到檔案：{path}")

    band = load_band(path, args.module, args.band_mm, args.head_px)

    seg_rows = band.length_px if args.seg_mm <= 0 else mm2px(args.seg_mm)
    seg_rows = max(1, min(seg_rows, band.length_px))
    total = (band.length_px + seg_rows - 1) // seg_rows

    # ── 摘要 ──
    print(f"來源     : {path}")
    if band.kind == "1d":
        print(f"型態     : 一維條碼帶，{len(band.bits)} 個模組"
              f"（原圖模組寬 {band.native_module}px → 輸出 {band.module_px}px）")
    else:
        print(f"型態     : 一般長圖（非一維），整張旋轉 90° 後切")
    print(f"帶長     : {band.length_px} px = {px2mm(band.length_px):.0f} mm "
          f"= {px2mm(band.length_px)/1000:.2f} m")
    print(f"帶寬     : {band.thickness_px} px = {px2mm(band.thickness_px):.1f} mm"
          f"（紙寬 {px2mm(args.head_px):.0f} mm）")
    last_mm = px2mm(band.length_px - (total - 1) * seg_rows)
    print(f"分段     : {total} 段 x {px2mm(seg_rows):.0f} mm（最後一段 {last_mm:.0f} mm）")

    if band.kind == "1d":
        print("\n模組寬對紙長的影響（資料完全不變）：")
        for m in (1, 2, 3, 4, 6):
            mark = "  ← 目前" if m == band.module_px else ""
            print(f"  --module {m} : {len(band.bits) * m / DPMM / 1000:6.2f} m{mark}")

    if args.estimate:
        return

    # ── 驗證 ──
    if args.verify:
        src = np.array(Image.open(path).convert("L")) < 128
        ref = src[0] if band.kind == "1d" else None
        joined = []
        for i in range(total):
            a, b = i * seg_rows, min((i + 1) * seg_rows, band.length_px)
            joined.append(band.rows(a, b)[:, 0])
        joined = np.concatenate(joined)
        print()
        if ref is not None and band.module_px == band.native_module:
            ok = np.array_equal(joined, ref)
            print(f"接回原圖比對：{'一致 ✓' if ok else '不一致 ✗'}"
                  f"（{len(joined)} px vs {len(ref)} px）")
        else:
            ok = len(joined) == band.length_px
            print(f"接合長度檢查：{'正確 ✓' if ok else '錯誤 ✗'}"
                  f"（{len(joined)} px / 應為 {band.length_px} px）")
        if not ok:
            sys.exit(1)
        if not args.do_print and args.no_png:
            return

    first = max(1, args.first)
    last = total if args.last <= 0 else min(args.last, total)
    if first > last:
        sys.exit(f"--from {first} 大於 --to {last}")

    outdir = None
    if not args.no_png:
        outdir = os.path.expanduser(args.out)
        os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    width = len(str(total))

    print()
    for i in range(first, last + 1):
        a = (i - 1) * seg_rows
        b = min(i * seg_rows, band.length_px)
        img = render_segment(band, a, b, i, total, args.head_px,
                             tick=not args.no_tick, label=not args.no_label)

        note = ""
        if outdir:
            name = f"{stem}_seg{i:0{width}d}of{total}.png"
            img.save(os.path.join(outdir, name))
            note = f" -> {name}"
        print(f"第 {i}/{total} 段：{px2mm(b - a):.0f} mm{note}")

        if args.do_print:
            try:
                send_to_printer(img, args.device, args.feed_lines,
                                not args.no_cut, args.profile)
            except Exception as e:
                sys.exit(f"[列印錯誤] {e}\n（裝置 {args.device} 存在嗎？"
                         f"可以用 ls -l /dev/usb/lp* 看，權限不足就把自己加進 lp 群組）")
            if not args.auto and i < last:
                try:
                    input("    沿裁切線剪下後按 Enter 印下一段（Ctrl+C 中止）…")
                except KeyboardInterrupt:
                    print("\n中止。")
                    return

    if outdir:
        print(f"\nPNG 已存到 {outdir}/")
        print("這些圖已經是印表機的實際像素，不需要縮放。若要走 CUPS：")
        print(f"  lp -d <印表機名> -o scaling=100 -o fit-to-page=false {outdir}/{stem}_seg*.png")
        print("但建議用 --print 走 ESC/POS，CUPS 這條路才是一開始崩掉的原因。")


if __name__ == "__main__":
    main()
