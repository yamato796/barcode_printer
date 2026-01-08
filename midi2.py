from dataclasses import dataclass
from typing import List, Tuple
import mido
import pygame
import pygame.midi
import time
import subprocess

@dataclass
class Note:
    pitch: int
    duration_beats: float
    velocity: int = 80


# ---------- 1) 把 ASCII 變成可音樂化的序列 ----------

SCALES = {
    "major":      [0, 2, 4, 5, 7, 9, 11],
    "minor":      [0, 2, 3, 5, 7, 8, 10],
    "pentatonic": [0, 2, 4, 7, 9],
}

def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))

def ascii_to_notes(
    barcode_ascii: str,
    base_note: int = 48,          # C3
    scale: str = "minor",
    unit_beats: float = 0.25,     # 每個字元對應的基本時值(拍)
    min_run: int = 1,
    max_run: int = 12,
) -> List[Note]:
    """
    將條碼機輸出的 ASCII 字串轉成音符序列
    - 先做 run-length encoding（連續相同字元合併）
    - 每段 run 變成一個音符
    - run 長度 -> 音長
    - 字元內容 -> 音高/力度（黑條 vs 空白 做一個簡單區分）
    """
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

        # 你可以依照你實際的 ASCII 格式改這個分類
        # 常見：'|' 或 '1' 表示黑條；空白或 '0' 表示白
        is_bar = ch in ("|", "1", "█", "#", "X", "x")

        # 音高：用字元的 ord + index 來取 scale degree，確保 deterministic
        degree = scale_ints[(ord(ch) + i + run) % len(scale_ints)]

        # 黑條走高八度、力度較大；白條走低一點、力度較小
        pitch = base_note + degree + (12 if is_bar else 0)
        pitch = clamp(pitch, 0, 127)
        velocity = 95 if is_bar else 55

        duration = run * unit_beats
        notes.append(Note(pitch=pitch, duration_beats=duration, velocity=velocity))

    return notes


# ---------- 2) 把音符序列寫成 MIDI 檔 ----------

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
    chord_duration_beats: float = 2.0,   # 合音持續多久
):
    mid = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    track.append(mido.Message("program_change", program=program, channel=channel, time=0))

    # 去重：避免同一個 pitch 重複 note_on（會讓部分音源怪怪的）
    pitches = sorted({n.pitch for n in notes})
    if not pitches:
        raise ValueError("No notes to write")

    # 讓力度取平均（你也可以改 max / min）
    vel = int(sum(getattr(n, "velocity", 80) for n in notes) / len(notes))
    vel = max(1, min(127, vel))

    # 同時 note_on
    first = True
    for p in pitches:
        track.append(mido.Message("note_on", note=p, velocity=vel, channel=channel, time=0 if first else 0))
        first = False

    # 等 chord_duration 後，全部 note_off
    off_time = int(chord_duration_beats * ticks_per_beat)
    first = True
    for p in pitches:
        track.append(mido.Message("note_off", note=p, velocity=0, channel=channel, time=off_time if first else 0))
        first = False

    mid.save(out_path)

# ---------- 3) 一行搞定的 API ----------

def barcode_ascii_to_midi(
    barcode_ascii: str,
    out_path: str = "barcode.mid",
    bpm: int = 120,
    scale: str = "minor",
    base_note: int = 48,
    unit_beats: float = 0.25,
    program: int = 0,
) -> None:
    notes = ascii_to_notes(
        barcode_ascii=barcode_ascii,
        base_note=base_note,
        scale=scale,
        unit_beats=unit_beats,
    )
    if not notes:
        raise ValueError("Input barcode_ascii is empty after stripping newlines.")
    #notes_to_midi_file(notes, out_path, bpm=bpm, program=program)
    notes_to_midi_chord_file(notes, out_path, bpm=bpm, program=program)

def play_with_fluidsynth(mid_path: str, sf2_path: str = "/usr/share/sounds/sf2/FluidR3_GM.sf2"):
    subprocess.run(["fluidsynth","-ni", "-a", "alsa", "-o", "audio.alsa.device=hw:1", "-g", "1.0", sf2_path, mid_path], check=True)

if __name__ == "__main__":
    # 把你那串 ASCII 直接貼在這裡
    #barcode_ascii = "MЗE ODB0A010 00"
    barcode_ascii = "XXXXJ102800309"
    out = "barcode.mid"
    barcode_ascii_to_midi(
        barcode_ascii,
        out_path=out,
        bpm=130,
        scale="pentatonic",
        base_note=50,
        unit_beats=0.25,
        program=81,
    )
    play_with_fluidsynth(mid_path=out)



    print("Wrote barcode.mid")
