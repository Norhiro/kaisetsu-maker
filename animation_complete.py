import os
import glob
import requests
import json
import moviepy.editor as mp
#from moviepy.editor import CompositeVideoClip
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import wave
import re
import random
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import filedialog
import ffmpeg
import pandas as pd
import traceback
from scipy.io import wavfile
import shutil

resolution=(1920, 1080)
default_character_order = None


class VoiceGenerator:
    def __init__(self, base_url="http://localhost:50021"):
        self.base_url = base_url

    def generate_voice(self, text, speaker_id=1, output_path="temp/output.wav"):
        print("Generating voice")
        params = {
            "text": text,
            "speaker": speaker_id
        }
        query = requests.post(f"{self.base_url}/audio_query", params=params)
        if query.status_code != 200:
            raise Exception(f"VoiceVox API query error: {query.status_code}")

        synthesis = requests.post(f"{self.base_url}/synthesis", params={"speaker": speaker_id}, data=query.content)
        if synthesis.status_code != 200:
            raise Exception(f"VoiceVox API synthesis error: {synthesis.status_code}")

        with open(output_path, "wb") as f:
            f.write(synthesis.content)

        return output_path

    def get_audio_duration(self, audio_path):
        with wave.open(audio_path, 'r') as audio_file:
            frames = audio_file.getnframes()
            rate = audio_file.getframerate()
            duration = frames / float(rate)
        return duration

class ImageProcessor:
    def __init__(self, resolution=(1920, 1080)):
        self.resolution = resolution

    def check_alpha_channel(self, image_path):
        image = Image.open(image_path).convert("RGBA")
        np_image = np.array(image)
        alpha_channel = np_image[:, :, 3]
        unique_alpha_values = np.unique(alpha_channel)
        print(f"Unique alpha values in the image {image_path}: {unique_alpha_values}")

    def resize_image(self, image_path, height):
        image = Image.open(image_path).convert("RGBA")
        return image.resize((int(image.width * (height / image.height)), height))

