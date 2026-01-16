import tempfile
from pathlib import Path
from openai import AsyncOpenAI


class Transcriber:
    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)

    async def transcribe(self, audio_data: bytes, filename: str = "voice.ogg") -> str:
        """
        Transcribe audio data to text using OpenAI Whisper.

        Args:
            audio_data: Raw audio bytes (OGG format from Telegram)
            filename: Filename hint for the API

        Returns:
            Transcribed text in Russian
        """
        # Write audio to temp file (OpenAI API needs a file)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(audio_data)
            temp_path = Path(f.name)

        try:
            with open(temp_path, "rb") as audio_file:
                response = await self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="ru",  # Optimize for Russian
                    response_format="text",
                )
            return response.strip()
        finally:
            temp_path.unlink(missing_ok=True)
