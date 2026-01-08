import mido
from mido import MidiFile, MidiTrack, Message
import subprocess

# 1. 設定你的字串
#data_string = "MЗE ODB0A010 00"
data_string = "XXXXJ102800309"
# 2. 建立 MIDI 檔案與軌道
mid = MidiFile()
track = MidiTrack()
mid.tracks.append(track)

# 3. 設定轉換規則 (Mapping)
# 我們將每個字元的編碼轉換成 0-127 的 MIDI 音高
for char in data_string:
    if char == " ":
        # 遇到空白鍵，插入一個短暫的休止符（時間延遲，但不發聲）
        track.append(Message('note_off', note=0, velocity=0, time=240))
    else:
        # 將字元轉為 Unicode 數字，並限制在 0-127 範圍內
        # 如果你希望聲音高一點，可以 +12 或 +24
        note_value = ord(char) % 128
        
        # 確保音高不要太低或太高 (例如限制在 21-108 鋼琴範圍)
        if note_value < 21: note_value += 24
        if note_value > 108: note_value -= 24

        # Note On (發聲), velocity (力度), time (距離上一音的時間)
        track.append(Message('note_on', note=note_value, velocity=80, time=0))
        # Note Off (停聲), 持續時間 240 ticks (約 1/4 拍)
        track.append(Message('note_off', note=note_value, velocity=80, time=240))

# 4. 存檔
out='output_code_sound.mid'
mid.save(out)

def play_with_fluidsynth(mid_path: str, sf2_path: str = "/usr/share/sounds/sf2/FluidR3_GM.sf2"):
    subprocess.run(["fluidsynth","-ni", "-a", "alsa", "-g", "1.0", sf2_path, mid_path], check=True)

play_with_fluidsynth(mid_path=out)
print("MIDI 檔案已生成！")