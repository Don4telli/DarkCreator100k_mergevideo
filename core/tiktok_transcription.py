#!/usr/bin/env python3
"""
TikTok transcription module.
Handles downloading TikTok videos and transcribing them using Deepgram.
"""

import os
import tempfile
import subprocess
from pathlib import Path
from deepgram import DeepgramClient, PrerecordedOptions
from .deepgram_config import get_deepgram_api_key, get_deepgram_config

class TikTokTranscriber:
    def __init__(self):
        self.api_key = get_deepgram_api_key()
        self.config = get_deepgram_config()
    
    def download_tiktok_video(self, url, output_dir=None):
        """
        Download TikTok video using yt-dlp.
        
        Args:
            url (str): TikTok video URL
            output_dir (str): Directory to save the video (optional)
            
        Returns:
            str: Path to downloaded video file
        """
        if output_dir is None:
            output_dir = tempfile.mkdtemp()
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Output template for yt-dlp
        output_template = os.path.join(output_dir, "tiktok_video.%(ext)s")
        
        try:
            # Use yt-dlp to download the video
            cmd = [
                "yt-dlp",
                "--extract-audio",
                "--audio-format", "mp3",
                "--output", output_template,
                url
            ]
            if hasattr(self, 'cookies_path') and self.cookies_path and os.path.exists(self.cookies_path):
                cmd.insert(-1, "--cookies")
                cmd.insert(-1, self.cookies_path)
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            # Find the downloaded file
            downloaded_files = list(Path(output_dir).glob("tiktok_video.*"))
            if not downloaded_files:
                raise Exception("No file was downloaded")
            
            return str(downloaded_files[0])
            
        except subprocess.CalledProcessError as e:
            error_output = e.stderr.lower()
            if "requiring login" in error_output:
                if hasattr(self, 'cookies_path') and self.cookies_path and os.path.exists(self.cookies_path):
                    raise Exception("Falha no download mesmo com cookies fornecidos. Verifique se os cookies estão válidos.")
                else:
                    raise Exception("Este vídeo do TikTok requer autenticação. Por favor, forneça um arquivo cookies.txt.")
            else:
                raise Exception(f"Falha no download do vídeo do TikTok: {e.stderr}")
        except Exception as e:
            raise Exception(f"Error downloading TikTok video: {str(e)}")
    
    def transcribe_audio(self, audio_path):
        """
        Transcribe audio file using Deepgram SDK.
        
        Args:
            audio_path (str): Path to audio file
            
        Returns:
            dict: Transcription result from Deepgram
        """
        try:
            # Initialize Deepgram client
            deepgram = DeepgramClient(self.api_key)
            
            # Configure options
            options = PrerecordedOptions(
                model=self.config["model"],
                language=self.config["language"],
                smart_format=self.config["smart_format"],
                punctuate=self.config["punctuate"],
                diarize=self.config["diarize"],
                utterances=self.config["utterances"]
            )
            
            # Read audio file
            with open(audio_path, "rb") as audio_file:
                buffer_data = audio_file.read()
            
            # Transcribe audio
            response = deepgram.listen.prerecorded.v("1").transcribe_file(
                {"buffer": buffer_data},
                options
            )
            
            return response.to_dict()
            
        except Exception as e:
            raise Exception(f"Error transcribing audio: {str(e)}")
    
    def extract_text_from_transcription(self, transcription_result):
        """
        Extract plain text from Deepgram transcription result.
        
        Args:
            transcription_result (dict): Result from Deepgram API
            
        Returns:
            str: Extracted text
        """
        try:
            if "results" not in transcription_result:
                return "No transcription results found."
            
            channels = transcription_result["results"].get("channels", [])
            if not channels:
                return "No audio channels found in transcription."
            
            alternatives = channels[0].get("alternatives", [])
            if not alternatives:
                return "No transcription alternatives found."
            
            transcript = alternatives[0].get("transcript", "")
            return transcript.strip() if transcript else "No text found in transcription."
            
        except Exception as e:
            return f"Error extracting text: {str(e)}"
    
    def transcribe_tiktok_url(self, url, progress_callback=None, cookies_path=None):
        """
        Complete workflow: download TikTok video and transcribe it.
        
        Args:
            url (str): TikTok video URL
            progress_callback (callable): Optional callback for progress updates
            cookies_path (str): Optional path to cookies file for authenticated download
            
        Returns:
            dict: Result containing transcription text and metadata
        """
        if cookies_path:
            self.cookies_path = cookies_path
        temp_dir = None
        try:
            # Create temporary directory
            temp_dir = tempfile.mkdtemp()
            
            if progress_callback:
                progress_callback("Downloading TikTok video...", 10)
            
            # Download video
            audio_path = self.download_tiktok_video(url, temp_dir)
            
            if progress_callback:
                progress_callback("Video downloaded, starting transcription...", 50)
            
            # Transcribe audio
            transcription_result = self.transcribe_audio(audio_path)
            
            if progress_callback:
                progress_callback("Transcription completed, extracting text...", 90)
            
            # Extract text
            text = self.extract_text_from_transcription(transcription_result)
            
            if progress_callback:
                progress_callback("Transcription process completed!", 100)
            
            return {
                "success": True,
                "text": text,
                "url": url,
                "full_result": transcription_result
            }
            
        except Exception as e:
            error_msg = f"Error in TikTok transcription: {str(e)}"
            if progress_callback:
                progress_callback(error_msg, 0)
            
            return {
                "success": False,
                "error": error_msg,
                "url": url
            }
            
        finally:
            # Clean up temporary directory
            if temp_dir and os.path.exists(temp_dir):
                import shutil
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass  # Ignore cleanup errors

def transcribe_tiktok_video(url, progress_callback=None, cookies_path=None):
    """
    Convenience function to transcribe a TikTok video.
    
    Args:
        url (str): TikTok video URL
        progress_callback (callable): Optional callback for progress updates
        cookies_path (str): Optional path to cookies file for authenticated download
        
    Returns:
        dict: Transcription result
    """
    transcriber = TikTokTranscriber()
    return transcriber.transcribe_tiktok_url(url, progress_callback, cookies_path)