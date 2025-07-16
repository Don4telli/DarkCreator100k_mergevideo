#!/usr/bin/env python3
"""
Deepgram configuration module.
Contains API key and configuration for Deepgram transcription service.
"""

# Hardcoded Deepgram API key
DEEPGRAM_API_KEY = "2ee8b707f933f130ad3c73aec75cfdc0a470b45e"

# Deepgram configuration settings
DEEPGRAM_CONFIG = {
    "model": "nova-3",
    "language": "multi",
    "smart_format": True,
    "punctuate": True,
    "diarize": False,
    "utterances": True
}

def get_deepgram_api_key():
    """Get the Deepgram API key."""
    return DEEPGRAM_API_KEY

def get_deepgram_config():
    """Get the Deepgram configuration."""
    return DEEPGRAM_CONFIG