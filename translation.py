import argostranslate.translate
import json
import numpy as np
import os
import pyttsx3
import queue
import sounddevice as sd
import time
import threading

from audio_utils import (
    auto_select_microphone,
    get_calibrated_amplification,
    get_calibrated_silence_threshold
)
from collections.abc import Iterable
from logger_setup import logger
from utils import AudioProcessor
from vosk import Model, KaldiRecognizer

os.environ["SD_DISABLE_ASIO"] = "1"

audio_queue = queue.Queue()
# Используем калиброванное значение
current_amplification = get_calibrated_amplification()


def audio_callback(indata, frames, time_, status):
    if status:
        logger.warning(f"Audio callback status: {status}")

    try:
        amplification_factor = current_amplification
        audio_float = indata.astype(np.float32) / 32768.0

        # Добавляем проверку на тишину перед усилением
        rms = np.sqrt(np.mean(audio_float**2))
        if rms < 0.001:  # Порог очень тихого звука
            amplified_audio = audio_float  # Не усиливаем шум
        else:
            amplified_audio = audio_float * amplification_factor

        amplified_audio = np.clip(amplified_audio, -1.0, 1.0)
        amplified_data_int16 = (amplified_audio * 32767).astype(np.int16)
        audio_queue.put(bytes(amplified_data_int16))
    except Exception as e:
        logger.error(f"Ошибка в audio_callback: {e}")
        # В случае ошибки передаем оригинальные данные
        audio_queue.put(bytes(indata))


def set_amplification_factor(factor):
    global current_amplification
    current_amplification = max(1.0, min(5.0, float(factor)))
    logger.info(f"Установлено усиление микрофона: {current_amplification:.1f}")


def speak_text(text, lang_code=None, finish_callback=None):
    def worker():
        if not text or len(text.strip()) < 2:
            logger.warning("Озвучка пропущена: короткий текст")
            if finish_callback:
                finish_callback()
            return

        engine = None
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 150)
            engine.setProperty("volume", 1.0)

            if lang_code:
                available_voices = engine.getProperty("voices")
                if isinstance(available_voices, Iterable):
                    lang_code_lower = lang_code.lower()
                    for voice in available_voices:
                        voice_langs = []
                        for lang in getattr(voice, "languages", []):
                            if isinstance(lang, bytes):
                                try:
                                    decoded = lang.decode("utf-8").lower()
                                    voice_langs.append(decoded)
                                except Exception:
                                    pass
                            else:
                                voice_langs.append(str(lang).lower())

                        if any(lang_code_lower in lang_item
                               for lang_item in voice_langs):
                            engine.setProperty("voice", voice.id)
                            logger.debug(
                                f"Выбран голос для {lang_code}: {voice.name}"
                            )
                            break

            text_to_speak = text.strip()
            logger.info(f"Озвучивание: {text_to_speak}")

            engine.say(text_to_speak)
            engine.runAndWait()
            logger.debug("Озвучка завершена")

        except Exception as e:
            logger.error(f"Ошибка озвучки: {e}")
        finally:
            try:
                if engine:
                    engine.stop()
            except Exception:
                pass
            if finish_callback:
                finish_callback()

    threading.Thread(target=worker, daemon=True).start()


