# silero-runpod-serverless

Шаблон для развёртывания Silero TTS на RunPod Serverless.

## Возможности
- Поддержка стандартных и кастомных голосов Silero (через speaker_embedding_url).
- Загрузка WAV в RunPod Storage (по конфигурируемому upload URL).
- GitHub Actions для автоматической сборки и публикации Docker-образа `seomozg/silero-runpod-serverless:latest`.

## Настройка RunPod Storage
RunPod Storage не имеет одного стандартного публичного API для загрузки — поэтому шаблон использует
универсальный подход: укажи переменные окружения при деплое на RunPod:

- `RUNPOD_STORAGE_UPLOAD_URL` — базовый URL для загрузки, например `https://storage.runpod.io/upload/<your-bucket>`
  (точный формат зависит от твоей конфигурации RunPod Storage / S3-совместимого endpoint).
- `RUNPOD_STORAGE_API_KEY` — (опционально) API ключ для авторизации.

Шаблон сделает HTTP PUT к `RUNPOD_STORAGE_UPLOAD_URL + '/tts_outputs/<file.wav>'` с файлом в теле
и передаст `Authorization: Bearer <RUNPOD_STORAGE_API_KEY>` если ключ указан.

Если у тебя S3-совместимый endpoint — укажи его здесь и путь, либо используй внешнюю службу хранения (S3, Backblaze и т.д.).

## Переменные окружения (RunPod Endpoint settings)
- `MODEL_REPO` — репозиторий для torch.hub (по умолчанию `snakers4/silero-models`)
- `MODEL_NAME` — имя модели (по умолчанию `silero_tts`)
- `DEFAULT_LANGUAGE` — язык при загрузке (по умолчанию `ru`)
- `DEFAULT_SPEAKER` — голос по умолчанию (по умолчанию `aidar`)
- `SAMPLE_RATE` — частота дискретизации (по умолчанию `48000`)
- `RUNPOD_STORAGE_UPLOAD_URL` — (опционально) базовый URL для PUT загрузки
- `RUNPOD_STORAGE_API_KEY` — (опционально) ключ для авторизации при загрузке

## Деплой
1. Форкни / зааплоди этот репозиторий в GitHub под пользователем `seomozg`.
2. Настрой GitHub Secrets:
   - `DOCKERHUB_USERNAME` — имя в Docker Hub
   - `DOCKERHUB_TOKEN` — токен доступа
3. После пуша в `main` GitHub Actions соберёт и опубликует образ `seomozg/silero-runpod-serverless:latest`.
4. На RunPod Console → Serverless → Create Endpoint укажи:
   - Docker Image: `seomozg/silero-runpod-serverless:latest`
   - Укажи необходимые Environment Variables (например, `RUNPOD_STORAGE_UPLOAD_URL`)
   - Разверни endpoint (CPU или GPU)

## Пример запроса
```bash
curl https://api.runpod.ai/v2/<endpoint-id>/run \
  -H "Content-Type: application/json" \
  -d '{
        "input": {
          "text": "Привет, я Silero!",
          "speaker": "aidar",
          "speaker_embedding_url": "https://example.com/custom_speaker.pth"
        }
      }'
```

Ответ содержит `audio_base64` и, если настроена загрузка, `storage_url`.