class Animator:
    def __init__(self, character='ずんだもん', speaker=1, resolution=resolution):
        self.character = character
        self.speaker = speaker
        self.fps = 24
        self.resolution = resolution
        self.images = self.load_images(character)
        self.voice_generator = VoiceGenerator()
        self.image_processor = ImageProcessor(resolution)
        self.clip_counter = 0
        os.makedirs('json', exist_ok=True)
        os.makedirs('video', exist_ok=True)


    def add_text(self, image, text, font_size, font_color, border_color, position):
        draw = ImageDraw.Draw(image)
        #font_path = "arial.ttf"  # フォントファイルへのパスを指定
        font_path = "font/NotoSansJP-Medium.otf"  #"arial.ttf"  # フォントファイルへのパスを指定
        font = ImageFont.truetype(font_path, font_size)
        
        lines = text.split('\n')
        max_width = 0
        total_height = 0
        
        for line in lines:
            text_bbox = draw.textbbox((0, 0), line, font=font)
            text_width, text_height = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
            if text_width > max_width:
                max_width = text_width
            total_height += text_height
        
        width, height = image.size
        
        if position == "center":
            y_offset = (height - total_height) / 2
        elif position == "bottom":
            y_offset = height - total_height - 50
        else:
            y_offset = 10  # デフォルトの位置（左上）
        
        for line in lines:
            text_bbox = draw.textbbox((0, 0), line, font=font)
            text_width, text_height = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
            if position == "center":
                x = (width - text_width) / 2
            elif position == "bottom":
                x = (width - text_width) / 2
            else:
                x = 10  # デフォルトの位置（左上）

            # テキストの縁取り
            draw.text((x-1, y_offset-1), line, font=font, fill=border_color)
            draw.text((x+1, y_offset-1), line, font=font, fill=border_color)
            draw.text((x-1, y_offset+1), line, font=font, fill=border_color)
            draw.text((x+1, y_offset+1), line, font=font, fill=border_color)
            
            # テキスト本体
            draw.text((x, y_offset), line, font=font, fill=font_color)
            
            y_offset += text_height
        
        return image
      

    def load_images(self, character):
        image_sets = {
            'ずんだもん': {
                'normal': "zundamon_normal.png",
                'open_eye_close_mouth': "zundamon_normal.png",
                'open_eye_mid_mouth': "zundamon_mouth_mid.png",
                'open_eye_open_mouth': "zundamon_mouth_open.png",
                'close_eye_close_mouth': "zundamon_mouth_close_eye_close.png",
                'close_eye_mid_mouth': "zundamon_mouth_mid_eye_close.png",
                'close_eye_open_mouth': "zundamon_mouth_open_eye_close.png"
            },
            '四国めたん': {
                'normal': "metan_normal.png",
                'open_eye_close_mouth': "metan_normal.png",
                'open_eye_mid_mouth': "metan_mouth_mid.png",
                'open_eye_open_mouth': "metan_mouth_open.png",
                'close_eye_close_mouth': "metan_mouth_close_eye_close.png",
                'close_eye_mid_mouth': "metan_mouth_mid_eye_close.png",
                'close_eye_open_mouth': "metan_mouth_open_eye_close.png"
            }
        }
        return image_sets.get(character, image_sets[character])

    def get_audio_volume(self, audio_path):
        rate, data = wavfile.read(audio_path)
        duration = len(data) / rate
        frame_count = int(duration * self.fps)
        volumes = []
        frame_size = int(rate / self.fps)
        for i in range(frame_count):
            start = i * frame_size
            end = start + frame_size
            volume = np.abs(data[start:end]).mean()
            volumes.append(volume)
        return volumes, duration

    def create_silence(self, duration, fps):
        return mp.AudioClip(lambda t: [0, 0], duration=duration).set_fps(fps)

    def create_animation(self, text, position="center", speaker_id=1, volume=1.0, silent=False, title_settings=None, subtitle_settings=None):
        print("Starting to create animation")
        segments = re.split(r'(\d+)', text)
        audio_clips = []
        total_duration = 0
        default_pause = 5
        font_path = "font/NotoSansJP-Medium.otf"


        for segment in segments:
            segment = segment.strip()
            if segment.isdigit():
                pause_duration = int(segment)
                silence_clip = self.create_silence(pause_duration, 44100)
                audio_clips.append(silence_clip)
                total_duration += pause_duration
            elif segment:
                print(f"Generating voice for segment: {segment}")
                audio_file = self.voice_generator.generate_voice(segment, speaker_id, f"temp/audio_{self.clip_counter}.wav")
                audio_clip = mp.AudioFileClip(audio_file)
                audio_clips.append(audio_clip)
                total_duration += audio_clip.duration
                silence_clip = self.create_silence(default_pause, 44100)
                audio_clips.append(silence_clip)
                total_duration += default_pause
                self.clip_counter += 1

        final_audio = mp.concatenate_audioclips(audio_clips)

        final_audio_path = "final_audio.wav"
        final_audio.write_audiofile(final_audio_path)
        volumes, _ = self.get_audio_volume(final_audio_path)
        total_duration = final_audio.duration

        blink_times = sorted(random.sample(range(int(total_duration * self.fps)), int(total_duration)))

        def make_frame(t):
            frame = int(t * self.fps)
            volume = volumes[frame] if frame < len(volumes) else 0

            if volume < 1000:
                if frame in blink_times:
                    image = self.images['close_eye_close_mouth']
                else:
                    image = self.images['normal']
            elif volume < 3000:
                if frame in blink_times:       
                    image = self.images['close_eye_mid_mouth']
                else:
                    image = self.images['open_eye_mid_mouth']
            else:
                if frame in blink_times:
                    image = self.images['close_eye_open_mouth']
                else:
                    image = self.images['open_eye_open_mouth']

            image = "image/" + image 
            img = Image.open(image).convert("RGBA")
            img_resized = img.resize((int(img.width * (self.resolution[1] / img.height)), self.resolution[1]), Image.Resampling.LANCZOS)

            # 背景の透過PNGをキャラクター画像と同じサイズで作成
            transparent_bg = Image.new('RGBA', img_resized.size, (0, 0, 0, 0))

            # 背景とキャラクター画像を合成
            combined = Image.alpha_composite(transparent_bg, img_resized)

            # タイトルとサブタイトルの追加（原画の上に文字の表示がある）
            #if title_settings and title_settings["start_time"] <= t <= title_settings["start_time"] + title_settings["duration"]:
            #    combined = self.add_text(combined, title_settings["text"], title_settings["font_size"], title_settings["font_color"], title_settings["border_color"], position="center")
            
            #if subtitle_settings and subtitle_settings["start_time"] <= t <= subtitle_settings["start_time"] + subtitle_settings["duration"]:
            #    combined = self.add_text(combined, subtitle_settings["text"], subtitle_settings["font_size"], subtitle_settings["font_color"], subtitle_settings["border_color"], position="bottom")

            return combined

        pngs = []    
        for t in np.arange(0, total_duration, 1 / self.fps):
            frame = make_frame(t)
            frame_path = f'temp/frame_{int(t * self.fps):04d}.png'
            frame.save(frame_path)
            pngs.append(frame_path)

        video = mp.ImageSequenceClip(pngs, fps=self.fps)

        video = video.set_audio(final_audio)
        video = video.set_fps(self.fps)

        # キャラクターの位置を設定
        if position == "left_25":
            x_pos = int(self.resolution[0] * 0.25 - video.size[0] / 2)
            video = video.set_position((x_pos, 'center'))
        elif position == "right_25":
            x_pos = int(self.resolution[0] * 0.75 - video.size[0] / 2)
            video = video.set_position((x_pos, 'center'))
        elif position == "left_10":
            x_pos = int(self.resolution[0] * 0.10 - video.size[0] / 2)
            video = video.set_position((x_pos, 'center'))
        elif position == "right_10":
            x_pos = int(self.resolution[0] * 0.90 - video.size[0] / 2)
            video = video.set_position((x_pos, 'center'))
        elif position == "hidden":
            video = video.set_opacity(0)
        else:
            video = video.set_position('center')

        # JSONファイルの連番を取得
        existing_json_files = glob.glob('json/output_*.json')
        json_file_number = len(existing_json_files) + 1

        # 動画ファイルのパスを設定
        mov_file = f'video/output_{json_file_number}.mov'
        mp4_file = f'video/output_{json_file_number}.mp4'

        # Create transparent MOV file
        bgpng = 'temp/bg.png'
        bgmov = 'temp/bg.mov'
        img = Image.new('RGBA', (self.resolution[0], self.resolution[1]), (0, 0, 0, 0))
        img.save(bgpng)
        print("Running ffmpeg process for background")
        process = (
            ffmpeg
            .input(bgpng, loop=1, framerate=self.fps)
            .output(bgmov, vcodec='qtrle', t=total_duration, pix_fmt='argb', r=self.fps)
            .run()
        )

        background_clip = mp.VideoFileClip(bgmov, has_mask=True).set_duration(total_duration)
        final_clip = mp.CompositeVideoClip([background_clip, video], size=self.resolution)
       
          # タイトルとサブタイトルの追加
        if title_settings['text'] != "":
            title_clip = mp.TextClip(
                title_settings["text"], fontsize=title_settings["font_size"], color=title_settings["font_color"], bg_color='transparent', 
                font=font_path, size=(self.resolution[0], None), 
                stroke_color=title_settings["border_color"],
                method='caption'
            ).set_position('center').set_duration(title_settings["duration"]).set_start(title_settings["start_time"])

            final_clip = mp.CompositeVideoClip([final_clip, title_clip], size=self.resolution)

        if subtitle_settings['text'] != "":
            subtitle_clip = mp.TextClip(
                subtitle_settings["text"], fontsize=subtitle_settings["font_size"], color=subtitle_settings["font_color"], bg_color='transparent', font=font_path, size=(self.resolution[0], None), method='caption'
            ).set_position(('center', 'bottom')).set_duration(subtitle_settings["duration"]).set_start(subtitle_settings["start_time"])
            final_clip = mp.CompositeVideoClip([final_clip, subtitle_clip], size=self.resolution)

        final_clip.write_videofile(mov_file, codec="qtrle", fps=self.fps)

        # Create gray background MP4 file
        gray_bg = mp.ColorClip(size=self.resolution, color=(128, 128, 128)).set_duration(total_duration).set_fps(self.fps)
        final_clip_with_gray_bg = mp.CompositeVideoClip([gray_bg, video], size=self.resolution)
        final_clip_with_gray_bg.write_videofile(mp4_file, codec="libx264", fps=self.fps, ffmpeg_params=["-pix_fmt", "yuv420p"])

        #レイヤ
        global default_character_order
        if default_character_order is None:
            default_character_order = {self.character: 1}
            layer = 1
        elif self.character in default_character_order:
            layer = default_character_order[self.character]
        else:
            layer = max(default_character_order.values()) +1
            default_character_order.setdefault(self.character, layer)

        # JSONファイルの作成
        json_data = {
            "mov_file": mov_file,
            "mp4_file": mp4_file,
            "text": text,
            "layer": layer,
            "position": position,
            "start_time": 0,
            "duration": total_duration,
            "volume": volume,
            "character": self.character,
            "speaker_id": speaker_id,
            "title_settings": title_settings,
            "subtitle_settings": subtitle_settings
        }
    
        json_output_path = f'json/output_{json_file_number}.json'
    
        with open(json_output_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)

        return mov_file, mp4_file

