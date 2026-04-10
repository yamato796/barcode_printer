from dataclasses import dataclass
from typing import List, Tuple
import mido
import pygame
import pygame.midi
import time
import subprocess
import hashlib
from barcode import Code128
from barcode.writer import ImageWriter
from PIL import Image
import os

# ─────────────────────────────────────────────
#  顯示設定（依實際情況調整）
# ─────────────────────────────────────────────
TEMPLATE_PATH = "./IMG_0114.PNG"       # 背景模板圖片路徑

# 條碼要貼入模板的位置與大小（像素）
# (x, y) 為左上角，width/height 為縮放後的條碼尺寸
BARCODE_X      = 36
BARCODE_Y      = 774
BARCODE_WIDTH  = 860
BARCODE_HEIGHT = 230

DISPLAY_SECONDS = 10   # 每張圖顯示幾秒（0 = 一直顯示到下一張）
# ─────────────────────────────────────────────



@dataclass
class Note:
    pitch: int
    duration_beats: float
    velocity: int = 80

SCALES = {
    "major":      [0, 2, 4, 5, 7, 9, 11],
    "minor":      [0, 2, 3, 5, 7, 8, 10],
    "pentatonic": [0, 2, 4, 7, 9],
}

def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))

def params_from_text(text: str):
    h = hashlib.sha256(text.encode("utf-8", errors="ignore")).digest()

    scales = ["major", "minor", "pentatonic"]
    programs = [81, 100, 104, 84, 85, 86] 

    scale = scales[h[0] % len(scales)]
    bpm = 70 + (h[1] % 121)          # 70..190
    base_note = 36 + (h[2] % 25)     # 36..60
    unit_beats = [0.125, 0.25, 0.375, 0.5][h[3] % 4]
    program = programs[h[4] % len(programs)]
    chord_duration = 1.0 + (h[5] % 8) * 0.5   # 1.0..5.0

    return scale, bpm, base_note, unit_beats, program, chord_duration


def ascii_to_notes(
    barcode_ascii: str,
    base_note: int = 48,       
    scale: str = "minor",
    unit_beats: float = 0.25,    
    min_run: int = 1,
    max_run: int = 12,
) -> List[Note]:

    s = barcode_ascii.replace("\r", "").replace("\n", "")
    if not s:
        return []

    # run-length encode
    runs: List[Tuple[str, int]] = []
    prev = s[0]
    cnt = 1
    for ch in s[1:]:
        if ch == prev:
            cnt += 1
        else:
            runs.append((prev, cnt))
            prev, cnt = ch, 1
    runs.append((prev, cnt))

    scale_ints = SCALES.get(scale.lower())
    if not scale_ints:
        raise ValueError(f"Unknown scale: {scale}. Use one of {list(SCALES.keys())}")

    notes: List[Note] = []
    for i, (ch, run) in enumerate(runs):
        run = clamp(run, min_run, max_run)

        is_bar = ch in ("|", "1", "█", "#", "X", "x")

        degree = scale_ints[(ord(ch) + i + run) % len(scale_ints)]

        pitch = base_note + degree + (12 if is_bar else 0)
        pitch = clamp(pitch, 0, 127)
        velocity = 95 if is_bar else 55

        duration = run * unit_beats
        notes.append(Note(pitch=pitch, duration_beats=duration, velocity=velocity))

    return notes


def notes_to_midi_file(
    notes: List[Note],
    out_path: str,
    bpm: int = 120,
    program: int = 0,        # 0=Acoustic Grand Piano
    channel: int = 0,
    ticks_per_beat: int = 480,
) -> None:
    mid = mido.MidiFile(ticks_per_beat=ticks_per_beat,type=1)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    track.append(mido.Message("program_change", program=program, channel=channel, time=0))

    for n in notes:
        track.append(mido.Message("note_on", note=n.pitch, velocity=n.velocity, channel=channel, time=0))
        track.append(mido.Message(
            "note_off",
            note=n.pitch,
            velocity=0,
            channel=channel,
            time=int(n.duration_beats * ticks_per_beat),
        ))

    mid.save(out_path)

