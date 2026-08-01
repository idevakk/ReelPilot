import os
import glob
import subprocess
import wave
import shutil
import re
import random
from datetime import datetime
from urllib.parse import urljoin
from pathlib import Path
import numpy as np
import cv2
import requests
from bs4 import BeautifulSoup
from moviepy.editor import (
    VideoFileClip, 
    CompositeVideoClip, 
    AudioFileClip, 
    ColorClip, 
    concatenate_videoclips, 
    CompositeAudioClip
)

from .config import OUTPUT_DIR

ENDPOINTS = [
    "https://transitionalhooks.com/social-media-video-hook-library/",
    "https://transitionalhooks.com/social-media-video-hook-library/page/2/",
    "https://onlinepath.com.au/blog/100-best-viral-video-hooks-2024/"
]

# ==========================================
# MODULE 1: REMOTE VIDEO FETCHER
# ==========================================
class RemoteVideoFetcher:
    def __init__(self, endpoints, download_dir="./raw_clips"):
        self.endpoints = endpoints
        self.download_dir = download_dir
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def _scrape_mp4_links(self):
        found_urls = set()
        for url in self.endpoints:
            try:
                response = requests.get(url, headers=self.headers, timeout=15)
                if response.status_code != 200:
                    continue
                html_content = response.text
                
                soup = BeautifulSoup(html_content, "html.parser")
                for tag in soup.find_all(["video", "source", "a"]):
                    src = tag.get("src") or tag.get("href")
                    if src and ".mp4" in src.lower():
                        found_urls.add(urljoin(url, src))
                
                regex_urls = re.findall(r'https?://[^\s<>"]+?\.mp4', html_content, re.IGNORECASE)
                for r_url in regex_urls:
                    found_urls.add(r_url)
            except Exception:
                continue
        return list(found_urls)

    def fetch(self, target_count):
        if os.path.exists(self.download_dir):
            shutil.rmtree(self.download_dir)
        os.makedirs(self.download_dir, exist_ok=True)

        mp4_links = self._scrape_mp4_links()
        if not mp4_links:
            raise RuntimeError("Could not find any .mp4 links across the provided endpoints.")
            
        # Randomize the fetched links before downloading
        random.shuffle(mp4_links)
            
        downloaded = 0
        for i, video_url in enumerate(mp4_links):
            if downloaded >= target_count:
                break
            file_path = os.path.join(self.download_dir, f"remote_clip_{downloaded + 1:03d}.mp4")
            try:
                with requests.get(video_url, headers=self.headers, stream=True, timeout=20) as r:
                    r.raise_for_status()
                    with open(file_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                downloaded += 1
            except Exception:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    
        if downloaded < 2:
            raise RuntimeError(f"Only fetched {downloaded} videos. Need at least 2.")
        return downloaded


# ==========================================
# MODULE 2: PREMIUM REEL PIPELINE
# ==========================================
class PremiumReelPipeline:
    def __init__(self, target_w=1080, target_h=1920, fps=30):
        self.W = target_w
        self.H = target_h
        self.FPS = fps
        self.TRANSITION_DURATION = 0.65
        self.GAP_PIXELS = 15
        self.VIDEO_BITRATE = "12M"
        self.AUDIO_BITRATE = "256k"
        self.temp_dir = "./_reel_workspace"
        self.foley_path = os.path.join(self.temp_dir, "temp_swoosh.wav")

    def _setup_workspace(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        os.makedirs(self.temp_dir, exist_ok=True)

    def _cleanup_workspace(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _conform_clip(self, input_path, output_path):
        vf_filter = (
            "crop='if(gt(iw/ih,9/16),trunc(ih*9/16/2)*2,iw)':"
            "'if(gt(iw/ih,9/16),ih,trunc(iw*16/9/2)*2)',"
            f"scale={self.W}:{self.H}:flags=lanczos"
        )
        command = [
            "ffmpeg", "-y", "-i", input_path, "-vf", vf_filter,
            "-r", str(self.FPS), "-c:v", "libx264", "-preset", "fast",
            "-b:v", self.VIDEO_BITRATE, "-maxrate", self.VIDEO_BITRATE,
            "-bufsize", self.VIDEO_BITRATE, "-c:a", "aac",
            "-b:a", self.AUDIO_BITRATE, "-ar", "44100", "-ac", "2", output_path
        ]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def _generate_swoosh_foley(self):
        sample_rate = 44100
        t = np.linspace(0, self.TRANSITION_DURATION, int(sample_rate * self.TRANSITION_DURATION), endpoint=False)
        freq = 140 - 100 * (t / self.TRANSITION_DURATION)
        envelope = np.sin(np.pi * (t / self.TRANSITION_DURATION)) ** 2
        audio_data = (0.5 * 32767 * np.sin(2 * np.pi * freq * t) * envelope).astype(np.int16)
        
        with wave.open(self.foley_path, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_data.tobytes())

    def _safe_subclip(self, clip, start, end):
        try:
            return clip.subclipped(start, end)
        except AttributeError:
            return clip.subclip(start, end)

    @staticmethod
    def ease_out_cubic(t_norm):
        return 1 - pow(1 - t_norm, 3)

    def apply_velocity_blur(self, image, t):
        t_norm = t / self.TRANSITION_DURATION
        velocity = 3 * pow(1 - t_norm, 2) 
        blur_amount = int(35 * velocity)
        if blur_amount % 2 == 0:
            blur_amount += 1 
        if blur_amount < 3:
            return image
        kernel = np.zeros((blur_amount, blur_amount))
        kernel[:, int((blur_amount - 1)/2)] = np.ones(blur_amount)
        kernel /= blur_amount
        return cv2.filter2D(image, -1, kernel)

    def build_transition(self, clip_a, clip_b):
        a_tail = self._safe_subclip(clip_a, clip_a.duration - self.TRANSITION_DURATION, clip_a.duration)
        b_head = self._safe_subclip(clip_b, 0, self.TRANSITION_DURATION)
        total_travel = self.H + self.GAP_PIXELS

        a_moving = a_tail.set_position(
            lambda t: ('center', -total_travel * self.ease_out_cubic(t / self.TRANSITION_DURATION))
        ).without_audio()
        
        b_moving = b_head.set_position(
            lambda t: ('center', total_travel - (total_travel * self.ease_out_cubic(t / self.TRANSITION_DURATION)))
        )

        bg = ColorClip(size=(self.W, self.H), color=(0,0,0)).set_duration(self.TRANSITION_DURATION)
        transition_comp = CompositeVideoClip([bg, a_moving, b_moving], size=(self.W, self.H))
        transition_comp = transition_comp.fl(lambda gf, t: self.apply_velocity_blur(gf(t), t))
        
        foley_audio = AudioFileClip(self.foley_path)
        combined_audio = CompositeAudioClip([b_moving.audio, foley_audio]) if b_moving.audio else foley_audio
        transition_comp = transition_comp.set_audio(combined_audio)
        
        return transition_comp.set_duration(self.TRANSITION_DURATION)

    def run(self, input_folder, output_filename="master_reel.mp4", progress_callback=None):
        file_pattern = os.path.join(input_folder, "*.mp4")
        raw_files = sorted(glob.glob(file_pattern))
        if len(raw_files) < 2:
            raise ValueError("Require minimum 2 clips in the input folder.")

        self._setup_workspace()
        self._generate_swoosh_foley()
        
        conformed_files = []
        for i, file_path in enumerate(raw_files):
            if progress_callback:
                progress_callback(0.1 + (0.3 * (i / len(raw_files))), f"Normalizing clip {i+1}/{len(raw_files)}...")
            filename = os.path.basename(file_path)
            temp_output = os.path.join(self.temp_dir, f"{i:03d}_{filename}")
            self._conform_clip(file_path, temp_output)
            conformed_files.append(temp_output)
            
        if progress_callback:
            progress_callback(0.4, "Building physics timeline & foley...")
        clips = [VideoFileClip(f) for f in conformed_files]
        final_sequence = []
        
        for i, current_clip in enumerate(clips):
            start_time = 0 if i == 0 else self.TRANSITION_DURATION
            end_time = current_clip.duration if i == (len(clips) - 1) else (current_clip.duration - self.TRANSITION_DURATION)
            body_clip = self._safe_subclip(current_clip, start_time, end_time)
            final_sequence.append(body_clip)
            
            if i < len(clips) - 1:
                transition = self.build_transition(current_clip, clips[i + 1])
                final_sequence.append(transition)
                
        if progress_callback:
            progress_callback(0.6, "Rendering video (Step 1: Audio -> Step 2: Video)...")
        master_video = concatenate_videoclips(final_sequence, method="compose")
        
        master_video.write_videofile(
            str(output_filename),
            fps=self.FPS,
            codec="libx264",
            audio_codec="aac",
            preset="fast",   
            threads=4,         
            bitrate="12000k",
            logger=None # Suppress MoviePy terminal spam for cleaner UI performance
        )
        
        master_video.close()
        for clip in clips:
            clip.close()
        self._cleanup_workspace()
        return output_filename

def run_mashup(count: int, output_path: Path | None = None) -> Path:
    local_dir = OUTPUT_DIR / "_mashup_raw"
    os.makedirs(local_dir, exist_ok=True)
    
    # Clean previous raw clips
    for f in local_dir.glob("*.mp4"):
        try: os.remove(f)
        except Exception: pass
        
    print(f"Scraping endpoints for {count} random remote hook .mp4 links...")
    fetcher = RemoteVideoFetcher(endpoints=ENDPOINTS, download_dir=str(local_dir))
    fetcher.fetch(target_count=count)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = f"mashup_{timestamp}"
    
    if output_path is None:
        target_dir = OUTPUT_DIR / slug
        target_dir.mkdir(parents=True, exist_ok=True)
        output_file = target_dir / f"{slug}.mp4"
    else:
        output_file = output_path
        
    print("Building and rendering the master sequence...")
    pipeline = PremiumReelPipeline()
    pipeline.run(str(local_dir), str(output_file))
    
    # Optional: write a sidecar for the web UI
    if output_path is None:
        sidecar = target_dir / f"{slug}.txt"
        sidecar.write_text(f"Hook Mashup: {count} clips joined natively.", encoding="utf-8")
        
    print(f"[Success] Mashup generated at {output_file}")
    
    # Clean up local raw dir
    try: shutil.rmtree(local_dir)
    except: pass
    
    return output_file