class AnimationGUI:
    def __init__(self, root):
        print("Initializing GUI")
        self.root = root
        self.root.title("アニメーション生成 GUI")

        #self.tree_insert = None
        self.tree_insert = []
        self.bg_tree_insert = []
        self.cell_value = None 

        self.character_data = {
            "ずんだもん": {
                "ノーマル": 3,
                "あまあま": 1,
                "ツンツン": 7,
                "セクシー": 5,
                "ささやき": 22,
                "ヒソヒソ": 38,
                "ヘロヘロ": 75,
                "なみだめ": 76
            },
            "四国めたん": {
                "ノーマル": 2,
                "あまあま": 0,
                "ツンツン": 6,
                "セクシー": 4,
                "ささやき": 36,
                "ヒソヒソ": 37
            }
        }

        self.layer_options = [[1 ,"一番前"],[2  ,"2番目"],[3 ,"3番目"],[4  ,"4番目"],[5 ,"5番目"]]

        self.animator = Animator()
        self.create_widgets()
        self.load_existing_json_files()

        # Treeviewにダブルクリックイベントをバインド
        self.tree.bind("<Double-1>", self.on_double_click)

    def create_widgets(self):
        print("Creating widgets")
        frame = ttk.Frame(self.root, padding="10")
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        ttk.Label(frame, text="キャラクター").grid(row=0, column=0)
        self.character_var = tk.StringVar()
        self.character_menu = ttk.Combobox(frame, textvariable=self.character_var, state="readonly")
        self.character_menu["values"] = list(self.character_data.keys())
        self.character_menu.grid(row=0, column=1)
        self.character_menu.bind("<<ComboboxSelected>>", self.update_style_menu)

        ttk.Label(frame, text="声色").grid(row=1, column=0)
        self.style_var = tk.StringVar()
        self.style_menu = ttk.Combobox(frame, textvariable=self.style_var, state="readonly")
        self.style_menu.grid(row=1, column=1)

        ttk.Label(frame, text="セリフ").grid(row=2, column=0)
        self.text_entry = tk.Text(frame, height=5, width=60)
        self.text_entry.grid(row=2, column=1, columnspan=5, sticky=tk.W)

        ttk.Label(frame, text="横位置").grid(row=3, column=0)
        self.position_var = tk.StringVar(value="center")
        position_options = ["hidden", "left_10", "left_25", "center", "right_25", "right_10"]
        for i, position in enumerate(position_options):
            ttk.Radiobutton(frame, text=position, variable=self.position_var, value=position).grid(row=3, column=i+1, sticky=tk.W)

        ttk.Label(frame, text="開始タイミング (秒)").grid(row=4, column=0)
        self.start_time_entry = ttk.Entry(frame)
        self.start_time_entry.grid(row=4, column=1)

        ttk.Label(frame, text="ボリューム").grid(row=5, column=0)
        self.volume_entry = ttk.Entry(frame)
        self.volume_entry.grid(row=5, column=1)
        self.volume_entry.insert(0, "1.0")

        self.silence_button = ttk.Button(frame, text="無音", command=self.set_silence)
        self.silence_button.grid(row=5, column=2)
        self.silence_entry = ttk.Entry(frame)
        self.silence_entry.grid(row=5, column=3)
        self.silence_entry.insert(0, "5.0")
        ttk.Label(frame, text="無音アニメーションの秒数指定　指定なしだと5秒").grid(row=5, column=4, sticky=tk.W)

        # タイトル設定ウィジェット
        ttk.Label(frame, text="タイトル").grid(row=6, column=0)
        self.title_text = tk.Text(frame, height=2, width=60)
        self.title_text.grid(row=6, column=1, columnspan=5, sticky=tk.W)

        ttk.Label(frame, text="タイトルフォントサイズ").grid(row=7, column=0)
        self.title_font_size = ttk.Entry(frame)
        self.title_font_size.grid(row=7, column=1)
        self.title_font_size.insert(0, "40")

        ttk.Label(frame, text="タイトルフォント色").grid(row=7, column=2)
        self.title_font_color = ttk.Entry(frame)
        self.title_font_color.grid(row=7, column=3)
        self.title_font_color.insert(0, "white")

        ttk.Label(frame, text="タイトル縁取り色").grid(row=7, column=4)
        self.title_border_color = ttk.Entry(frame)
        self.title_border_color.grid(row=7, column=5)
        self.title_border_color.insert(0, "black")

        ttk.Label(frame, text="タイトル開始タイミング (秒)").grid(row=8, column=0)
        self.title_start_time = ttk.Entry(frame)
        self.title_start_time.grid(row=8, column=1)
        self.title_start_time.insert(0, "0")

        ttk.Label(frame, text="タイトルduration (秒)").grid(row=8, column=2)
        self.title_duration = ttk.Entry(frame)
        self.title_duration.grid(row=8, column=3)
        self.title_duration.insert(0, "5")

        # サブタイトル設定ウィジェット
        ttk.Label(frame, text="サブタイトル").grid(row=9, column=0)
        self.subtitle_text = tk.Text(frame, height=2, width=60)
        self.subtitle_text.grid(row=9, column=1, columnspan=5, sticky=tk.W)

        ttk.Label(frame, text="サブタイトルフォントサイズ").grid(row=10, column=0)
        self.subtitle_font_size = ttk.Entry(frame)
        self.subtitle_font_size.grid(row=10, column=1)
        self.subtitle_font_size.insert(0, "30")

        ttk.Label(frame, text="サブタイトルフォント色").grid(row=10, column=2)
        self.subtitle_font_color = ttk.Entry(frame)
        self.subtitle_font_color.grid(row=10, column=3)
        self.subtitle_font_color.insert(0, "white")

        ttk.Label(frame, text="サブタイトル縁取り色").grid(row=10, column=4)
        self.subtitle_border_color = ttk.Entry(frame)
        self.subtitle_border_color.grid(row=10, column=5)
        self.subtitle_border_color.insert(0, "black")

        ttk.Label(frame, text="サブタイトル開始タイミング (秒)").grid(row=11, column=0)
        self.subtitle_start_time = ttk.Entry(frame)
        self.subtitle_start_time.grid(row=11, column=1)
        self.subtitle_start_time.insert(0, "0")

        ttk.Label(frame, text="サブタイトルduration (秒)").grid(row=11, column=2)
        self.subtitle_duration = ttk.Entry(frame)
        self.subtitle_duration.grid(row=11, column=3)
        self.subtitle_duration.insert(0, "5")

        self.generate_button = ttk.Button(frame, text="アニメーション生成", command=self.generate_animation)
        self.generate_button.grid(row=12, column=0, columnspan=2)

        self.upload_bg_button = ttk.Button(frame, text="背景アップロード", command=self.upload_background)
        self.upload_bg_button.grid(row=12, column=2, columnspan=2)

        # 動画を重ね合わせるボタンを追加
        self.combine_button = ttk.Button(frame, text="動画を重ね合わせる", command=self.combine_videos)
        self.combine_button.grid(row=12, column=4, columnspan=2)

        #キャラクターTree
        columns=(["キャラクター","キャラクター", 100],
                ["声色", "声色", 100],                      
                ["セリフ", "セリフ", 100],
                ["layer","layer",100],
                ["横位置", "横位置", 100],
                ["開始タイミング", "開始タイミング", 100],
                ["duration", "duration", 100],
                ["ボリューム", "ボリューム", 100],
                ["filename","filename",100])
        column = [a[0] for a in columns] 
        self.tree = ttk.Treeview(frame, columns=column, show="headings")
        for col in columns:
            self.tree.heading(col[0], text=col[1])
            self.tree.column(col[0], width=col[2])  # 適切な幅に調整
        self.tree.grid(row=13, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")
        
        self.bg_tree = ttk.Treeview(frame, columns=("開始タイミング", "duration", "ファイル名"), show="headings")
        self.bg_tree.heading("開始タイミング", text="開始タイミング")
        self.bg_tree.heading("duration", text="duration")
        self.bg_tree.heading("ファイル名", text="ファイル名")
        self.bg_tree.grid(row=14, column=0, columnspan=7, pady=10)
        self.root.after(100, self.add_layer_dropdowns) #00ミリ秒）を置いて指定したメソッド（self.add_layer_dropdowns）を呼び出す　

    def open_layer_menu(self, item_id, column, x, y): 
        # 現在の値を取得
        value = self.tree.item(item_id, "values")
        current_value = self.tree.item(item_id, "values")[3]
        # ポップアップメニューを作成
        popup_menu = tk.Menu(self.root, tearoff=0)
        for option in self.layer_options:
            # 現在の値と同じオプションには特別なマークをつけるか、異なるスタイルを適用
            if option[1] == current_value:
                popup_menu.add_command(label=option[1] + " (current)", command=lambda opt=option: self.set_layer_value(item_id, column, opt, value))
            else:
                popup_menu.add_command(label=option[1], command=lambda opt=option: self.set_layer_value(item_id, column, opt, value))
    
        # メニューを表示
        popup_menu.tk_popup(x, y)

    def set_layer_value(self, item_id, column, opt, value):
        value = list(value)
        value[3] = opt[1]
        filename = 'json/'+ value[-1]
        with open(filename, 'r') as file:
            data = json.load(file)
        data.update(layer = opt[0])        
        # Treeviewを更新
        self.tree.item(item_id, values=value)

    def add_layer_dropdowns(self):
        for row in self.tree.get_children():
            values = self.tree.item(row)["values"]
            self.add_layer_dropdown(row, values)
    def add_layer_dropdown(self, row, values):

        layer_var = tk.StringVar(value=self.layer_options[int(values[3]) - 1][1])
    
        def update_layer(*args):
            for i, item in enumerate(self.layer_options):
                if item[1] == layer_var.get():
                    ind = i 
            self.tree.set(row, "layer", str(ind + 1 ))

        layer_var.trace_add("write", update_layer)
        layer_menu = ttk.OptionMenu(self.tree, layer_var, layer_var.get(), *self.layer_options)
        self.tree.set(row, "layer", layer_var.get())
    
        # レイヤードロップダウンをTreeviewに追加
        # Treeviewのアイテム位置を取得して、プルダウンメニューを配置
        bbox = self.tree.bbox(row, column=3)
        if bbox:
            layer_menu.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])


    def on_character_change(self, event):
        current_character = self.character_var.get()
        menu = self.style_menu["menu"]
        menu.delete(0, "end")
        for style in self.character_data[current_character].keys():
            menu.add_command(label=style, command=lambda value=style: self.style_var.set(value))


    def on_double_click(self, event):
        item_id = self.tree.identify_row(event.y)  # クリックされた行のIDを取得
        column_id = self.tree.identify_column(event.x)  # クリックされた列のIDを取得
        m = re.findall(r'\d+', item_id)
        m = int(''.join(m)) -1
        cell_value = self.tree_insert[m]
        if column_id == "#8":
            self.file_popup(cell_value)
        elif column_id == "#4":
            self.open_layer_menu(item_id, column_id, event.x_root, event.y_root)
        else:
            self.show_popup(cell_value)

    def file_popup(self, cell_value):
        print("File popup")
        popup = tk.Toplevel(self.root)
        popup.title("ポップアップ")
        ttk.Label(popup, text=f"選択された値: {cell_value}").pack(padx=10, pady=10)
        popup.transient(self.root)
        popup.grab_set()
        self.root.wait_window(popup)

    def delete_animation(self):
        print("Deleting animation")
        current_item = self.tree.focus()
        if not current_item:
            messagebox.showerror("エラー", "削除するアイテムが選択されていません。")
            return

        prev_values = self.tree.item(current_item)["values"]
        self.tree.delete(current_item)

        json_file_path = os.path.join('json', self.cell_value[-1])
        data = self.load_json_file(json_file_path)

        if data is not None:
            #data["character"] = character
            #data["speaker_id"] = speaker_id
            #data["text"] = text
            #data["position"] = position
            data["start_time"] = float(-1)
            #data["duration"] = float(duration)
            #data["volume"] = float(volume)
            with open(json_file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

        messagebox.showinfo("完了", "アニメーションが削除されました。")
        self.popup.destroy()

    def update_animation(self):
        print("Updating animation")

        duration = self.duration_entry.get()
        position = self.position_var.get()
        character = self.character_var_popup.get()
        style = self.style_var_popup.get()
        text = self.text_entry.get("1.0", "end-1c")
        volume = self.volume_entry.get()
        start_time = self.start_time_entry.get()
        layer = self.layer_entry.get()

        if not duration:
            messagebox.showerror("エラー", "アニメーションの秒数を入力してください。")
            return

        current_item = self.tree.focus()
        if not current_item:
            messagebox.showerror("エラー", "修正するアイテムが選択されていません。")
            return

        prev_values = self.tree.item(current_item)["values"]
        filename = prev_values[-1]
        speaker_id = self.character_data[character][style]

        new_values = (character, style, text, layer, position, start_time, duration, volume, filename)
        self.tree.item(current_item, values=new_values)                                                
        tree_data = []
        for item in self.tree.get_children():
            row = self.tree.item(item)["values"]
            tree_data.append(row)

        df = pd.DataFrame(self.tree_insert, columns=['character', 'style', 'text', 'layer', 'position', 'start_time', 'duration', 'volume', 'filename'])
        df = df.sort_values(by='start_time')
        self.tree_insert = df.values.tolist()
  
        for ins in self.tree_insert:
            self.tree.insert("", "end", values=ins)

        json_file_path = os.path.join('json', self.cell_value[-1])
        data = self.load_json_file(json_file_path)

        if data is not None:
            data["character"] = character
            data["speaker_id"] = speaker_id
            data["text"] = text
            data["position"] = position
            data["start_time"] = float(start_time)
            data["duration"] = float(duration)
            data["volume"] = float(volume)
            data["layer"] = int(layer)
            with open(json_file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

        messagebox.showinfo("完了", "アニメーションが修正されました。")
        self.popup.destroy()

    def update_style_menu_popup(self, event):
        print("Updating style menu for popup")
        character = self.character_var_popup.get()
        styles = self.character_data.get(character, {})
        self.style_menu_popup["values"] = list(styles.keys())
        self.style_menu_popup.set("")

    def show_popup(self, cell_value):
        print("Show popup")
        self.popup = tk.Toplevel(self.root)
        self.popup.title("修正")

        ttk.Label(self.popup, text="キャラクター").grid(row=0, column=0, sticky=tk.W)
        self.character_var_popup = tk.StringVar(value=cell_value[0])
        self.character_menu_popup = ttk.Combobox(self.popup, textvariable=self.character_var_popup, state="readonly")
        self.character_menu_popup["values"] = list(self.character_data.keys())
        self.character_menu_popup.grid(row=0, column=1)
        self.character_menu_popup.bind("<<ComboboxSelected>>", self.update_style_menu_popup)

        ttk.Label(self.popup, text="声色").grid(row=1, column=0, sticky=tk.W)
        self.style_var_popup = tk.StringVar(value=cell_value[1])
        self.style_menu_popup = ttk.Combobox(self.popup, textvariable=self.style_var_popup, state="readonly")
        self.style_menu_popup.grid(row=1, column=1)

        character = self.character_var_popup.get()
        styles = self.character_data.get(character, {})
        self.style_menu_popup["values"] = list(styles.keys())
        self.style_menu_popup.set(cell_value[1])

        ttk.Label(self.popup, text="セリフ").grid(row=2, column=0, sticky=tk.W)
        self.text_entry = tk.Text(self.popup, height=5, width=60)
        self.text_entry.grid(row=2, column=1, columnspan=5, sticky=tk.W)
        self.text_entry.insert("1.0", cell_value[2])

        ttk.Label(self.popup, text="位置選択").grid(row=3, column=0, sticky=tk.W)
        self.position_var = tk.StringVar(value=cell_value[4])
        position_options = ["hidden", "left_10", "left_25", "center", "right_25", "right_10"]
        for i, position in enumerate(position_options):
            ttk.Radiobutton(self.popup, text=position, variable=self.position_var, value=position).grid(row=3, column=i+1, sticky=tk.W)

        ttk.Label(self.popup, text="レイヤ").grid(row=4, column=0, sticky=tk.W)
        self.layer_entry = ttk.Entry(self.popup)
        self.layer_entry.grid(row=4, column=1)
        self.layer_entry.insert(0, cell_value[3])

        ttk.Label(self.popup, text="開始タイミング (秒)").grid(row=5, column=0, sticky=tk.W)
        self.start_time_entry = ttk.Entry(self.popup)
        self.start_time_entry.grid(row=5, column=1)
        self.start_time_entry.insert(0, cell_value[5])

        ttk.Label(self.popup, text="アニメーションの秒数").grid(row=6, column=0, sticky=tk.W)
        self.duration_entry = ttk.Entry(self.popup)
        self.duration_entry.grid(row=6, column=1)
        self.duration_entry.insert(0, cell_value[6])

        ttk.Label(self.popup, text="ボリューム").grid(row=7, column=0, sticky=tk.W)
        self.volume_entry = ttk.Entry(self.popup)
        self.volume_entry.grid(row=7, column=1)
        self.volume_entry.insert(0, cell_value[7])

        self.cell_value = cell_value
        self.ok_button = ttk.Button(self.popup, text="修正", command=self.update_animation)
        self.ok_button.grid(row=9, column=0, columnspan=1)

        self.del_button = ttk.Button(self.popup, text="削除", command=self.delete_animation)
        self.del_button.grid(row=9, column=1, columnspan=1)

    def add_animation(self):
        print("Adding animation")
        duration = self.duration_entry.get()
        position = self.position_var.get()
        character = self.character_var_popup.get()
        style = self.style_var_popup.get()
        starttime = self.start_time_entry.get()
        if not duration:
            messagebox.showerror("エラー", "アニメーションの秒数を入力してください。")
            return

        current_item = self.tree.focus()
        if not current_item:
            messagebox.showerror("エラー", "無音アニメーションを追加する前に、少なくとも1つのアニメーションを生成してください。")
            return

        prev_values = self.tree.item(current_item)["values"]
        start_time = prev_values[4]

        speaker_id = self.character_data[character][style]
        new_start_time = float(start_time) + float(prev_values[5])


        json_file = self.animator.create_animation(
            text="", position=position, silent=True, duration=float(duration), speaker_id=speaker_id
        )

        json_file_path = os.path.join('json', json_file)
        data = self.load_json_file(json_file_path)

        if data is not None:
            data["start_time"] = new_start_time
            with open(json_file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

        self.tree.insert("", "end", values=(character, style, "無音", position, new_start_time, duration))
        messagebox.showinfo("完了", "無音アニメーションが追加されました。")
        self.popup.destroy()


    def upload_background(self):
        file_path = filedialog.askopenfilename(
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg"),
                ("Video files", "*.mp4 *.mov"),
                ("All files", "*.*")
            ]
        )
        if file_path:
            self.save_background(file_path)

            if file_path.endswith(".mp4") or file_path.endswith(".mov"):
                clip = mp.VideoFileClip(file_path)
                duration = clip.duration
                fps = clip.fps
                width, height = clip.size

            # JSONファイルの作成
            json_data = {
                "backgroudn_file": os.path.basename(file_path),
                "start_time": 0,
                "duration": duration,
            }

            # JSONファイルの連番を取得
            existing_bg_files = glob.glob('json/background_*.json')
            json_bg_number = len(existing_bg_files) + 1
            json_output_path = f'json/background_{json_bg_number}.json'

            with open(json_output_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)

    def save_background(self, file_path):
        if not os.path.exists('./source'):
            os.makedirs('./source')
        shutil.copy(file_path, './source')
        print(f"Background file {file_path} uploaded to ./source")

    def set_silence(self):
        print("Setting silence")
        self.volume_entry.delete(0, tk.END)
        self.volume_entry.insert(0, "0")

    def update_style_menu(self, event):
        print("Updating style menu")
        character = self.character_var.get()
        styles = self.character_data.get(character, {})
        self.style_menu["values"] = list(styles.keys())
        self.style_menu.set("")

    def load_json_file(self, filepath):
        if not os.path.isfile(filepath):
            print(f"File does not exist: {filepath}")
            return None
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content:
                    print(f"File is empty: {filepath}")
                    return None
            return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"JSON decode error in file {filepath}: {e}")
            return None

    def clear_temp_folder(self):
        temp_files = glob.glob('temp/*')
        for file in temp_files:
            os.remove(file)

    def generate_animation(self):
        print("Generating animation")
        try:
            character = self.character_var.get()
            speaker_id = self.character_data[character][self.style_var.get()]
            text = self.text_entry.get("1.0", "end-1c")
            position = self.position_var.get()
            volume = float(self.volume_entry.get())

            # Animatorクラスのインスタンスを作成し、キャラクターとスピーカーIDを渡す
            self.animator = Animator(character=character, speaker=speaker_id)

            start_time = 0
            valid_items = []
            for item in self.tree.get_children():
                item_data = self.tree.item(item, "values")
                if float(item_data[5]) >= 0:  # 開始タイミングが0以上のアイテムのみを追加
                    valid_items.append(item_data)

            # valid_itemsを開始タイミングでソート
            valid_items.sort(key=lambda x: float(x[5]))

            silent = False
            if volume == 0:
                silent = True

            print(f"Creating animation: character={character}, speaker_id={speaker_id}, text={text}, position={position}, volume={volume}, silent={silent}")
            title_settings = None
            subtitle_settings= None
            mov_file, mp4_file = self.animator.create_animation(
                text=text, position=position, volume=volume, silent=silent, speaker_id=speaker_id,
                title_settings={
                    "text": self.title_text.get("1.0", "end-1c").strip(),
                    "font_size": int(self.title_font_size.get()),
                    "font_color": self.title_font_color.get(),
                    "border_color": self.title_border_color.get(),
                    "start_time": float(self.title_start_time.get()),
                    "duration": float(self.title_duration.get()),
                },
                subtitle_settings={
                    "text": self.subtitle_text.get("1.0", "end-1c").strip(),
                    "font_size": int(self.subtitle_font_size.get()),
                    "font_color": self.subtitle_font_color.get(),
                    "border_color": self.subtitle_border_color.get(),
                    "start_time": float(self.subtitle_start_time.get()),
                    "duration": float(self.subtitle_duration.get()),
                }
            )

            json_file_path = os.path.join('json', f'output_{self.animator.clip_counter - 1}.json')
            print(f"Attempting to load JSON file from: {json_file_path}")
            data = self.load_json_file(json_file_path)

            if data is not None:
                data["start_time"] = start_time
                data["title_settings"] = title_settings
                data["subtitle_settings"] = subtitle_settings
                with open(json_file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)

            print(f"temp/audio_{self.animator.clip_counter - 1}.wav")
            duration = VoiceGenerator().get_audio_duration(f"temp/audio_{self.animator.clip_counter - 1}.wav")
            for item_data in valid_items:
                self.tree.insert("", "end", values=item_data)
            self.tree.update()

            # JSONファイルの内容をツリーに反映
            self.update_tree_from_json()    

            self.clear_temp_folder()

            messagebox.showinfo("Success", f"Animations created: {mov_file}, {mp4_file}")

        except Exception as e:
            error_message = traceback.format_exc()
            print(error_message)
            messagebox.showerror("Error", error_message)

    def update_tree_from_json(self):
        # 既存のアイテムを削除
        for item in self.tree.get_children():
            self.tree.delete(item)
        for item in self.bg_tree.get_children():
            self.bg_tree.delete(item)

        self.tree_insert = []
        self.bg_tree_insert = []

        # JSONファイルを読み込んでツリーに追加
        json_files = sorted(glob.glob('json/output_*.json'), key=os.path.getmtime)
        for json_file in json_files:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                file = os.path.basename(json_file)
            
                values = (
                    data.get("character", ""),
                    data.get("speaker_id", ""),
                    data.get("text", ""),
                    data.get("layer", 1),
                    data.get("position", ""),
                    data.get("start_time", 0),
                    data.get("duration", 0),
                    data.get("volume", 1.0),
                    file,
                )
                self.tree_insert.append(values)
                self.tree.insert("", "end", values=values)

        bg_files = sorted(glob.glob('json/background_*.json'), key=os.path.getmtime)
        for bg_file in bg_files:
            with open(bg_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                values = (
                    data.get("start_time", 0),
                    data.get("duration", 0),
                    data.get("backgroudn_file", ""),
                )
                self.bg_tree_insert.append(values)
                self.bg_tree.insert("", "end", values=values)

        self.tree.update()
        self.bg_tree.update()
        self.root.after(100, self.add_layer_dropdowns)  # 100ミリ秒後にadd_layer_dropdownsメソッドを呼び出す
    """
    def update_tree_from_json(self): 
        # 既存のアイテムを削除
        for item in self.tree.get_children():
            self.tree.delete(item)

        # JSONファイルを読み込んでツリーに追加
        json_files = sorted(glob.glob('json/output_*.json'), key=os.path.getmtime)
        for json_file in json_files:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                file = os.path.basename(json_file)
                
                values = (
                    data.get("character", ""),
                    data.get("speaker_id", ""),
                    data.get("text", ""),
                    data.get("layer", 1),
                    data.get("position", ""),
                    data.get("start_time", 0),
                    data.get("duration", 0),
                    data.get("volume", 1.0),
                    file,
                    #data.get("title_settings", ""),
                    #data.get("subtitle_settings", ""),
                )
                self.tree.insert("", "end", values=values)
                
        self.tree.update()
        self.root.after(100, self.add_layer_dropdowns) #00ミリ秒）を置いて指定したメソッド（self.add_layer_dropdowns）を呼び出す
                """
    
    def get_style_name(self, speaker_id):
        print("Getting style name")
        for character, styles in self.character_data.items():
            for style_name, id in styles.items():
                if id == speaker_id:
                    return style_name
        return ""

    def load_existing_json_files(self):
        # Treeviewをクリア
        for item in self.tree.get_children():
            self.tree.delete(item)
    
        self.tree_insert = []
        self.bg_tree_insert = []

        # JSONファイルのロードロジック
        for filename in os.listdir('json'):
            if filename.endswith('.json'):
                json_file_path = os.path.join('json', filename)
                data = self.load_json_file(json_file_path)
                if data is not None:
                    if not "background_" in json_file_path:
                        character = data["character"]
                        style = self.get_style_name(data["speaker_id"])
                        text = data["text"]
                        layer = data.get("layer", 1) 
                        position = data["position"]
                        start_time = data.get("start_time", 0)
                        duration = data.get("duration", "")
                        volume = data.get("volume")
                        self.tree_insert.append((character, style, text, layer, position, start_time, duration, volume, filename))
                    else:
                        start_time = data.get("start_time", 0)
                        duration = data.get("duration", "")
                        file_name = data.get("backgroudn_file", "")
                        self.bg_tree_insert.append((start_time, duration, file_name))


        df = pd.DataFrame(self.tree_insert, columns=['character', 'style', 'text', 'layer', 'position', 'start_time', 'duration', 'volume', 'filename'])
        df = df.sort_values(by='start_time')
        self.tree_insert = df.values.tolist()
  
        for ins in self.tree_insert:
            self.tree.insert("", "end", values=ins)

        bg_df = pd.DataFrame(self.bg_tree_insert, columns=['start_time', 'duration', 'file_name'])
        bg_df = bg_df.sort_values(by='start_time')
        self.bg_tree_insert = bg_df.values.tolist()
        for ins in self.bg_tree_insert:
            self.bg_tree.insert("", "end", values=(ins))


    def combine_videos(self):
        print("Combining videos")
        try:
            # キャラクター
            # ツリーに表示されているファイル順に動画を取得
          
            layers = {}
            clips = []
            for i, item in enumerate(self.tree.get_children()):
                item_data = self.tree.item(item, "values")
                filename = self.tree_insert[i]
                filename = filename[-1]# ファイル名を取得 
                json_file_path = os.path.join('json', filename)

                char_start_time = item_data[5] # start_time
                char_duration = item_data[6]   # duration 
                layer = item_data[3]           # layer
                for item in self.layer_options:
                    if layer == item[1]:
                        layer = item[0]
                data = self.load_json_file(json_file_path) 
                print(data)
                data['layer'] = layer
                with open(json_file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)

                print(char_start_time, char_duration)
                if data is not None:
                    char_movfile = data["mov_file"]
                    #layer = data["layer"]
                    if layer not in layers.keys():
                        layers[layer] = []
          
                    #print(char_movfile)
                    clip = mp.VideoFileClip(char_movfile, has_mask=True) 
                    clip = clip.subclip(0, char_duration)
                    clip = clip.set_start(char_start_time)
                    #clips.append(clip)

                layers[layer].append( [clip, char_start_time, char_duration]) 

            for key, value in layers.items():
                print(key, value) 
                layercommand = []  
                df = None
                for item in value:
                    print([item[1],item[2]])
                    if df is None:
                        df = pd.DataFrame([[ float(item[1]), float(item[2]) ]], columns=['start', 'duration'])
                        df['sum'] = df['start'] + df['duration']
                    else:
                        dfinner = pd.DataFrame([[ float(item[1]), float(item[2]) ]], columns=['start', 'duration'])
                        dfinner['sum'] = dfinner['start'] + dfinner['duration']
                        df = pd.concat([df, dfinner])               
                    bgduration = df['sum'].max() - df['start'].min()    
                    layercommand.append( item[0].set_start(item[1]) ) 
                layercommand.insert(0,  mp.ColorClip(size=resolution, color=(0,0,0,0), duration=bgduration)    )

                layer_clip = mp.CompositeVideoClip(
                    layercommand,
                    size=resolution)

                layers[key] = layer_clip
            print(layers)
            clips = sorted(layers.items(), reverse=True, key=lambda x: x[0])
            print(clips)
            clips = [value for key, value in clips]
            print(clips)

            # 背景の動画を重ねる
            bg_clips = []
            for bg_item in self.bg_tree.get_children():
                bg_item_data = self.bg_tree.item(bg_item, "values")
                bg_movfile = bg_item_data[-1]
                bg_movfile = os.path.basename(bg_movfile)
                bg_movfile = os.path.join('source', bg_movfile)
                bg_start_time = bg_item_data[0]
                bg_duration = bg_item_data[1]           
                bg_movfile_path = os.path.join('source', os.path.basename(bg_movfile))
                print( bg_start_time, bg_duration )
                clip = mp.VideoFileClip(bg_movfile_path).set_start(bg_start_time).set_duration(bg_duration).resize(resolution)
                bg_clips.append(clip)
            if bg_clips:
                clips = bg_clips + clips

            combined_clip = mp.CompositeVideoClip(clips)


            print("----------------------------   動画を合成します。")    

            # 動画の保存
            output_file = "combined_video.mp4"
            combined_clip.write_videofile(output_file, codec="libx264", fps=24, audio_codec="aac")
            messagebox.showinfo("Success", f"動画が成功裏に重ね合わされました: {output_file}")
        except Exception as e:
            error_message = traceback.format_exc()
            print(error_message)
            messagebox.showerror("Error", error_message)

if __name__ == "__main__":
    print("Starting application")
    root = tk.Tk()
    app = AnimationGUI(root)
    root.mainloop()