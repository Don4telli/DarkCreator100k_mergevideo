import os
import logging
import traceback
import tempfile
from pathlib import Path
from typing import List, Dict, Tuple
from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips, ColorClip, VideoFileClip
import numpy as np
import cv2
from collections import defaultdict
import numpy as np
import cv2
import re

class VideoProcessor:
    """Handles video creation from images and audio"""
    
    # Aspect ratio presets
    ASPECT_RATIOS = {
        '1:1': (1080, 1080),
        '16:9': (1920, 1080),
        '9:16': (1080, 1920)
    }
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    # NO ARQUIVO: core/video_processor.py

    def group_images_by_prefix(self, image_paths: List[str]) -> Dict[str, List[str]]:
        """Group images by their original filename prefix (A, B, C, D, etc.), ignoring any timestamp prefixes."""
        groups = defaultdict(list)

        for image_path in image_paths:
            filename = os.path.basename(image_path)
            
            # *** CORREÇÃO PRINCIPAL ***
            # Remove o prefixo de timestamp (ex: "1752771563_") para obter o nome original.
            original_name = filename.split('_', 1)[-1] if '_' in filename else filename
            
            print(f"DEBUG: Processing original filename: {original_name}")

            match = re.match(r'^([A-Za-z]+)', original_name)
            if match:
                prefix = match.group(1).upper()
                print(f"DEBUG: Extracted prefix '{prefix}' from: {original_name}")
                groups[prefix].append(image_path)
            else:
                print(f"DEBUG: No prefix found in '{original_name}', adding to DEFAULT group.")
                groups['DEFAULT'].append(image_path)
        
        # Sort images within each group numerically
        for prefix in groups:
            def extract_number(path):
                filename = os.path.basename(path)
                # Também usa o nome original para extrair o número
                original_name = filename.split('_', 1)[-1] if '_' in filename else filename
                
                # Extrai o número do nome do arquivo (e.g., A1.png -> 1)
                match = re.search(r'([A-Za-z]+)(\d+)', original_name)
                if match:
                    return int(match.group(2))
                return 0  # Default if no number found
            
            groups[prefix].sort(key=extract_number)
            print(f"DEBUG: Sorted group '{prefix}': {[os.path.basename(p) for p in groups[prefix]]}")
            
        print(f"DEBUG: Final groups: {dict(groups)}")
        return dict(groups)
    
    def create_green_screen_clip(self, duration: float, width: int, height: int) -> ColorClip:
        """Create a green screen clip for separating videos"""
        # Create a bright green screen (chroma key green)
        green_color = (0, 255, 0)  # RGB for bright green
        return ColorClip(size=(width, height), color=green_color, duration=duration)
    
    def get_aspect_ratio_dimensions(self, aspect_ratio: str) -> Tuple[int, int]:
        """Get width and height for a given aspect ratio preset"""
        if aspect_ratio in self.ASPECT_RATIOS:
            return self.ASPECT_RATIOS[aspect_ratio]
        else:
            # Default to 16:9 if invalid aspect ratio
            return self.ASPECT_RATIOS['16:9']
        
    def get_audio_duration(self, audio_path: str) -> float:
        """Get the duration of an audio file in seconds"""
        try:
            audio_clip = AudioFileClip(audio_path)
            duration = audio_clip.duration
            audio_clip.close()
            return duration
        except Exception as e:
            self.logger.error(f"Error getting audio duration: {str(e)}")
            raise
    
    def validate_inputs(self, image_paths: List[str], audio_path: str) -> bool:
        """Validate that all input files exist and are valid"""
        # Check if audio file exists
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        # Check if all image files exist
        for image_path in image_paths:
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"Image file not found: {image_path}")
        
        # Check if we have at least one image
        if len(image_paths) == 0:
            raise ValueError("No images provided")
        
        return True
    
    def create_video_from_images(self, image_paths: List[str], audio_path: str, output_path: str, width=1920, height=1080, fps=30, progress_callback=None):
        """Create a video from a list of images with timing based on audio length. Returns a VideoClip if output_path is None."""
        try:
            self.validate_inputs(image_paths, audio_path)
            
            if progress_callback:
                progress_callback("Loading audio file...", 10)
            
            # Get audio duration
            audio_clip = AudioFileClip(audio_path)
            audio_duration = audio_clip.duration
            
            # Calculate duration for each image
            total_images = len(image_paths)
            seconds_per_image = audio_duration / total_images
            
            self.logger.info(f"Audio duration: {audio_duration}s")
            self.logger.info(f"Total images: {total_images}")
            self.logger.info(f"Seconds per image: {seconds_per_image}s")
            
            if progress_callback:
                progress_callback(f"Processing {total_images} images...", 30)
            
            # Create video clips from images
            image_clips = []
            for i, image_path in enumerate(image_paths):
                try:
                    clip = ImageClip(image_path).set_duration(seconds_per_image).resize((width, height))
                    image_clips.append(clip)
                    
                    if progress_callback:
                        progress = 30 + (i / total_images) * 40
                        progress_callback(f"Processing image {i+1}/{total_images}", progress)
                        
                except Exception as e:
                    self.logger.warning(f"Error processing image {image_path}: {str(e)}")
                    continue
            
            if not image_clips:
                raise ValueError("No valid images could be processed")
            
            if progress_callback:
                progress_callback("Combining images into video...", 70)
            
            # Concatenate all clips
            final_clip = concatenate_videoclips(image_clips)
            
            # Add audio
            final_clip = final_clip.set_audio(audio_clip)
            
            if progress_callback:
                progress_callback("Rendering final video...", 80)
            
            if output_path:
                # Ensure output directory exists
                output_dir = Path(output_path).parent
                output_dir.mkdir(parents=True, exist_ok=True)
                # Write final video to file
                final_clip.write_videofile(
                    output_path,
                    fps=fps,
                    codec='libx264',
                    audio_codec='aac',
                    verbose=False,
                    logger='bar'
                )
                if progress_callback:
                    progress_callback("Video created successfully!", 100)
                # Close all clips to free memory
                final_clip.close()
                audio_clip.close()
                for clip in image_clips:
                    clip.close()
                self.logger.info(f"Video created successfully: {output_path}")
                return None
            else:
                # Return the clip without writing to file
                # Note: Don't close clips here as they're still needed
                return final_clip
            
        except Exception as e:
            self.logger.error(f"Error creating video: {str(e)}")
            if progress_callback:
                progress_callback(f"Error: {str(e)}", 0)
            raise
    
    def create_multi_video_with_separators(self, image_paths: List[str], audio_path: str, output_path: str, 
                                          aspect_ratio='9:16', fps=30, green_screen_duration=2.0, progress_callback=None) -> None:
        """Create a video from grouped images, with improved error handling and cleanup."""
        # Listas para rastrear objetos que precisam ser fechados
        clips_to_close = []
        
        try:
            # --- FASE 1: SETUP (0-10%) ---
            if progress_callback: progress_callback("Initializing...", 1)
            fps = int(fps)
            self.validate_inputs(image_paths, audio_path)
            width, height = self.get_aspect_ratio_dimensions(aspect_ratio)
            if progress_callback: progress_callback("Grouping images...", 5)
            image_groups = self.group_images_by_prefix(image_paths)
            if not image_groups:
                raise ValueError("Image grouping failed. Check image filenames for prefixes like 'A1, B1'.")
            
            if progress_callback: progress_callback("Loading main audio...", 8)
            audio_clip = AudioFileClip(audio_path)
            clips_to_close.append(audio_clip)

            # --- FASE 2: CRIAR SEGMENTOS (10-50%) ---
            video_segments = []
            num_groups = len(image_groups)
            sorted_groups = sorted(image_groups.items())

            for i, (prefix, group_images) in enumerate(sorted_groups):
                progress = 10 + (i / num_groups) * 40
                if progress_callback: progress_callback(f"Creating segment for '{prefix}' ({i+1}/{num_groups})", progress)
                
                group_video = self.create_video_from_images(
                    image_paths=group_images, audio_path=audio_path, output_path=None,
                    width=width, height=height, fps=fps
                )
                if group_video:
                    video_segments.append(group_video)
                    clips_to_close.append(group_video)
            
            if not video_segments:
                raise ValueError("No valid video segments could be created.")
            
            # --- FASE 3: COMPOSIÇÃO FINAL (50-70%) ---
            if progress_callback: progress_callback("Combining segments...", 55)
            final_clips = []
            for i, segment in enumerate(video_segments):
                final_clips.append(segment)
                if i < len(video_segments) - 1:
                    green_clip = self.create_green_screen_clip(green_screen_duration, width, height)
                    final_clips.append(green_clip)
                    clips_to_close.append(green_clip)
            
            final_video_no_audio = concatenate_videoclips(final_clips)
            clips_to_close.append(final_video_no_audio)
            
            if progress_callback: progress_callback("Creating final audio track...", 65)
            from moviepy.editor import concatenate_audioclips
            audio_segments = []
            for i in range(len(video_segments)):
                temp_audio = AudioFileClip(audio_path)
                clips_to_close.append(temp_audio)
                audio_segments.append(temp_audio)
                if i < len(video_segments) - 1:
                    silence = AudioFileClip(audio_path).subclip(0, green_screen_duration).volumex(0)
                    clips_to_close.append(silence)
                    audio_segments.append(silence)
                    
            final_audio = concatenate_audioclips(audio_segments)
            clips_to_close.append(final_audio)
            
            final_video = final_video_no_audio.set_audio(final_audio)
            final_video.duration = final_audio.duration
            clips_to_close.append(final_video)
            
            # --- FASE 4: RENDERIZAÇÃO E VERIFICAÇÃO (70-100%) ---
            if progress_callback: progress_callback("Rendering final video...", 70)
            
            # Custom progress tracking for video writing
            class VideoWriteProgressLogger:
                def __init__(self, callback, start_progress=70, end_progress=99):
                    self.callback = callback
                    self.start_progress = start_progress
                    self.progress_range = end_progress - start_progress
                    self.last_progress = start_progress
                
                def __call__(self, *args, **kwargs):
                    # MoviePy logger callback with (bar_name, current_frame, total_frames)
                    if len(args) == 3 and args[2] > 0:
                        bar_name, current_frame, total_frames = args
                        write_progress = (current_frame / total_frames) * 100
                        total_progress = self.start_progress + (write_progress / 100) * self.progress_range
                        
                        # Only update if progress increased significantly (reduce callback frequency)
                        if total_progress - self.last_progress >= 1:
                            if self.callback:
                                self.callback(f"Writing video: {int(write_progress)}% complete", total_progress)
                            self.last_progress = total_progress
                
                def iter_bar(self, **kwargs):
                    # Handle audio processing progress
                    iterable = kwargs.get('iterable', [])
                    total_items = len(list(iterable)) if hasattr(iterable, '__len__') else 100
                    for i, item in enumerate(iterable):
                        if self.callback and total_items > 0:
                            audio_progress = (i / total_items) * 20  # Audio is ~20% of writing process
                            total_progress = self.start_progress + audio_progress
                            if total_progress - self.last_progress >= 2:
                                self.callback(f"Processing audio: {int((i/total_items)*100)}%", total_progress)
                                self.last_progress = total_progress
                        yield item
                
                def bars_end(self):
                    if self.callback:
                        self.callback("Finalizing video file...", 95)
            
            progress_logger = VideoWriteProgressLogger(progress_callback, start_progress=70, end_progress=99)
            
            print("DEBUG: About to write final video with custom logger...")
            # Use um nome de arquivo de áudio temporário único para evitar conflitos em execuções paralelas
            import tempfile
            import os
            temp_audiofile_name = os.path.join(tempfile.gettempdir(), f'temp-audio-{os.urandom(8).hex()}.m4a')
            
            final_video.write_videofile(
                output_path,
                fps=fps,
                codec='libx264',
                audio_codec='aac',
                temp_audiofile=temp_audiofile_name,
                remove_temp=True,
                logger=progress_logger
            )
            print("DEBUG: MoviePy's write_videofile function has completed.")
            
            # VERIFICAÇÃO FINAL E CRÍTICA
            if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
                raise RuntimeError(f"FATAL ERROR: Video file was not created properly or is empty. Please check logs.")

            if progress_callback: progress_callback("Video created successfully!", 100)

        except Exception as e:
            # Log completo e detalhado para aparecer nos logs do Cloud Run
            print("--- CRITICAL ERROR IN VIDEO PROCESSING THREAD ---")
            import traceback
            traceback.print_exc()
            print("-------------------------------------------------")
            if progress_callback:
                # Envia um sinal de erro claro para o frontend
                progress_callback(f"Error: {str(e)}", -1) 
            # Re-levanta a exceção para que a thread termine
            raise

        finally:
            # Bloco de limpeza para liberar memória, não importa o que aconteça
            print("DEBUG: Final cleanup process started...")
            for clip in clips_to_close:
                try:
                    clip.close()
                except:
                    pass # Ignora erros durante o fechamento
            print("DEBUG: Final cleanup complete.")
    
    def get_supported_image_formats(self) -> List[str]:
        """Get list of supported image formats"""
        return ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp']
    
    def get_supported_audio_formats(self) -> List[str]:
        """Get list of supported audio formats"""
        return ['.mp3', '.wav', '.aac', '.m4a', '.ogg', '.flac']
    
    def detect_green_screen_segments(self, video_path: str, green_threshold: float = 0.8, progress_callback=None) -> List[Tuple[float, float]]:
        """Detect green screen segments in a video and return their time ranges"""
        try:
            if progress_callback:
                progress_callback("Loading video...", 10)
            
            video = VideoFileClip(video_path)
            fps = video.fps
            duration = video.duration
            
            green_segments = []
            current_green_start = None
            
            # Sample frames at regular intervals (every 2 seconds for faster processing)
            sample_interval = 2.0
            total_samples = int(duration / sample_interval)
            
            for i, t in enumerate(np.arange(0, duration, sample_interval)):
                if progress_callback:
                    progress = 10 + (i / total_samples) * 70
                    progress_callback(f"Analyzing frame at {t:.1f}s...", progress)
                
                try:
                    frame = video.get_frame(t)
                    is_green = self._is_green_screen_frame(frame, green_threshold)
                    
                    if is_green and current_green_start is None:
                        # Start of green screen segment
                        current_green_start = t
                    elif not is_green and current_green_start is not None:
                        # End of green screen segment
                        green_segments.append((current_green_start, t))
                        current_green_start = None
                        
                except Exception as e:
                    self.logger.warning(f"Error processing frame at {t}s: {str(e)}")
                    continue
            
            # Handle case where video ends with green screen
            if current_green_start is not None:
                green_segments.append((current_green_start, duration))
            
            video.close()
            
            if progress_callback:
                progress_callback(f"Found {len(green_segments)} green screen segments", 80)
            
            return green_segments
            
        except Exception as e:
            self.logger.error(f"Error detecting green screen segments: {str(e)}")
            raise
    
    def _is_green_screen_frame(self, frame: np.ndarray, threshold: float = 0.8) -> bool:
        """Check if a frame is predominantly green screen"""
        # Convert RGB to HSV for better green detection
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        
        # Define green color range in HSV
        # Green hue is around 60 in HSV (0-179 range)
        lower_green = np.array([40, 50, 50])   # Lower bound for green
        upper_green = np.array([80, 255, 255]) # Upper bound for green
        
        # Create mask for green pixels
        green_mask = cv2.inRange(hsv, lower_green, upper_green)
        
        # Calculate percentage of green pixels
        total_pixels = frame.shape[0] * frame.shape[1]
        green_pixels = np.sum(green_mask > 0)
        green_percentage = green_pixels / total_pixels
        
        return green_percentage > threshold