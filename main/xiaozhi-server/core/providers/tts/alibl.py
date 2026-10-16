import os
import uuid
import asyncio
from datetime import datetime
from dashscope import SpeechSynthesizer
from core.providers.tts.base import TTSProviderBase


class TTSProvider(TTSProviderBase):
    """阿里云百炼 TTS，整段合成（DashScope SDK，sambert/cosyvoice，复用百炼 API key）。

    与 alibl_stream.py（百炼 WebSocket 流式）相对，适合低延迟要求不高的场景。
    """

    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        import dashscope
        key = config.get("api_key")
        if key:
            dashscope.api_key = key
        self.model = config.get("model", "sambert-zhichu-v1")
        self.voice = config.get("voice", "zhichu")
        self.audio_file_type = config.get("format", "mp3")

    def generate_filename(self, extension=".mp3"):
        return os.path.join(
            self.output_file,
            f"tts-{datetime.now().date()}@{uuid.uuid4().hex}{extension}",
        )

    async def text_to_speak(self, text, output_file):
        # SpeechSynthesizer.call 是同步阻塞调用，放到线程里避免卡住事件循环
        audio, code, message = await asyncio.to_thread(self._synthesize, text)
        if code or not audio:
            raise RuntimeError(f"DashScope TTS {code}: {message}")
        if output_file:
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, "wb") as f:
                f.write(audio)
        return audio

    def _synthesize(self, text):
        result = SpeechSynthesizer.call(
            model=self.model, text=text, voice=self.voice, format=self.audio_file_type
        )
        resp = result.get_response()
        return (
            result.get_audio_data(),
            getattr(resp, "code", None),
            getattr(resp, "message", ""),
        )
