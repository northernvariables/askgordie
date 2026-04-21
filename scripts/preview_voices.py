#!/usr/bin/env python3
"""Preview all available Chirp3 HD voices with each persona.

Generates sample audio for each persona × voice combination.
Run on the Pi to hear through the speaker, or locally to save WAV files.

Usage:
    python scripts/preview_voices.py [--play] [--persona laurier]
"""

import argparse
import base64
import io
import json
import os
import sys
import wave

import httpx

# All available Chirp3 HD voices
VOICES = [
    ("Alnilam", "Warm, steady male"),
    ("Achird", "Clear, direct male"),
    ("Algieba", "Rich, resonant male"),
    ("Enceladus", "Deep, authoritative male"),
    ("Fenrir", "Strong, commanding male"),
    ("Puck", "Lighter, younger male"),
    ("Aoede", "Warm female"),
    ("Charon", "Deep, measured voice"),
    ("Kore", "Clear, expressive female"),
]

# Sample phrases per persona
PERSONA_SAMPLES = {
    "laurier": {
        "name": "Sir Wilfrid Laurier",
        "text": "The twentieth century shall be the century of Canada. I have always believed that this great country, stretching from sea to sea, is destined for greatness if we can but learn to live together in harmony.",
    },
    "pearson": {
        "name": "Lester B. Pearson",
        "text": "Politics is the skilled use of blunt objects. But peacekeeping, now that requires a different kind of skill — the patience to listen, the courage to compromise, and the wisdom to know when both are needed.",
    },
    "douglas": {
        "name": "Tommy Douglas",
        "text": "I don't mind being called a dreamer. Every good thing that ever happened in this country started with someone who dared to dream that ordinary people deserved a better deal. Medicare wasn't a dream — it was common sense.",
    },
    "diefenbaker": {
        "name": "John Diefenbaker",
        "text": "I am a Canadian, free to speak without fear, free to worship in my own way, free to stand for what I think right, free to oppose what I believe wrong, and free to choose who shall govern my country.",
    },
}

TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1beta1/text:synthesize"


def get_access_token():
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not creds_path:
        print("ERROR: Set GOOGLE_APPLICATION_CREDENTIALS to your service account key path")
        sys.exit(1)

    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(Request())
    return creds.token


def synthesize(text: str, voice_name: str, token: str) -> bytes:
    full_name = f"en-US-Chirp3-HD-{voice_name}"
    response = httpx.post(
        TTS_ENDPOINT,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "x-goog-user-project": "canada-gpt-ca",
        },
        json={
            "input": {"text": text},
            "voice": {"name": full_name, "languageCode": "en-US"},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 16000, "speakingRate": 1.0},
        },
        timeout=15.0,
    )
    if response.status_code != 200:
        print(f"  ERROR: {response.status_code} — {response.json().get('error', {}).get('message', '')}")
        return b""

    audio_b64 = response.json()["audioContent"]
    return base64.b64decode(audio_b64)


def save_wav(pcm_data: bytes, path: str):
    """Save raw WAV bytes to a file."""
    with open(path, "wb") as f:
        f.write(pcm_data)


def play_wav(wav_data: bytes):
    """Play WAV data through the system default output."""
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_data)
        f.flush()
        subprocess.run(["paplay", f.name], timeout=30)
        os.unlink(f.name)


def main():
    parser = argparse.ArgumentParser(description="Preview Chirp3 HD voices for each persona")
    parser.add_argument("--play", action="store_true", help="Play audio through speakers (requires paplay)")
    parser.add_argument("--persona", type=str, default="", help="Preview only this persona (laurier/pearson/douglas/diefenbaker)")
    parser.add_argument("--voice", type=str, default="", help="Preview only this voice")
    parser.add_argument("--output-dir", type=str, default="voice_previews", help="Directory for WAV files")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    token = get_access_token()

    personas = PERSONA_SAMPLES
    if args.persona:
        personas = {args.persona: PERSONA_SAMPLES[args.persona]}

    voices = VOICES
    if args.voice:
        voices = [(v, d) for v, d in VOICES if v.lower() == args.voice.lower()]

    for persona_slug, info in personas.items():
        print(f"\n{'='*60}")
        print(f"  {info['name']}")
        print(f"{'='*60}")

        for voice_name, voice_desc in voices:
            print(f"\n  Voice: {voice_name} ({voice_desc})")
            print(f"  Text: \"{info['text'][:80]}...\"")

            wav_data = synthesize(info["text"], voice_name, token)
            if not wav_data:
                continue

            filename = f"{args.output_dir}/{persona_slug}_{voice_name.lower()}.wav"
            save_wav(wav_data, filename)
            print(f"  Saved: {filename}")

            if args.play:
                print(f"  Playing...")
                play_wav(wav_data)
                print(f"  Done.")

    print(f"\nAll previews saved to {args.output_dir}/")
    print("Listen and pick the best voice for each persona.")


if __name__ == "__main__":
    main()