def notes_to_midi_chord_file(
    notes,
    out_path: str,
    bpm: int = 120,
    program: int = 0,
    channel: int = 0,
    ticks_per_beat: int = 480,
    chord_duration_beats: float = 3.0,  
):
    mid = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    track.append(mido.Message("program_change", program=program, channel=channel, time=0))

    # remove dup pitch
    pitches = sorted({n.pitch for n in notes})
    if not pitches:
        raise ValueError("No notes to write")

    # avg
    vel = int(sum(getattr(n, "velocity", 80) for n in notes) / len(notes))
    vel = max(1, min(127, vel))

    # all note_on
    first = True
    for p in pitches:
        track.append(mido.Message("note_on", note=p, velocity=vel, channel=channel, time=0 if first else 0))
        first = False

    # wait for chord_duration ，all note_off
    off_time = int(chord_duration_beats * ticks_per_beat)
    first = True
    for p in pitches:
        track.append(mido.Message("note_off", note=p, velocity=0, channel=channel, time=off_time if first else 0))
        first = False

    mid.save(out_path)


def barcode_ascii_to_midi(
    barcode_ascii: str,
    out_path: str = "barcode.mid",
    bpm: int = 120,
    scale: str = "minor",
    base_note: int = 48,
    unit_beats: float = 0.25,
    program: int = 0,
) -> None:
    
    scale, bpm, base_note, unit_beats, program, chord_duration = params_from_text(barcode_ascii)

    notes = ascii_to_notes(
        barcode_ascii=barcode_ascii,
        base_note=base_note,
        scale=scale,
        unit_beats=unit_beats,
    )
    if not notes:
        raise ValueError("Input barcode_ascii is empty after stripping newlines.")
    #notes_to_midi_file(notes, out_path, bpm=bpm, program=program)
    #notes_to_midi_chord_file(notes, out_path, bpm=bpm, program=program, chord_duration_beats=chord_duration)
    notes_to_midi_chord_file(notes, out_path, bpm=bpm, program=program, chord_duration_beats=3.0)
    #notes_to_midi_chord_file(notes, out_path, bpm=bpm, program=program)

def play_with_fluidsynth(mid_path: str, sf2_path: str = "/usr/share/sounds/sf2/FluidR3_GM.sf2"):
    #subprocess.run(["fluidsynth","-ni", "-a", "alsa", "-o", "audio.alsa.device=hw:1", "-g", "1.0", sf2_path, mid_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["fluidsynth","-ni", "-a", "alsa", "-o", "audio.alsa.device=plughw:3", "-g", "1.0", sf2_path, mid_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    #res = subprocess.run(["fluidsynth","-ni", "-a", "alsa", "-o", "audio.alsa.device=plughw:3", "-g", "1.0", sf2_path, mid_path], check=True, capture_output=True, text=True)
    #print(res)
# ─────────────────────────────────────────────
#  全螢幕顯示
# ─────────────────────────────────────────────

# 全域 pygame surface（主執行緒持有）
_screen      = None
_screen_size = (0, 0)

def init_display():
    """初始化 pygame 全螢幕視窗（在主執行緒呼叫一次）。"""
    global _screen, _screen_size
    os.environ.setdefault("SDL_VIDEODRIVER", "x11")   # RPi 可改 "fbdev" 若無桌面
    os.environ["SDL_AUDIODRIVER"] = "dummy"           # 不讓 pygame 佔用音訊裝置，讓 fluidsynth 可以用 ALSA
    pygame.display.init()
    pygame.font.init()
    info = pygame.display.Info()
    _screen_size = (info.current_w, info.current_h)
    _screen = pygame.display.set_mode(_screen_size, pygame.FULLSCREEN | pygame.NOFRAME)
    pygame.display.set_caption("Barcode Display")
    pygame.mouse.set_visible(False)
    # 先填白色底，避免初始黑屏
    _screen.fill((255, 255, 255))
    pygame.display.flip()
    # 開機畫面：若模板存在就先顯示
    if os.path.exists(TEMPLATE_PATH):
        show_image_on_screen(TEMPLATE_PATH)