class Translator:
    def __init__(self, models_paths):
        logger.info(f"Инициализация Translator: {list(models_paths.keys())}")

        self.device_index, self.sample_rate = auto_select_microphone()
        logger.info(
            f"Выбрано устройство: {self.device_index}, "
            f"частота: {self.sample_rate}Hz"
        )

        # Используем калиброванные параметры
        self.silence_threshold = get_calibrated_silence_threshold()
        logger.info(
            f"Калиброванный порог тишины: {self.silence_threshold:.6f}"
        )

        self.audio_processor = AudioProcessor(self.sample_rate)
        self.models = {}

        for lang_code, model_path in models_paths.items():
            try:
                self.models[lang_code] = Model(model_path)
                logger.info(f"Загружена модель для {lang_code}")
            except Exception as e:
                logger.error(f"Ошибка загрузки модели {lang_code}: {e}")

        self.recognizer = None
        self.selected_lang = None
        self.last_translation = ""
        self._init_translations()

    def _init_translations(self):
        self.translations = {}
        try:
            self.installed_languages = (
                argostranslate.translate.get_installed_languages()
            )
            lang_codes = ["ru", "fr", "zh", "en"]

            for src in lang_codes:
                for tgt in lang_codes:
                    if src == tgt:
                        continue

                    from_lang = next(
                        (lang for lang in self.installed_languages
                         if lang.code == src), None
                    )
                    to_lang = next(
                        (lang for lang in self.installed_languages
                         if lang.code == tgt), None
                    )

                    if from_lang and to_lang:
                        try:
                            self.translations[
                                (src, tgt)
                            ] = from_lang.get_translation(to_lang)
                            logger.debug(f"Доступен перевод: {src} -> {tgt}")
                        except Exception as e:
                            logger.warning(
                                f"Перевод {src}->{tgt} недоступен: {e}"
                            )
        except Exception as e:
            logger.error(f"Ошибка инициализации переводов: {e}")

    def set_language(self, lang_code):
        if lang_code not in self.models:
            raise ValueError(
                f"Модель распознавания для языка {lang_code} не найдена"
            )

        logger.info(f"Установка языка распознавания: {lang_code}")
        model = self.models[lang_code]
        self.recognizer = KaldiRecognizer(model, self.sample_rate)
        self.selected_lang = lang_code

    def recognize(
            self,
            max_silence_seconds=3.0,
            silence_threshold=None,
            manual_stop_callback=None,
    ):
        """Улучшенное распознавание речи."""
        if self.recognizer is None:
            raise RuntimeError("Язык распознавания не установлен")

        if silence_threshold is None:
            silence_threshold = self.silence_threshold

        last_sound_time = time.time()
        last_text = ""
        recording_start_time = time.time()

        logger.info(
            f"Начало распознавания с порогом тишины: {silence_threshold:.6f}"
        )

        try:
            # Упрощаем конфигурацию потока
            stream_configs = [
                {'blocksize': 2048, 'latency': 'low'},
                {'blocksize': 1024, 'latency': 'low'},
            ]

            stream = None
            for config in stream_configs:
                try:
                    stream = sd.InputStream(
                        samplerate=self.sample_rate,
                        blocksize=config['blocksize'],
                        dtype="int16",
                        channels=1,
                        callback=audio_callback,
                        device=self.device_index,
                        latency=config['latency']
                    )
                    stream.start()
                    logger.info(
                        f"Аудиопоток запущен: blocksize={config['blocksize']}"
                    )
                    break
                except Exception as e:
                    if stream:
                        stream.close()
                    logger.debug(f"Ошибка конфигурации {config}: {e}")
                    continue

            if stream is None:
                # Последняя попытка с базовыми настройками
                try:
                    stream = sd.InputStream(
                        samplerate=self.sample_rate,
                        dtype="int16",
                        channels=1,
                        callback=audio_callback,
                        device=self.device_index
                    )
                    stream.start()
                    logger.info(
                        "Аудиопоток запущен с настройками по умолчанию"
                    )
                except Exception as e:
                    logger.error(f"Не удалось запустить аудиопоток: {e}")
                    return ""

            logger.info("Начало записи речи...")

            while True:
                current_time = time.time()
                recording_duration = current_time - recording_start_time

                # Минимальное время записи перед проверкой тишины
                min_recording_time = 1.0
                if recording_duration < min_recording_time:
                    time.sleep(0.1)
                    continue

                if manual_stop_callback and manual_stop_callback():
                    logger.info("Ручная остановка записи")
                    break

                try:
                    data = audio_queue.get(timeout=0.5)
                except queue.Empty:
                    if manual_stop_callback and manual_stop_callback():
                        logger.info("Ручная остановка при таймауте")
                        break
                    continue

                # Анализируем громкость для обнаружения тишины
                try:
                    audio_array = np.frombuffer(data, dtype=np.int16)
                    if len(audio_array) > 0:
                        rms = np.sqrt(np.mean(audio_array**2)) / 32768.0
                        if rms >= silence_threshold:
                            last_sound_time = current_time
                except Exception as e:
                    logger.debug(f"Ошибка анализа громкости: {e}")

                # Обработка аудиоданных
                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "").strip()
                    if text:
                        last_text = text
                        last_sound_time = current_time
                        logger.info(f"Распознано: {text}")
                else:
                    partial = json.loads(self.recognizer.PartialResult())
                    partial_text = partial.get("partial", "").strip()
                    if partial_text:
                        last_text = partial_text
                        last_sound_time = current_time
                        if len(partial_text) > 2:
                            logger.debug(f"Частично: {partial_text}")

                # Проверка условий остановки
                silence_timeout = (
                    current_time - last_sound_time
                ) > max_silence_seconds
                # Макс. время записи
                recording_timeout = recording_duration > 10.0

                if silence_timeout or recording_timeout:
                    logger.info("Завершение записи по таймауту")
                    break

            stream.stop()
            stream.close()

            # Получаем финальный результат
            final_result = json.loads(self.recognizer.FinalResult())
            final_text = final_result.get("text", "").strip()

            result_text = final_text or last_text
            logger.info(f"Финальный результат: '{result_text}'")
            return result_text

        except Exception as e:
            logger.error(f"Ошибка при распознавании: {e}")
            return ""

    def translate_text(self, text, source_lang, target_lang):
        """Перевод текста между языками."""
        if not text.strip():
            return ""

        if source_lang == target_lang:
            return text

        logger.info(f"Перевод {source_lang}->{target_lang}: '{text}'")

        if target_lang == "zh":
            try:
                translation = self.translations.get((source_lang, target_lang))
                if translation:
                    translated_text = translation.translate(text)
                    if (len(translated_text.strip()) > 0 and
                            not any(c in translated_text for c in ['�', ''])):
                        self.last_translation = translated_text
                        logger.info(f"Корректный перевод: '{translated_text}'")
                        return translated_text

                if source_lang != "en":
                    trans1 = self.translations.get((source_lang, "en"))
                    trans2 = self.translations.get(("en", target_lang))
                    if trans1 and trans2:
                        english_text = trans1.translate(text)
                        translated_text = trans2.translate(english_text)
                        if len(translated_text.strip()) > 0:
                            self.last_translation = translated_text
                            logger.info(
                                f"Перевод через EN: '{translated_text}'"
                            )
                            return translated_text

                if source_lang != "en":
                    trans = self.translations.get((source_lang, "en"))
                    if trans:
                        return trans.translate(text)
                return text

            except Exception as e:
                logger.error(f"Ошибка перевода на китайский: {e}")
                return text

        translation = self.translations.get((source_lang, target_lang))
        if translation:
            try:
                translated_text = translation.translate(text)
                self.last_translation = translated_text
                logger.info(f"Результат перевода: '{translated_text}'")
                return translated_text
            except Exception as e:
                logger.error(f"Ошибка прямого перевода: {e}")

        if source_lang != "en" and target_lang != "en":
            trans1 = self.translations.get((source_lang, "en"))
            trans2 = self.translations.get(("en", target_lang))

            if trans1 and trans2:
                try:
                    english_text = trans1.translate(text)
                    translated_text = trans2.translate(english_text)
                    self.last_translation = translated_text
                    logger.info(
                        f"Перевод через английский: '{translated_text}'"
                    )
                    return translated_text
                except Exception as e:
                    logger.error(f"Ошибка перевода через английский: {e}")

        logger.warning(f"Перевод {source_lang}->{target_lang} недоступен")
        self.last_translation = text
        return text

    def speak(self, text, lang_code=None, finish_callback=None):
        """Публичный метод для озвучивания текста."""
        speak_text(text, lang_code, finish_callback)

    def stop(self):
        """Остановка всех процессов."""
        pass
