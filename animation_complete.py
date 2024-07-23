import wx
import wx.grid
import wx.lib.scrolledpanel

import os
import re
import json

import threading
import queue

#import PySimpleGUI as sg
import gloour
import requests

import moviepy.editor as mp
from moviepy.video.io.ffmpeg_writer import FFMPEG_VideoWriter
import ffmpeg
from PIL import Image, ImageDraw, ImageFont
import wave
from proglog import ProgressBarLogger

import numpy as np
import random

import pandas as pd
from scipy.io import wavfile
import shutil

resolution = (1920, 1080)
default_character_order = None
fps = 30
output = "output.mp4"

class VoiceGenerator:
    def __init__(self, base_url="http://localhost:50021"):
        self.base_url = base_url

    def generate_voice(self, text, speaker_id=1, output_path="temp/output.wav"):
        print("Generating voice")
        params = {
            "text": text,
            "speaker": speaker_id
        }
        query = requests.post(f"{self.base_url}/audio_query", params=params)   ################################################### 改善個所　VOICE VOX 起動確認
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
        #self.fps = 24
        self.fps = fps
        self.resolution = resolution
        self.images = self.load_images(character)
        self.voice_generator = VoiceGenerator()
        self.image_processor = ImageProcessor(resolution)
        self.clip_counter = 0
        os.makedirs('json', exist_ok=True)
        os.makedirs('video', exist_ok=True)

    def add_text(self, image, text, font_size, font_color, border_color, position):
        draw = ImageDraw.Draw(image)
        font_path = "font/NotoSansJP-Medium.otf"
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
            y_offset = 10

        for line in lines:
            text_bbox = draw.textbbox((0, 0), line, font=font)
            text_width, text_height = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
            if position == "center":
                x = (width - text_width) / 2
            elif position == "bottom":
                x = (width - text_width) / 2
            else:
                x = 10

            draw.text((x - 1, y_offset - 1), line, font=font, fill=border_color)
            draw.text((x + 1, y_offset - 1), line, font=font, fill=border_color)
            draw.text((x - 1, y_offset + 1), line, font=font, fill=border_color)
            draw.text((x + 1, y_offset + 1), line, font=font, fill=border_color)
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
        return mp.AudioClip(lambda t: [0, 0], duration=duration).set_fps(self.fps)

    def create_animation(self, text, position="center", 
                        speaker_id=1, volume=1.0, silence_duration=0, 
                        title_settings=None, subtitle_settings=None, 
                        progress_callback=None):
        print("Starting to create animation")
        silence_duration = int(silence_duration)
        if volume == 0:
            text = '[' + str(silence_duration) + ']'
        print(text)
        #segments = re.split(r'(\d+)', text)
        #segments = re.split(r'(\d+|\n)', text)
        segments = re.split(r'(\n)', text)
        segments = [item for item in segments if item]
        print(segments)

        audio_clips = []
        total_duration = 0
        default_pause = 5
        font_path = "font/NotoSansJP-Medium.otf"

        for i, segment in enumerate(segments):
            segment = segment.strip()
            #if segment.isdigit() and i< len(segments) and segments[i-1] == '[' and segments[i+1] == ']':
            if len(segment) >2 and segment[0] == "[" and segment[-1] == "]" and segment[1:-2].isdigit():
                        pause_duration = int(segment[1:-1])
                        silence_clip = self.create_silence(pause_duration, 44100)
                        audio_clips.append(silence_clip)
                        total_duration += pause_duration
            elif segment == '\n':
                        pass
                        #pause_duration = 1
                        #silence_clip = self.create_silence(pause_duration, 44100)
                        #audio_clips.append(silence_clip)
                        #total_duration += pause_duration
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

            transparent_bg = Image.new('RGBA', img_resized.size, (0, 0, 0, 0))
            combined = Image.alpha_composite(transparent_bg, img_resized)

            return combined

        pngs = []    
        for t in np.arange(0, total_duration, 1 / self.fps):
            frame = make_frame(t)
            frame_path = f'temp/frame_{int(t * self.fps):04d}.png'
            frame.save(frame_path)
            pngs.append(frame_path)
            if progress_callback:
                progress_callback(50 + int(t / total_duration * 25))


        video = mp.ImageSequenceClip(pngs, fps=self.fps)

        video = video.set_audio(final_audio)
        video = video.set_fps(self.fps)

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

        existing_json_files = glob.glob('json/output_*.json')
        json_file_number = len(existing_json_files) + 1

        mov_file = f'video/output_{json_file_number}.mov'
        mp4_file = f'video/output_{json_file_number}.mp4'

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
       
        if title_settings and title_settings["text"] != "":
            title_clip = mp.TextClip(
                title_settings["text"], fontsize=title_settings["font_size"], color=title_settings["font_color"], bg_color='transparent', 
                font=font_path, size=(self.resolution[0], None), 
                stroke_color=title_settings["border_color"],
                method='caption'
            ).set_position('center').set_duration(title_settings["duration"]).set_start(title_settings["start_time"])

            final_clip = mp.CompositeVideoClip([final_clip, title_clip], size=self.resolution)

        if subtitle_settings and subtitle_settings["text"] != "":
            subtitle_clip = mp.TextClip(
                subtitle_settings["text"], fontsize=subtitle_settings["font_size"], color=subtitle_settings["font_color"], bg_color='transparent', font=font_path, size=(self.resolution[0], None), method='caption'
            ).set_position(('center', 'bottom')).set_duration(subtitle_settings["duration"]).set_start(subtitle_settings["start_time"])
            final_clip = mp.CompositeVideoClip([final_clip, subtitle_clip], size=self.resolution)

        # カスタムロガーを設定
        if progress_callback:
            print(progress_callback)
            
            logger = WriteVideoProgress(progress_callback)
            final_clip.write_videofile(mov_file, codec="qtrle", fps=self.fps, logger=logger)  ####################
        else:
             final_clip.write_videofile(mov_file, codec="qtrle", fps=self.fps)

        gray_bg = mp.ColorClip(size=self.resolution, color=(128, 128, 128)).set_duration(total_duration).set_fps(self.fps)
        final_clip_with_gray_bg = mp.CompositeVideoClip([gray_bg, video], size=self.resolution)
        final_clip_with_gray_bg.write_videofile(mp4_file, codec="libx264", fps=self.fps, ffmpeg_params=["-pix_fmt", "yuv420p"])

        global default_character_order
        if default_character_order is None:
            default_character_order = {self.character: 1}
            layer = 1
        elif self.character in default_character_order:
            layer = default_character_order[self.character]
        else:
            layer = max(default_character_order.values()) +1
            default_character_order.setdefault(self.character, layer)

        json_data = {
            "mov_file": os.path.basename(mov_file),
            "mp4_file": os.path.basename(mp4_file),
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
    
        json_output_path = f'json/output_{json_file_number}.json'   # Json 書き出し    
        with open(json_output_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)

        temp_files = glob.glob('temp/*')                            # tempファイル・クリア
        for file in temp_files:
            os.remove(file)

        return mov_file, mp4_file
#########################################################################################################
class WriteVideoProgress(ProgressBarLogger):
    def __init__(self, progress_callback, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.progress_callback = progress_callback
        self.reading_audio = False

    def callback(self, *_, **__):
        pass

    def bars_callback(self, bar, attr, value, old_value=None): 
        total = self.bars[bar]["total"]
        if total > 0:
            progress = int((value / total) * 100)
            wx.CallAfter(self.progress_callback, progress)
            print(f"Progress: {progress}%")

#########################################################################################################
class Combine_videos:
    def __init__(self, frame): #Animation クラスへのアクセス
        self.frame = frame
        self.resolution = resolution
        self.fps = fps

        self.result_queue = queue.Queue()
        self.progress = 0

    def get_table_data(self):
        data = []
        num_rows = self.frame.table.GetNumberRows() #キャラ画テーブル　行列数
        num_cols = self.frame.table.GetNumberCols()

        #　キャラ画
        for row in range(num_rows):
            row_values = []
            for col in range(num_cols):
                row_value = self.frame.table.GetCellValue(row, col) ## テーブル表の導入
                row_values.append(row_value)
            data.append(row_values)

        bg_data = []
        num_rows = self.frame.bg_table.GetNumberRows() #Backgroundテーブル　行列数
        num_cols = self.frame.bg_table.GetNumberCols()

        #　Background
        for row in range(num_rows):
            row_values = []
            for col in range(num_cols):
                row_value = self.frame.bg_table.GetCellValue(row, col) ## テーブル表の導入
                row_values.append(row_value)
            bg_data.append(row_values)
        #print(bg_data)

        return (data, bg_data)

    def composition(self, progress_callback):  #############################################################################
        datum = self.get_table_data()

        #Background
        data = datum[1]
        df = pd.DataFrame(data, columns=['開始タイミング', 'duration', 'ファイル名', 'filename'])
        #print(df)

        df['layer'] = 0 
        
        # キャラ画
        data = datum[0]
        # Convert the array to a DataFrame
        cdf = pd.DataFrame(data, columns=['キャラクター', '声色', 'セリフ', 'layer', '横位置', '開始タイミング', 'duration', 'ボリューム', 'filename'])

        # Concatenate the DataFrames
        df = pd.concat([df, cdf], ignore_index=True)
        df['開始タイミング'] = df['開始タイミング'].astype(float)
        df['duration'] = df['duration'].astype(float)
        df['layer'] = df['layer'].astype(float)
        # Step 1: Remove rows where the 6th column (開始タイミング) contains a negative value
        df = df[df['開始タイミング'] >= 0]

        # Step 2: Sort by 'layer' and '開始タイミング'
        df = df.sort_values(by=['layer', '開始タイミング'])

        # Specify the desired order of columns
        desired_order = ['layer','開始タイミング', 'duration', 'filename','ファイル名','キャラクター', '声色', 'セリフ', '横位置','ボリューム']
        # Reorder the columns
        df = df.reindex(columns=desired_order)
        sd = df['開始タイミング'] + df['duration']
        total_duration = sd.max()   #ベース動画終了時間

        # ベース
        bgpng = 'temp/base_bg.png'
        bgmov = 'temp/base_bg.mov'
        img = Image.new('RGBA', (self.resolution[0], self.resolution[1]), (0, 0, 0, 0))
        img.save(bgpng)
        print("Running ffmpeg process for base background")
        process = (
            ffmpeg
            .input(bgpng, loop=1, framerate=self.fps)
            .output(bgmov, vcodec='qtrle', t=total_duration, pix_fmt='argb', r=self.fps)
            .run()
        )

        videos=[]
        for i, vitem in enumerate(df.values.tolist()):
            print(vitem)
            layer = vitem[0]
            start = vitem[1]
            duration = vitem[2]
            filename = vitem[3]
            if layer ==0:
                print("layer 0")
                with open(os.path.join('./json', filename), 'r', encoding='utf-8') as file:
                        data = json.load(file)
                #background = data['background_file']  　　　バックグラウンド調整
                movie='source/'+ data['background_file']
                clip = mp.VideoFileClip(movie, has_mask=True)
                if clip.duration != duration:
                    clip = clip.subclip(0, duration)
                if clip.size[1] > resolution[1]:
                    clip = clip.resize(height=resolution[1])
                clip = clip.set_start(start)
                clip = clip.set_position(("center","center"))
            else: 
                #charactor movie                            キャラムービー調整
                with open(os.path.join('./json', filename), 'r', encoding='utf-8') as file:
                        data = json.load(file)
                movie = 'video/' + data['mov_file']
                clip = mp.VideoFileClip(movie, has_mask=True)
                if clip.duration != duration:
                    clip = clip.subclip(0, duration)
                clip = clip.set_start(start)
            videos.append([clip,start,duration])
            if i <1:
                clips = clip
            else:
                clips = mp.CompositeVideoClip([clips, clip], size=self.resolution)

        background_clip = mp.VideoFileClip(bgmov, has_mask=True).set_duration(total_duration)
        final_clip = mp.CompositeVideoClip([background_clip, clips], size=self.resolution)


        # カスタムロガーを設定
        logger = WriteVideoProgress(progress_callback)
        final_clip.write_videofile(output, codec="libx264", fps=self.fps, ffmpeg_params=["-pix_fmt", "yuv420p"], logger=logger)
        #final_clip.write_videofile(output, codec="libx264", fps=self.fps, ffmpeg_params=["-pix_fmt", "yuv420p"])
          
        temp_files = glob.glob('temp/*')                            # tempファイル・クリア
        for file in temp_files:
            os.remove(file)

        self.result_queue.put("動画処理が完了")
        return output
   

#########################################################################################################
class AnimationGUI(wx.Frame):
    def __init__(self, *args, **kw):
        super(AnimationGUI, self).__init__(*args, **kw)
        self.fps = fps

        self.character_data = {
            "ずんだもん": {"ノーマル": 3, "あまあま": 1, "ツンツン": 7, "セクシー": 5, "ささやき": 22, "ヒソヒソ": 38, "ヘロヘロ": 75, "なみだめ": 76},
            "四国めたん": {"ノーマル": 2, "あまあま": 0, "ツンツン": 6, "セクシー": 4, "ささやき": 36, "ヒソヒソ": 37}
        }

        self.InitUI()
        self.load_existing_json_files()

    def InitUI(self):
        panel = wx.lib.scrolledpanel.ScrolledPanel(self)
        panel.SetupScrolling(scroll_x=True, scroll_y=True)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # キャラクター選択
        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        st1 = wx.StaticText(panel, label='キャラクター')
        hbox1.Add(st1, flag=wx.RIGHT, border=8)
        self.character_combo = wx.ComboBox(panel, choices=list(self.character_data.keys()), style=wx.CB_READONLY)
        self.character_combo.Bind(wx.EVT_COMBOBOX, self.on_character_select)
        hbox1.Add(self.character_combo, proportion=1)
        vbox.Add(hbox1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # 声色選択
        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        st2 = wx.StaticText(panel, label='声色')
        hbox2.Add(st2, flag=wx.RIGHT, border=8)
        self.voice_combo = wx.ComboBox(panel, choices=[], style=wx.CB_READONLY)
        hbox2.Add(self.voice_combo, proportion=1)
        vbox.Add(hbox2, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # セリフ入力
        hbox3 = wx.BoxSizer(wx.HORIZONTAL)
        st3 = wx.StaticText(panel, label='セリフ')
        hbox3.Add(st3, flag=wx.RIGHT, border=8)
        self.text_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(400, 50))
        hbox3.Add(self.text_ctrl, proportion=1, flag=wx.EXPAND)
        vbox.Add(hbox3, proportion=1, flag=wx.LEFT|wx.RIGHT|wx.TOP|wx.EXPAND, border=10)

        # 位置選択（横並びのラジオボタン）
        hbox4 = wx.BoxSizer(wx.HORIZONTAL)
        st4 = wx.StaticText(panel, label='横位置')
        hbox4.Add(st4, flag=wx.RIGHT, border=8)
        self.position_choices = ['hidden', 'left_10', 'left_25', 'center', 'right_25', 'right_10']
        self.position_radio_buttons = []
        for choice in self.position_choices:
            rb = wx.RadioButton(panel, label=choice, style=wx.RB_GROUP if choice == 'hidden' else 0)
            hbox4.Add(rb, flag=wx.RIGHT, border=8)
            self.position_radio_buttons.append(rb)
        vbox.Add(hbox4, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # その他の入力
        hbox5 = wx.BoxSizer(wx.HORIZONTAL)
        st5 = wx.StaticText(panel, label='開始タイミング (秒)')
        hbox5.Add(st5, flag=wx.RIGHT, border=8)
        self.start_time_ctrl = wx.TextCtrl(panel)
        hbox5.Add(self.start_time_ctrl, proportion=1)
        vbox.Add(hbox5, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        hbox6 = wx.BoxSizer(wx.HORIZONTAL)
        st6 = wx.StaticText(panel, label='ボリューム')
        hbox6.Add(st6, flag=wx.RIGHT, border=8)
        self.volume_ctrl = wx.TextCtrl(panel, value="1.0")
        hbox6.Add(self.volume_ctrl, proportion=1)
        self.set_silence_btn = wx.Button(panel, label='無音')
        self.set_silence_btn.Bind(wx.EVT_BUTTON, self.on_set_silence)
        hbox6.Add(self.set_silence_btn, flag=wx.LEFT, border=8)
        self.silence_duration_ctrl = wx.TextCtrl(panel, value="5")
        hbox6.Add(self.silence_duration_ctrl, proportion=1)
        vbox.Add(hbox6, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        vbox.Add(wx.StaticText(panel, label="無音アニメーションの秒数指定　指定なしだと5秒"), flag=wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # タイトル設定
        hbox7 = wx.BoxSizer(wx.HORIZONTAL)
        st7 = wx.StaticText(panel, label='タイトル')
        hbox7.Add(st7, flag=wx.RIGHT, border=8)
        self.title_text_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(400, 40))
        hbox7.Add(self.title_text_ctrl, proportion=1, flag=wx.EXPAND)
        vbox.Add(hbox7, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Combining hbox7, hbox8, and hbox9 into a single horizontal sizer (hbox_combined)
        hbox_combined = wx.BoxSizer(wx.HORIZONTAL)

        hbox8 = wx.BoxSizer(wx.HORIZONTAL)
        st8 = wx.StaticText(panel, label='タイトルフォントサイズ')
        hbox8.Add(st8, flag=wx.RIGHT, border=8)
        self.title_font_size_ctrl = wx.TextCtrl(panel, value="40")
        hbox8.Add(self.title_font_size_ctrl, proportion=1)
        #vbox.Add(hbox8, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        hbox9 = wx.BoxSizer(wx.HORIZONTAL)
        st9 = wx.StaticText(panel, label='タイトルフォント色')
        hbox9.Add(st9, flag=wx.RIGHT, border=8)
        self.title_font_color_ctrl = wx.TextCtrl(panel, value="white")
        hbox9.Add(self.title_font_color_ctrl, proportion=1)
        #vbox.Add(hbox9, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        hbox10 = wx.BoxSizer(wx.HORIZONTAL)
        st10 = wx.StaticText(panel, label='タイトル縁取り色')
        hbox10.Add(st10, flag=wx.RIGHT, border=8)
        self.title_border_color_ctrl = wx.TextCtrl(panel, value="black")
        hbox10.Add(self.title_border_color_ctrl, proportion=1)
        #vbox.Add(hbox10, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Add hbox8, hbox9, and hbox10 to hbox_combined
        hbox_combined.Add(hbox8, proportion=1, flag=wx.EXPAND|wx.ALL, border=5)
        hbox_combined.Add(hbox9, proportion=1, flag=wx.EXPAND|wx.ALL, border=5)
        hbox_combined.Add(hbox10, proportion=1, flag=wx.EXPAND|wx.ALL, border=5)
        # Add hbox_combined to the main vertical sizer
        vbox.Add(hbox_combined, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Combining hbox11, hbox12 into a single horizontal sizer (hbox_combined)
        hbox_combined = wx.BoxSizer(wx.HORIZONTAL)

        hbox11 = wx.BoxSizer(wx.HORIZONTAL)
        st11 = wx.StaticText(panel, label='タイトル開始タイミング (秒)')
        hbox11.Add(st11, flag=wx.RIGHT, border=8)
        self.title_start_time_ctrl = wx.TextCtrl(panel, value="0")
        hbox11.Add(self.title_start_time_ctrl, proportion=1)
        #vbox.Add(hbox11, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        hbox12 = wx.BoxSizer(wx.HORIZONTAL)
        st12 = wx.StaticText(panel, label='タイトルduration (秒)')
        hbox12.Add(st12, flag=wx.RIGHT, border=8)
        self.title_duration_ctrl = wx.TextCtrl(panel, value="5")
        hbox12.Add(self.title_duration_ctrl, proportion=1)
        #vbox.Add(hbox12, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Add hbox11, hbox12 to hbox_combined
        hbox_combined.Add(hbox11, proportion=1, flag=wx.EXPAND|wx.ALL, border=5)
        hbox_combined.Add(hbox12, proportion=1, flag=wx.EXPAND|wx.ALL, border=5)
        # Add hbox_combined to the main vertical sizer
        vbox.Add(hbox_combined, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # サブタイトル設定
        hbox13 = wx.BoxSizer(wx.HORIZONTAL)
        st13 = wx.StaticText(panel, label='サブタイトル')
        hbox13.Add(st13, flag=wx.RIGHT, border=8)
        self.subtitle_text_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(400, 40))
        hbox13.Add(self.subtitle_text_ctrl, proportion=1, flag=wx.EXPAND)
        vbox.Add(hbox13, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Combining hbox14, hbox15, hbox16 into a single horizontal sizer (hbox_combined)
        hbox_combined = wx.BoxSizer(wx.HORIZONTAL)

        # サブタイトルフォントサイズ
        hbox14 = wx.BoxSizer(wx.HORIZONTAL)
        st14 = wx.StaticText(panel, label='サブタイトルフォントサイズ')
        hbox14.Add(st14, flag=wx.RIGHT, border=8)
        self.subtitle_font_size_ctrl = wx.TextCtrl(panel, value="30")
        hbox14.Add(self.subtitle_font_size_ctrl, proportion=1)
        #vbox.Add(hbox14, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # サブタイトルフォント色
        hbox15 = wx.BoxSizer(wx.HORIZONTAL)
        st15 = wx.StaticText(panel, label='サブタイトルフォント色')
        hbox15.Add(st15, flag=wx.RIGHT, border=8)
        self.subtitle_font_color_ctrl = wx.TextCtrl(panel, value="white")
        hbox15.Add(self.subtitle_font_color_ctrl, proportion=1)
        #vbox.Add(hbox15, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # サブタイトル縁取り色
        hbox16 = wx.BoxSizer(wx.HORIZONTAL)
        st16 = wx.StaticText(panel, label='サブタイトル縁取り色')
        hbox16.Add(st16, flag=wx.RIGHT, border=8)
        self.subtitle_border_color_ctrl = wx.TextCtrl(panel, value="black")
        hbox16.Add(self.subtitle_border_color_ctrl, proportion=1)
        #vbox.Add(hbox16, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Add hbox14, hbox15, and hbox16 to hbox_combined
        hbox_combined.Add(hbox14, proportion=1, flag=wx.EXPAND|wx.ALL, border=5)
        hbox_combined.Add(hbox15, proportion=1, flag=wx.EXPAND|wx.ALL, border=5)
        hbox_combined.Add(hbox16, proportion=1, flag=wx.EXPAND|wx.ALL, border=5)
        # Add hbox_combined to the main vertical sizer
        vbox.Add(hbox_combined, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Combining hbox17, hbox18 into a single horizontal sizer (hbox_combined)
        hbox_combined = wx.BoxSizer(wx.HORIZONTAL)

        # サブタイトル開始タイミング
        hbox17 = wx.BoxSizer(wx.HORIZONTAL)
        st17 = wx.StaticText(panel, label='サブタイトル開始タイミング (秒)')
        hbox17.Add(st17, flag=wx.RIGHT, border=8)
        self.subtitle_start_time_ctrl = wx.TextCtrl(panel, value="0")
        hbox17.Add(self.subtitle_start_time_ctrl, proportion=1)
        #vbox.Add(hbox17, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # サブタイトルduration
        hbox18 = wx.BoxSizer(wx.HORIZONTAL)
        st18 = wx.StaticText(panel, label='サブタイトルduration (秒)')
        hbox18.Add(st18, flag=wx.RIGHT, border=8)
        self.subtitle_duration_ctrl = wx.TextCtrl(panel, value="5")
        hbox18.Add(self.subtitle_duration_ctrl, proportion=1)
        #vbox.Add(hbox18, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        # Add hbox17, hbox18 to hbox_combined
        hbox_combined.Add(hbox17, proportion=1, flag=wx.EXPAND|wx.ALL, border=5)
        hbox_combined.Add(hbox18, proportion=1, flag=wx.EXPAND|wx.ALL, border=5)
        # Add hbox_combined to the main vertical sizer
        vbox.Add(hbox_combined, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)


        # ボタン配置
        hbox19 = wx.BoxSizer(wx.HORIZONTAL)
        self.generate_btn = wx.Button(panel, label='アニメーション生成')
        self.generate_btn.Bind(wx.EVT_BUTTON, self.on_generate)
        hbox19.Add(self.generate_btn, flag=wx.RIGHT, border=8)
        self.upload_background_btn = wx.Button(panel, label='背景アップロード')
        self.upload_background_btn.Bind(wx.EVT_BUTTON, self.on_upload_background)
        hbox19.Add(self.upload_background_btn, flag=wx.RIGHT, border=8)
        self.combine_videos_btn = wx.Button(panel, label='動画を重ね合わせる')
        self.combine_videos_btn.Bind(wx.EVT_BUTTON, self.on_combine_videos)
        hbox19.Add(self.combine_videos_btn, flag=wx.RIGHT, border=8)
        #プログレッシブバー
        # Create a vertical sizer for the progress bars
        box_progress = wx.BoxSizer(wx.HORIZONTAL)

        # Add the first progress bar to the vertical sizer
        self.gauge1 = wx.Gauge(panel, range=100, size=(250, 25))
        box_progress.Add(self.gauge1, 0, wx.ALL | wx.CENTER, 5)

        # Add the second progress bar to the vertical sizer
        self.gauge2 = wx.Gauge(panel, range=100, size=(250, 25))
        box_progress.Add(self.gauge2, 0, wx.ALL | wx.CENTER, 5)

        # Add the vertical sizer to the horizontal sizer
        hbox19.Add(box_progress, flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=8)

        # Add the horizontal sizer to the main vertical sizer
        vbox.Add(hbox19, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=10)
        panel.SetSizer(vbox)


        # スクロールパネル for キャラクター用テーブル
        char_scroll_panel = wx.ScrolledWindow(panel, size=(800, 200), style=wx.SIMPLE_BORDER)
        char_scroll_panel.SetScrollRate(5, 5)

        # キャラクター用テーブル
        self.table = wx.grid.Grid(char_scroll_panel)
        self.table.CreateGrid(5, 9)  # 行数と列数を調整
        self.table.SetColLabelValue(0, "キャラクター")
        self.table.SetColLabelValue(1, "声色")
        self.table.SetColLabelValue(2, "セリフ")
        self.table.SetColLabelValue(3, "layer")
        self.table.SetColLabelValue(4, "横位置")
        self.table.SetColLabelValue(5, "開始タイミング")
        self.table.SetColLabelValue(6, "duration")
        self.table.SetColLabelValue(7, "ボリューム")
        self.table.SetColLabelValue(8, "filename")

        char_scroll_vbox = wx.BoxSizer(wx.VERTICAL)
        char_scroll_vbox.Add(self.table, 1, wx.EXPAND)
        char_scroll_panel.SetSizer(char_scroll_vbox)
        
        vbox.Add(char_scroll_panel, 1, wx.EXPAND | wx.ALL, 10)

        # Bind the cell change event to a handler
        self.table.Bind(wx.grid.EVT_GRID_CELL_CHANGED, self.on_cell_change)


        # スクロールパネル for 背景アニメーション用テーブル
        bg_scroll_panel = wx.ScrolledWindow(panel, size=(800, 200), style=wx.SIMPLE_BORDER)
        bg_scroll_panel.SetScrollRate(5, 5)

        # 背景アニメーション用テーブル
        self.bg_table = wx.grid.Grid(bg_scroll_panel)
        self.bg_table.CreateGrid(5, 4)  # 行数と列数を調整
        self.bg_table.SetColLabelValue(0, "開始タイミング")
        self.bg_table.SetColLabelValue(1, "duration")
        self.bg_table.SetColLabelValue(2, "ファイル名")
        self.bg_table.SetColLabelValue(3, "json")

        bg_scroll_vbox = wx.BoxSizer(wx.VERTICAL)
        bg_scroll_vbox.Add(self.bg_table, 1, wx.EXPAND)
        bg_scroll_panel.SetSizer(bg_scroll_vbox)
        
        vbox.Add(bg_scroll_panel, 1, wx.EXPAND | wx.ALL, 10)

        # Bind the cell change event to a handler for the background table
        self.bg_table.Bind(wx.grid.EVT_GRID_CELL_CHANGED, self.on_bg_cell_change)

        panel.SetSizer(vbox)


    def on_cell_change(self, event):
        row = event.GetRow()
        col = event.GetCol()
        value = self.table.GetCellValue(row, col)
        print(f"Cell at row {row}, column {col} changed to {value}")
        num_col = self.table.GetNumberCols() -1
        filename = self.table.GetCellValue(row, num_col)
        #print(filename)

        with open(os.path.join("./json", filename), "r", encoding="utf-8") as f:
                data = json.load(f)
        # Column #3 layer
        if col == 3:
            data['layer'] = int(value)
        elif col == 5:
            data['start_time'] = float(value)
        elif col == 6:
            data['duration'] = float(value)
        elif col == 7:
            data['volume'] = float(value)
        with open(os.path.join("./json", filename), 'w', encoding='utf-8') as file:
                json.dump(data, file, ensure_ascii=False, indent=4)
        if col == 5:
            self.load_existing_json_files() # 表示をstart_time順に並べ替え
        # Process the updated cell value as needed
        # For example, update the corresponding JSON data

        event.Skip()  # Ensure the event is propagated to other handlers

    def on_bg_cell_change(self, event):
        row = event.GetRow()
        col = event.GetCol()
        value = self.bg_table.GetCellValue(row, col)
        print(f"Background table cell at row {row}, column {col} changed to {value}")
        num_col = self.bg_table.GetNumberCols() -1
        filename = self.bg_table.GetCellValue(row, num_col)
        print(filename)
        with open(os.path.join("./json", filename), "r", encoding="utf-8") as f:
            data = json.load(f)
        if col == 0:
            data['start_time'] = float(value)
        elif col == 1:
            data['duration'] = float(value)
        with open(os.path.join("./json", filename), 'w', encoding='utf-8') as file:
                json.dump(data, file, ensure_ascii=False, indent=4)
        if col ==0:
            self.load_existing_json_files() # 表示をstart_time順に並べ替え
        # Process the updated cell value as needed
        # For example, update the corresponding JSON data

        event.Skip()  # Ensure the event is propagated to other handlers


    def load_existing_json_files(self):
        #try:
            print("load json")
            self.tree_insert = []
            self.bg_tree_insert = []
            # Load existing JSON files (example logic)
            for filename in os.listdir('./json'):
                if filename.endswith('.json'):
                    with open(os.path.join('./json', filename), 'r', encoding='utf-8') as file:
                        data = json.load(file)
                        if not "background_" in filename:
                            character = data["character"]
                            #style = self.get_style_name(data["speaker_id"])
                            style = data["speaker_id"]
                            text = data["text"]
                            layer = data.get("layer", 1)
                            position = data["position"]
                            start_time = data.get("start_time", 0)
                            duration = data.get("duration", "")
                            volume = data.get("volume")
                            self.tree_insert.append((character, style, text, layer, position, start_time, duration, volume, filename))
                        else:
                            start_time = data.get("start_time", 0)
                            start_time = float(start_time)
                            duration = data.get("duration", "")
                            duration = float(duration)
                            file_name = data.get("background_file", "")
                            self.bg_tree_insert.append((start_time, duration, file_name, filename))

            df = pd.DataFrame(self.tree_insert, columns=['character', 'style', 'text', 'layer', 'position', 'start_time', 'duration', 'volume', 'filename'])
            df["start_time"] = df["start_time"].astype(float)
            df = df.sort_values(by='start_time')
            self.tree_insert = df.values.tolist()

            bg_df = pd.DataFrame(self.bg_tree_insert, columns=['start_time', 'duration', 'file_name', 'filename'])
            bg_df["start_time"] = bg_df["start_time"].astype(float)
            bg_df = bg_df.sort_values(by='start_time')
            self.bg_tree_insert = bg_df.values.tolist()

            self.table.ClearGrid()
            self.bg_table.ClearGrid()
    
            # Clear existing rows
            if self.table.GetNumberRows() >0:
                self.table.DeleteRows(0, self.table.GetNumberRows(), updateLabels=True)
            if self.bg_table.GetNumberRows() >0:
                self.bg_table.DeleteRows(0, self.bg_table.GetNumberRows(), updateLabels=True)

            for tree in self.tree_insert:
                self.table.AppendRows(1)
                row_index = self.table.GetNumberRows() - 1
                row_index = self.table.GetNumberRows() - 1
                self.table.SetCellValue(row_index, 0, tree[0])  #data.get('character', ''))
                style = [k for k, v in self.character_data[tree[0]].items() if v == tree[1]][0]
                self.table.SetCellValue(row_index, 1, str(style))  #data.get('style
                self.table.SetCellValue(row_index, 2, tree[2])  #data.get('text', ''))
                self.table.SetCellValue(row_index, 3, str(tree[3]))  #str(data.get('layer', '')))
                self.table.SetCellValue(row_index, 4, tree[4])  #data.get('position', ''))
                self.table.SetCellValue(row_index, 5, str(tree[5]))  #str(data.get('start_time', '')))
                self.table.SetCellValue(row_index, 6, str(tree[6]))  #str(data.get('duration', '')))
                self.table.SetCellValue(row_index, 7, str(tree[7]))  #str(data.get('volume', '')))
                self.table.SetCellValue(row_index, 8, tree[8])  #json_file)

             # Make certain cells read-only
                self.table.SetReadOnly(row_index, 0, True)  # Make 'キャラクター' column read-only
                self.table.SetReadOnly(row_index, 1, True) 
                self.table.SetReadOnly(row_index, 2, True) 
                self.table.SetReadOnly(row_index, 4, True) 
                self.table.SetReadOnly(row_index, 8, True)  # Make 'filename' column read-only

            for tree in self.bg_tree_insert:
                self.bg_table.AppendRows(1)
                bg_row_index = self.bg_table.GetNumberRows() - 1
                self.bg_table.SetCellValue(bg_row_index, 0, str(tree[0]))   #str(data.get('bg_start_time', '')))
                self.bg_table.SetCellValue(bg_row_index, 1, str(tree[1]))   #str(data.get('bg_duration', '')))
                self.bg_table.SetCellValue(bg_row_index, 2, tree[2])   #data.get('bg_file', ''))
                self.bg_table.SetCellValue(bg_row_index, 3, tree[3])   #json_file)

             # Make certain cells read-only
                self.bg_table.SetReadOnly(bg_row_index, 2, True)  # Make 'bg file name' column read-only
                self.bg_table.SetReadOnly(bg_row_index, 3, True)  # Make 'json' column read-only

        #except Exception as e:       
        #    wx.MessageBox(f"Error loading JSON files: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)
  
    # Event Handlers
    def on_character_select(self, event):
        character = self.character_combo.GetValue()
        styles = list(self.character_data.get(character, {}).keys())
        self.voice_combo.Set(styles)
        self.voice_combo.SetSelection(0 if styles else -1)

    def on_set_silence(self, event):
        duration = self.silence_duration_ctrl.GetValue()
        self.text_ctrl.SetValue(f"[silence duration={duration}]")

    #ボタン
    def on_generate(self, event):
        def progress_callback(value):
            wx.CallAfter(self.update_progress_1, value)

        if self.character_combo.GetValue() != "" and \
           self.voice_combo.GetValue() != "" and \
           self.text_ctrl.GetValue() != "":
            
            self.generate_btn.Disable() 

            self.combine_thread = threading.Thread(target=self.generate, args=(progress_callback,))
            self.combine_thread.start()
            # スレッドの状態をチェック
            wx.CallLater(50, self.check_thread_1, self.combine_thread)

    def generate(self, progress_callback):
        #try:
            # Extract values from controls
            character = self.character_combo.GetValue()
            style = self.voice_combo.GetValue()
            speaker_id = [v for k, v in self.character_data[character].items() if k == style][0]
            text = self.text_ctrl.GetValue()
            position = [rb.GetLabel() for rb in self.position_radio_buttons if rb.GetValue()][0]
            start_time = self.start_time_ctrl.GetValue()
            volume = self.volume_ctrl.GetValue()
            silence_duration = self.silence_duration_ctrl.GetValue()
            title_text = self.title_text_ctrl.GetValue()
            title_font_size = self.title_font_size_ctrl.GetValue()
            title_font_color = self.title_font_color_ctrl.GetValue()
            title_border_color = self.title_border_color_ctrl.GetValue()
            title_start_time = self.title_start_time_ctrl.GetValue()
            title_duration = self.title_duration_ctrl.GetValue()
            subtitle_text = self.subtitle_text_ctrl.GetValue()
            subtitle_font_size = self.subtitle_font_size_ctrl.GetValue()
            subtitle_font_color = self.subtitle_font_color_ctrl.GetValue()
            subtitle_border_color = self.subtitle_border_color_ctrl.GetValue()
            subtitle_start_time = self.subtitle_start_time_ctrl.GetValue()
            subtitle_duration = self.subtitle_duration_ctrl.GetValue()

            #Animatorクラス・create_animationを稼働させる
            animator = Animator(character=character, speaker=speaker_id)

            # スレッドを使用して重い処理をバックグラウンドで実行
            animator.create_animation(
                        text=text, position=position, 
                        volume=volume, silence_duration=silence_duration, 
                        speaker_id=speaker_id,
                        title_settings={
                            "text": title_text.strip(),
                            "font_size": int(title_font_size),
                            "font_color": title_font_color,
                            "border_color": title_border_color,
                            "start_time": float(title_start_time),
                            "duration": float(title_duration),
                        },
                        subtitle_settings={
                            "text": subtitle_text.strip(),
                            "font_size": int(subtitle_font_size),
                            "font_color": subtitle_font_color,
                            "border_color": subtitle_border_color,
                            "start_time": float(subtitle_start_time),
                            "duration": float(subtitle_duration),
                        },
                        progress_callback=progress_callback, #######################################################
                    )

            self.load_existing_json_files()
            wx.MessageBox("アニメーションが生成されました。", "情報", wx.OK | wx.ICON_INFORMATION)
        #except Exception as e:
        #    wx.MessageBox(f"Error generating animation: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)

    def on_combine_videos(self, event):
        def progress_callback(value):
            wx.CallAfter(self.update_progress_2, value)
        self.combine_videos_btn.Disable()

        self.combine_thread = threading.Thread(target=self.combine_videos, args=(progress_callback,))
        self.combine_thread.start()
        # スレッドの状態をチェック
        wx.CallLater(50, self.check_thread_2, self.combine_thread)

    def combine_videos(self, progress_callback):
        try:
            Cv = Combine_videos(self)
            Cv.composition(progress_callback)
        except Exception as e:
            wx.MessageBox(f"Error: {e}", "Error", wx.ICON_ERROR)

    def update_progress_1(self, progress):
        #wx.CallAfter(self.gauge.SetValue, int(progress * 100))
        wx.CallAfter(self.gauge1.SetValue, progress)
        if progress >=100:
            self.on_thread_complete()
        else:
            self.combine_videos_btn.Disable()

    def update_progress_2(self, progress):
        #wx.CallAfter(self.gauge.SetValue, int(progress * 100))
        wx.CallAfter(self.gauge2.SetValue, progress)
        if progress >=100:
            self.on_thread_complete()
        else:
            self.combine_videos_btn.Disable()

    def check_thread_1(self, thread):
        if thread.is_alive():
            # スレッドがまだ動作中の場合は、50ミリ秒後に再度チェック
            wx.CallLater(50, self.check_thread_1, thread)
        else:
            # スレッドが完了した場合は、結果を処理
            self.on_thread_complete()

    def check_thread_2(self, thread):
        if thread.is_alive():
            # スレッドがまだ動作中の場合は、50ミリ秒後に再度チェック
            wx.CallLater(50, self.check_thread_2, thread)
        else:
            # スレッドが完了した場合は、結果を処理
            self.on_thread_complete()


    def on_thread_complete(self):
        # ボタンを再度有効化
        self.combine_videos_btn.Enable()  ##########################################

    def on_upload_background(self, event):
        with wx.FileDialog(self, "背景画像または動画を選択", wildcard="Image and Video files (*.png;*.jpg;*.mp4;*.mov)|*.png;*.jpg;*.mp4;*.mov", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            pathname = fileDialog.GetPath()
            try:
                # Process the selected file (image or video)
                wx.MessageBox(f"選択されたファイル: {pathname}", "情報", wx.OK | wx.ICON_INFORMATION)

                if not os.path.exists('./source'):
                    os.makedirs('./source')
                shutil.copy(pathname, './source')
                print(f"Background file {pathname} uploaded to ./source")

                if pathname.endswith(".mp4") or pathname.endswith(".mov"):
                    clip = mp.VideoFileClip(pathname)
                    duration = clip.duration
                    fps = clip.fps
                    width, height = clip.size
                elif pathname.endswith(".png") or pathname.endswith(".jpg"):
                    duration = 5                                                #アップロード時、デフォルト5秒を仮に設定

                # JSONファイルの作成
                json_data = {
                    "background_file": os.path.basename(pathname),
                    "start_time": 0,
                    "duration": duration,
                }

                # JSONファイルの連番を取得
                existing_bg_files = glob.glob('json/background_*.json')
                json_bg_number = len(existing_bg_files) + 1
                json_output_path = f'json/background_{json_bg_number}.json'

                with open(json_output_path, 'w', encoding='utf-8') as f:
                    json.dump(json_data, f, ensure_ascii=False, indent=4)

                self.load_existing_json_files()

            except Exception as e:
                wx.MessageBox(f"Error processing file: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)




# Create and run the application
if __name__ == '__main__':

    temp_files = glob.glob('temp/*')  # tempファイル・クリア
    for file in temp_files:
        os.remove(file)

    app = wx.App(False)
    frame = AnimationGUI(None, title='アニメーション生成 GUI')
    frame.Show()
    app.MainLoop()
