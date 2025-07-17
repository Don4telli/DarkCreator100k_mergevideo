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
        
    def group_images_by_prefix(self, image_paths: List[str]) -> Dict[str, List[str]]:
        """Group images by their filename prefix (A, B, C, D, etc.)"""
        groups = defaultdict(list)
        
        for image_path in image_paths:
            filename = os.path.basename(image_path)
            print(f"DEBUG: Processing filename: {filename}")
            
            # Handle uploaded files with format: image_000_originalname.ext
            if filename.startswith('image_') and '_' in filename:
                # Extract the part after the second underscore
                parts = filename.split('_', 2)
                if len(parts) >= 3:
                    original_name = parts[2]
                    # Extract prefix from original name
                    match = re.match(r'^([A-Za-z]+)', original_name)
                    if match:
                        prefix = match.group(1).upper()
                        print(f"DEBUG: Extracted prefix '{prefix}' from uploaded file: {filename}")
                        groups[prefix].append(image_path)
                        continue
            
            # Fallback: Extract prefix from beginning of filename (original logic)
            match = re.match(r'^([A-Za-z]+)', filename)
            if match:
                prefix = match.group(1).upper()
                print(f"DEBUG: Extracted prefix '{prefix}' from filename: {filename}")
                groups[prefix].append(image_path)
            else:
                # If no prefix found, put in 'DEFAULT' group
                print(f"DEBUG: No prefix found, adding to DEFAULT group: {filename}")
                groups['DEFAULT'].append(image_path)
        
        # Sort images within each group numerically
        for prefix in groups:
            def extract_number(path):
                filename = os.path.basename(path)
                # Handle uploaded files with format: image_000_originalname.ext
                if filename.startswith('image_') and '_' in filename:
                    parts = filename.split('_', 2)
                    if len(parts) >= 3:
                        original_name = parts[2]
                        # Extract number from original name (e.g., A1.png -> 1)
                        match = re.search(r'([A-Za-z]+)(\d+)', original_name)
                        if match:
                            return int(match.group(2))
                else:
                    # Extract number from filename (e.g., A1.png -> 1)
                    match = re.search(r'([A-Za-z]+)(\d+)', filename)
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
        """Create a video from grouped images, where each group video has the full audio length."""
        try:
            fps = int(fps)
            print(f"DEBUG: create_multi_video_with_separators called with {len(image_paths)} images")
            print(f"DEBUG: green_screen_duration = {green_screen_duration}")
            print(f"DEBUG: aspect_ratio = {aspect_ratio}")
            
            self.validate_inputs(image_paths, audio_path)
            width, height = self.get_aspect_ratio_dimensions(aspect_ratio)

            # Phase 1: Initial processing (0-10%)
            if progress_callback: progress_callback("Grouping images...", 2)
            image_groups = self.group_images_by_prefix(image_paths)
            print(f"DEBUG: Found {len(image_groups)} image groups: {list(image_groups.keys())}")
            if not image_groups:
                raise ValueError("No image groups found.")

            if progress_callback: progress_callback("Loading audio...", 5)
            audio_clip = AudioFileClip(audio_path)
            audio_duration = audio_clip.duration

            if progress_callback: progress_callback("Preparing segments...", 10)

            video_segments = []
            num_groups = len(image_groups)
            sorted_groups = sorted(image_groups.items())

            # Phase 2: Creating segments in memory (10-50%)
            segment_progress_start = 10
            segment_progress_total = 40
            progress_per_group = segment_progress_total / num_groups if num_groups > 0 else 0

            for i, (prefix, group_images) in enumerate(sorted_groups):
                print(f"DEBUG: Processing group {i+1}/{num_groups}: '{prefix}' with {len(group_images)} images")
                if not group_images:
                    self.logger.warning(f"Skipping empty image group: {prefix}")
                    continue

                if progress_callback:
                    progress = segment_progress_start + ((i + 1) / num_groups) * segment_progress_total
                    progress_callback(f"Creating segment for '{prefix}' ({i+1}/{num_groups})", progress)

                print(f"DEBUG: About to call create_video_from_images for group '{prefix}'")
                try:
                    # Create video clip in memory (no output_path = returns VideoClip)
                    group_video = self.create_video_from_images(
                        image_paths=group_images,
                        audio_path=audio_path,
                        output_path=None,  # Key: process in memory
                        width=width,
                        height=height,
                        fps=fps,
                        progress_callback=None  # Avoid nested progress callbacks
                    )
                    print(f"DEBUG: create_video_from_images returned: {type(group_video)} for group '{prefix}'")
                    if group_video and hasattr(group_video, 'duration') and group_video.duration > 0:
                        video_segments.append(group_video)
                        print(f"DEBUG: Successfully created segment for '{prefix}' with duration {group_video.duration}s.")
                        self.logger.info(f"Successfully created segment for '{prefix}' with duration {group_video.duration}s.")
                    else:
                        print(f"DEBUG: Failed to create valid video segment for group '{prefix}'. group_video={group_video}")
                        self.logger.warning(f"Failed to create a valid video segment for group '{prefix}'. It will be skipped.")
                except Exception as e:
                    print(f"DEBUG: Exception during video segment creation for '{prefix}': {str(e)}")
                    self.logger.error(f"Exception creating segment for '{prefix}': {str(e)}")
                    continue

            print(f"DEBUG: Created {len(video_segments)} video segments out of {num_groups} groups.")
            self.logger.debug(f"Created {len(video_segments)} video segments out of {num_groups} groups.")
            if not video_segments:
                raise ValueError("No valid video segments could be created. Please check image files and logs.")

            # Phase 3: Concatenating clips (50-60%)
            if progress_callback: progress_callback("Concatenating video segments...", 50)

            final_clips = []
            print(f"DEBUG: Building final clips list with {len(video_segments)} segments")
            for i, segment in enumerate(video_segments):
                print(f"DEBUG: Adding segment {i+1}/{len(video_segments)} to final clips")
                final_clips.append(segment)
                if i < len(video_segments) - 1:
                    print(f"DEBUG: Creating green screen separator {i+1}")
                    green_clip = self.create_green_screen_clip(green_screen_duration, width, height)
                    final_clips.append(green_clip)
            print(f"DEBUG: Final clips list has {len(final_clips)} clips total")

            # Ensure all clips have a numeric duration
            for i, clip in enumerate(final_clips):
                duration = getattr(clip, 'duration', 0)
                logging.debug(f"Clip {i}: type={type(clip)}, original duration={repr(duration)}, type={type(duration)}")
                if duration is None:
                    duration = 0
                
                try:
                    numeric_duration = float(duration)
                except (ValueError, TypeError):
                    logging.error(f"Could not convert duration '{duration}' to float for clip {i}. Defaulting to 0.")
                    numeric_duration = 0.0
                
                clip.duration = numeric_duration

            if not final_clips:
                raise ValueError("No video clips to process.")

            print(f"DEBUG: About to concatenate {len(final_clips)} clips")
            final_video = concatenate_videoclips(final_clips, method="compose")
            print(f"DEBUG: Video concatenation completed successfully")
            if progress_callback: progress_callback("Video segments concatenated.", 60)

            # Phase 4: Creating audio track (60-70%)
            if progress_callback: progress_callback("Creating audio track...", 60)
            print(f"DEBUG: Creating audio track for {num_groups} groups")
            from moviepy.editor import concatenate_audioclips
            audio_segments = []
            for i in range(num_groups):
                audio_segments.append(audio_clip)
                if i < num_groups - 1:  # Add silence for green screen (except after last group)
                    silence = audio_clip.subclip(0, green_screen_duration).volumex(0)  # Silent audio
                    audio_segments.append(silence)
            
            print(f"DEBUG: Concatenating {len(audio_segments)} audio segments")
            final_audio = concatenate_audioclips(audio_segments)
            print(f"DEBUG: Setting audio to final video")
            
            final_video = final_video.set_audio(final_audio)
            if final_video.duration > final_video.audio.duration:
                final_video.duration = final_video.audio.duration
            print(f"DEBUG: Final video prepared, duration: {final_video.duration}s")
            if progress_callback: progress_callback("Audio track created.", 70)

            # Phase 5: Writing final video (70-100%)
            if progress_callback: progress_callback("Writing final video...", 70)
            
            # Custom progress tracking for video writing
            class VideoWriteProgressLogger:
                def __init__(self, callback, start_progress=70, end_progress=100):
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
            
            progress_logger = VideoWriteProgressLogger(progress_callback)

            print(f"DEBUG: About to write final video to: {output_path}")

            # *** CORREÇÃO APLICADA ***
            # verbose=False para não poluir os logs
            # logger=progress_logger para ativar o callback de progresso
            final_video.write_videofile(
                output_path,
                fps=fps,
                codec='libx264',
                audio_codec='aac',
                verbose=False, 
                logger=progress_logger, 
                temp_audiofile='temp-audio.m4a',
                remove_temp=True
            )
            print(f"DEBUG: Video file writing completed successfully")
            if progress_callback: progress_callback("Video created successfully!", 100)
            
            # Check file size
            import os
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                print(f"DEBUG: Output file size: {file_size} bytes")
                if file_size < 1000:
                    print(f"DEBUG: WARNING - File size is suspiciously small: {file_size} bytes")
            else:
                print(f"DEBUG: ERROR - Output file does not exist: {output_path}")

            # Memory-based processing completed successfully
            print("DEBUG: Video processing completed using in-memory clips")

            # Clean up
            if isinstance(audio_clip, AudioFileClip):
                audio_clip.close()
            if isinstance(final_audio, AudioFileClip):
                final_audio.close()
            final_video.close()
            for seg in video_segments:
                seg.close()
            for cl in final_clips:
                cl.close()
            
        except Exception as e:
            self.logger.error(f"Error creating multi-video: {str(e)}")
            if progress_callback:
                progress_callback(f"Error: {str(e)}", 0)
            raise
    
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