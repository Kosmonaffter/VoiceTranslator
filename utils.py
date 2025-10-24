import numpy as np
import scipy.signal as signal
from logger_setup import logger


def dev_to_str_dict(dev):
    """Конвертирует устройство в словарь строк."""
    return {
        (k.decode("utf-8") if isinstance(k, bytes) else k):
        (v.decode("utf-8") if isinstance(v, bytes) else v)
        for k, v in dev.items()
    }


class AudioProcessor:
    def __init__(self, sample_rate):
        self.sample_rate = sample_rate

    def apply_bandpass_filter(self, audio_data, lowcut=300, highcut=3400):
        """Применяет полосовой фильтр для удаления шумов."""
        try:
            if len(audio_data) < 10:
                return audio_data

            nyquist = 0.5 * self.sample_rate
            low = lowcut / nyquist
            high = highcut / nyquist

            # Используем sos (second-order sections) формат для стабильности
            sos = signal.butter(4, [low, high], btype='band', output='sos')
            filtered_data = signal.sosfiltfilt(sos, audio_data)
            return filtered_data
        except Exception as e:
            logger.error(f"Ошибка фильтрации аудио: {e}")
            return audio_data

    def normalize_audio(self, audio_data):
        """Нормализует амплитуду аудиосигнала."""
        if len(audio_data) == 0:
            return audio_data

        max_val = np.max(np.abs(audio_data))
        if max_val > 0:
            return audio_data / max_val
        return audio_data

    def remove_dc_offset(self, audio_data):
        """Удаляет постоянное смещение."""
        if len(audio_data) == 0:
            return audio_data
        return audio_data - np.mean(audio_data)

    def preprocess_audio(self, audio_data):
        """Полная предобработка аудио."""
        if len(audio_data) == 0:
            return audio_data

        try:
            audio_array = np.frombuffer(
                audio_data,
                dtype=np.int16
            ).astype(np.float32)
            audio_array = self.remove_dc_offset(audio_array)
            audio_array = self.apply_bandpass_filter(audio_array)
            audio_array = self.normalize_audio(audio_array)
            return (audio_array * 32767).astype(np.int16).tobytes()
        except Exception as e:
            logger.error(f"Ошибка предобработки аудио: {e}")
            return audio_data


def test_microphone_sensitivity(device_index, sample_rate, duration=1.0):
    """Тестирует чувствительность микрофона."""
    try:
        import sounddevice as sd
        recording = sd.rec(
            int(duration * sample_rate),
            samplerate=sample_rate,
            channels=1,
            device=device_index,
            dtype='float32'
        )
        sd.wait()

        if recording.size > 0:
            rms = np.sqrt(np.mean(recording**2))
            return float(rms)
        return 0.0

    except Exception as e:
        logger.debug(f"Ошибка тестирования чувствительности: {e}")
        return 0.0
