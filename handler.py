import os
import io
import json
import base64
import tempfile
import torch
import requests
import soundfile as sf
import numpy as np

try:
    import runpod
except Exception:
    runpod = None

# === CONFIG ===
MODEL_REPO = os.getenv("MODEL_REPO", "snakers4/silero-models")
MODEL_NAME = os.getenv("MODEL_NAME", "silero_tts")
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "ru")
DEFAULT_SPEAKER = os.getenv("DEFAULT_SPEAKER", "aidar")
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "48000"))

# RunPod Storage config (optional)
# Provide RUNPOD_STORAGE_UPLOAD_URL and RUNPOD_STORAGE_API_KEY as environment variables
RUNPOD_STORAGE_UPLOAD_URL = os.getenv("RUNPOD_STORAGE_UPLOAD_URL")
RUNPOD_STORAGE_API_KEY = os.getenv("RUNPOD_STORAGE_API_KEY")

custom_speakers = {}

def upload_to_runpod_storage(file_path: str, dest_key: str) -> str:
    """Upload file to RunPod Storage via a user-provided upload URL.
    The runtime expects RUNPOD_STORAGE_UPLOAD_URL to be a base URL where files can be PUT
    with the destination key appended, and RUNPOD_STORAGE_API_KEY as an authorization header.
    If these are not provided, this function returns None.
    """
    if not RUNPOD_STORAGE_UPLOAD_URL:
        return None
    # Construct upload URL
    upload_url = RUNPOD_STORAGE_UPLOAD_URL.rstrip('/') + '/' + dest_key.lstrip('/')
    headers = {}
    if RUNPOD_STORAGE_API_KEY:
        headers['Authorization'] = f'Bearer {RUNPOD_STORAGE_API_KEY}'
    # Do PUT
    with open(file_path, 'rb') as f:
        resp = requests.put(upload_url, data=f, headers=headers, timeout=60)
    resp.raise_for_status()
    # Return the public URL (assume upload_url is public)
    return upload_url

def download_file(url: str, dest: str):
    r = requests.get(url, stream=True, timeout=30)
    r.raise_for_status()
    with open(dest, 'wb') as f:
        for chunk in r.iter_content(1024 * 32):
            f.write(chunk)

def load_silero_model(language=DEFAULT_LANGUAGE, speaker=DEFAULT_SPEAKER):
    model, example_text, languages, speakers = torch.hub.load(
        repo_or_dir=MODEL_REPO,
        model=MODEL_NAME,
        language=language,
        speaker=speaker
    )
    return model

print('Loading Silero TTS model... (may take a while on first start)')
MODEL = None
try:
    MODEL = load_silero_model()
    print('Model loaded')
except Exception as e:
    print('Failed to load model:', e)

def ensure_model():
    global MODEL
    if MODEL is None:
        MODEL = load_silero_model()
    return MODEL

def save_audio_to_wav_bytes(audio, sr):
    # audio can be torch.Tensor or numpy array
    if hasattr(audio, 'cpu'):
        audio_np = audio.cpu().numpy()
    else:
        audio_np = np.asarray(audio)
    buf = io.BytesIO()
    sf.write(buf, audio_np, sr, format='WAV')
    buf.seek(0)
    return buf

def generate_audio(text, speaker=DEFAULT_SPEAKER, sample_rate=SAMPLE_RATE, speaker_embedding_path=None):
    model = ensure_model()
    if speaker_embedding_path:
        emb = torch.load(speaker_embedding_path, map_location='cpu')
        if isinstance(emb, dict):
            # try to extract first tensor
            for v in emb.values():
                if hasattr(v, 'cpu'):
                    emb = v
                    break
        audio = model.apply_tts(text=text, speaker=emb, sample_rate=sample_rate)
    else:
        audio = model.apply_tts(text=text, speaker=speaker, sample_rate=sample_rate)
    return audio

def handler(event):
    """RunPod Serverless handler entrypoint.

    Expected `event` structure:
    {
      "input": {
        "text": "Hello",
        "speaker": "aidar",               # optional
        "sample_rate": 48000,              # optional
        "speaker_embedding_url": "https://.../my_emb.pth"  # optional
      }
    }
    """
    try:
        payload = event.get('input') if isinstance(event, dict) else (json.loads(event) if isinstance(event, str) else {})
    except Exception:
        payload = {}

    text = payload.get('text')
    if not text:
        return {'error': 'input.text is required'}

    speaker = payload.get('speaker', DEFAULT_SPEAKER)
    sample_rate = int(payload.get('sample_rate', SAMPLE_RATE))
    speaker_embedding_url = payload.get('speaker_embedding_url')

    speaker_embedding_path = None
    if speaker_embedding_url:
        tmpf = tempfile.NamedTemporaryFile(delete=False, suffix='.pth')
        try:
            download_file(speaker_embedding_url, tmpf.name)
            speaker_embedding_path = tmpf.name
        except Exception as e:
            return {'error': f'failed to download speaker embedding: {e}'}

    try:
        audio = generate_audio(text=text, speaker=speaker, sample_rate=sample_rate,
                              speaker_embedding_path=speaker_embedding_path)
    except Exception as e:
        return {'error': f'failed to generate audio: {e}'}

    wav_buf = save_audio_to_wav_bytes(audio, sample_rate)
    b64 = base64.b64encode(wav_buf.read()).decode('utf-8')

    # Save locally to /tmp and optionally upload to RunPod Storage
    out_dir = '/tmp/silero_outputs'
    os.makedirs(out_dir, exist_ok=True)
    safe_name = speaker.replace(' ', '_')
    out_path = os.path.join(out_dir, f'{safe_name}.wav')
    with open(out_path, 'wb') as f:
        f.write(base64.b64decode(b64))

    storage_url = None
    # If RUNPOD_STORAGE_UPLOAD_URL is configured, upload and return public URL
    if RUNPOD_STORAGE_UPLOAD_URL:
        dest_key = f'tts_outputs/{safe_name}_{os.path.basename(out_path)}'
        try:
            storage_url = upload_to_runpod_storage(out_path, dest_key)
        except Exception as e:
            # don't fail the whole response if upload fails
            storage_url = None

    response = {
        'speaker': speaker,
        'sample_rate': sample_rate,
        'audio_base64': b64,
        'saved_wav_path': out_path,
        'storage_url': storage_url
    }

    # clean up downloaded embedding file
    if speaker_embedding_path and os.path.exists(speaker_embedding_path):
        try:
            os.remove(speaker_embedding_path)
        except Exception:
            pass

    return response

if runpod:
    # When running inside RunPod serverless runtime, start the handler loop
    try:
        runpod.serverless.start({'handler': handler})
    except Exception as e:
        print('runpod.serverless.start failed:', e)

if __name__ == '__main__':
    # local test
    test_event = {'input': {'text': 'Привет! Тест Silero TTS.'}}
    print(handler(test_event))
