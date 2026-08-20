from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    DATABASE_SCHEMA: str = "ctts"

    # JWT - MUST match the value hsk-tutor's backend used to sign existing
    # ctts tokens (settings.SECRET_KEY there), or every already-signed-in
    # user gets logged out on cutover. Carry the same value over, don't
    # generate a fresh one.
    SECRET_KEY: str
    ALGORITHM: str = "HS256"

    # Tencent Cloud (TTS + ASR)
    TENCENT_SECRET_ID: str = ""
    TENCENT_SECRET_KEY: str = ""
    TENCENT_REGION: str = "ap-singapore"

    # iFLYTEK (TTS primary, see services/tts_resilient.py)
    IFLYTEK_APPID: str = ""
    IFLYTEK_API_KEY: str = ""
    IFLYTEK_API_SECRET: str = ""

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    CTTS_FRONTEND_URL: str = "https://uranbekanarbaev.dev"
    API_URL: str = "https://api-chinese-tts.hsk-tutor.com"

    CORS_ORIGINS: str = "*"

    # Amplitude analytics
    AMPLITUDE_API_KEY: str = ""

    # Alibaba OSS (audio cache) - read directly via os.environ in
    # services/audio_cache.py, listed here only for documentation.
    ALIBABA_ACCESS_KEY_ID: str = ""
    ALIBABA_ACCESS_KEY_SECRET: str = ""
    ALIBABA_OSS_ENDPOINT: str = "oss-ap-southeast-1.aliyuncs.com"
    ALIBABA_BUCKET_NAME: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
