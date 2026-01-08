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
    
    scale, bpm, base_note, unit_beats, program, chord_duration = params_from_text(ch)

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
    subprocess.run(["fluidsynth","-ni", "-a", "alsa", "-g", "1.0", sf2_path, mid_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == "__main__":

    #barcode_ascii = "MЗE ODB0A010 00"
    #barcode_ascii = "XXXXJ102800309"
    while(True):
        #ch="Test Barcode"
        ch = input('scan barcode\n')
        print(f"{ch}")
        current_timestamp = time.time()
        filename = f"code_{int(current_timestamp)}"
        my_code = Code128(ch, writer=ImageWriter())        
        my_code.save(f"{filename}")
        out = f"barcode_{filename}.mid"

        barcode_ascii_to_midi(
            ch,
            out_path=out,
            bpm=130,
            scale="pentatonic",
            base_note=50,
            unit_beats=0.25,
            program=81,
        )
        play_with_fluidsynth(mid_path=out)

        subprocess.run(["lp", "-o", "fit-to-page", f"./{filename}.png"])