def composite_barcode(barcode_png: str) -> str:
    """
    把條碼圖貼入模板，回傳合成後的暫存檔路徑。
    若模板不存在，直接回傳原始條碼路徑。
    """
    if not os.path.exists(TEMPLATE_PATH):
        print(f"[警告] 找不到模板 {TEMPLATE_PATH}，直接顯示條碼。")
        return barcode_png

    template_rgba = Image.open(TEMPLATE_PATH).convert("RGBA")
    # 先把模板合成到白色背景（避免透明通道變黑）
    bg = Image.new("RGB", template_rgba.size, (255, 255, 255))
    bg.paste(template_rgba, mask=template_rgba.split()[3])

    barcode = Image.open(barcode_png).convert("RGB")
    barcode = barcode.resize((BARCODE_WIDTH, BARCODE_HEIGHT), Image.LANCZOS)

    bg.paste(barcode, (BARCODE_X, BARCODE_Y))

    out_path = barcode_png.replace(".png", "_display.png")
    bg.save(out_path)
    return out_path


def show_image_on_screen(image_path: str):
    """把圖片縮放至全螢幕並顯示（主執行緒呼叫）。"""
    global _screen, _screen_size
    if _screen is None:
        return
    try:
        img = pygame.image.load(image_path)
        img = pygame.transform.scale(img, _screen_size)
        _screen.blit(img, (0, 0))
        pygame.display.flip()
    except Exception as e:
        print(f"[顯示錯誤] {e}")


def pump_events():
    """清空 pygame 事件佇列，避免視窗被系統標記為無回應。"""
    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN and event.key == pygame.K_q and (pygame.key.get_mods() & pygame.KMOD_CTRL):
            raise KeyboardInterrupt


def read_barcode_from_events() -> str:
    """
    透過 pygame 事件佇列收集條碼器鍵盤輸入，直到收到 Enter 為止。
    條碼器掃描後會自動送出 Enter，所以這個函式會阻塞直到掃描完成。
    """
    text = ""
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                raise KeyboardInterrupt
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                    raise KeyboardInterrupt
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    return text.strip()
                elif event.key == pygame.K_BACKSPACE:
                    text = text[:-1]
                elif event.unicode and event.unicode.isprintable():
                    text += event.unicode
        time.sleep(0.01)  # 避免 CPU 空轉


# ─────────────────────────────────────────────
#  主程式
# ─────────────────────────────────────────────

if __name__ == "__main__":

    init_display()
    # 確保初始畫面渲染出來
    pygame.event.pump()
    pygame.display.flip()

    print("=== 條碼掃描器已就緒，按 Q 離開 ===")

    try:
        while True:
            ch = read_barcode_from_events()
            if ch == "":
                continue

            print(f"掃到: {ch}")
            current_timestamp = time.time()
            filename = f"code_{int(current_timestamp)}"

            # 1. 生成條碼圖片
            my_code = Code128(ch, writer=ImageWriter())
            my_code.save(filename)
            barcode_png = f"{filename}.png"

            # 2. 合成到模板並全螢幕顯示
            display_path = composite_barcode(barcode_png)
            show_image_on_screen(display_path)

            # 3. 列印
            try:
                #subprocess.run(["lp","-o", "orientation-requested=3" ,"-o", "fit-to-page", display_path])
                subprocess.run(["lp","-o", "orientation-requested=3" ,"-o" , "print-quality=5","-o", "fit-to-page", display_path])
            except Exception as e:
                print(f"[列印錯誤] {e}")
            
            # 4. 播放 MIDI（blocking，但圖已寫入 framebuffer 不受影響）
            mid_out = f"barcode_{filename}.mid"
            try:
                barcode_ascii_to_midi(ch, out_path=mid_out)
                play_with_fluidsynth(mid_path=mid_out)
            except Exception as e:
                print(f"[MIDI 錯誤] {e}")


    except KeyboardInterrupt:
        print("離開。")
    finally:
        pygame.quit()
