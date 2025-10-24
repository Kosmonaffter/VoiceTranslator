import numpy as np
import sounddevice as sd
import time
from logger_setup import logger
from utils import dev_to_str_dict, test_microphone_sensitivity

# Глобальные переменные для калибровки
calibrated_amplification = 3.0
calibrated_silence_threshold = 0.01


def calibrate_microphone(device_index, sample_rate, calibration_time=3.0):
    """Улучшенная калибровка микрофона."""
    global calibrated_amplification, calibrated_silence_threshold

    logger.info("Начинаем калибровку микрофона...")

    try:
        # Записываем фоновый шум
        logger.info("Записываем фоновый шум...")
        noise_recording = sd.rec(
            int(calibration_time * sample_rate),
            samplerate=sample_rate,
            channels=1,
            device=device_index,
            dtype='float32'
        )
        sd.wait()

        if noise_recording.size > 0:
            noise_rms = np.sqrt(np.mean(noise_recording**2))
            logger.info(f"Уровень фонового шума: {noise_rms:.6f}")

            # Более агрессивный порог для лучшего распознавания
            # Увеличили множитель
            calibrated_silence_threshold = max(0.01, noise_rms * 5)
            logger.info(
                f"Установлен порог тишины: {calibrated_silence_threshold:.6f}"
            )

        # Тестируем уровни усиления с голосом
        logger.info("Произнесите тестовую фразу для калибровки...")
        time.sleep(1)  # Даем время подготовиться

        test_amplifications = [1.0, 2.0, 3.0, 4.0]
        best_amplification = 2.0
        best_level = 0.0

        for amp in test_amplifications:
            logger.info(f"Тестируем усиление {amp}...")
            time.sleep(1)  # Пауза для произнесения фразы

            test_recording = sd.rec(
                int(2.0 * sample_rate),  # Увеличили время записи
                samplerate=sample_rate,
                channels=1,
                device=device_index,
                dtype='float32'
            )
            sd.wait()

            if test_recording.size > 0:
                amplified = test_recording * amp
                level = np.sqrt(np.mean(amplified**2))

                logger.info(f"Уровень при усилении {amp}: {level:.6f}")

                # Ищем оптимальное усиление (более строгие критерии)
                if 0.05 < level < 0.7 and level > best_level:
                    best_level = level
                    best_amplification = amp

        calibrated_amplification = best_amplification
        logger.info(f"Оптимальное усиление: {calibrated_amplification:.1f}")

        return calibrated_amplification, calibrated_silence_threshold

    except Exception as e:
        logger.error(f"Ошибка калибровки: {e}")
        return 3.0, 0.01


def get_calibrated_amplification():
    """Возвращает калиброванное значение усиления."""
    return calibrated_amplification


def get_calibrated_silence_threshold():
    """Возвращает калиброванный порог тишины."""
    return calibrated_silence_threshold


def test_microphone(device_index, sample_rate, duration=0.5):
    """Тестирует микрофон с заданными параметрами."""
    try:
        device_index = int(device_index)
        sample_rate = int(sample_rate)

        with sd.InputStream(
            device=device_index,
            channels=1,
            samplerate=sample_rate,
            blocksize=1024,
            dtype='int16'
        ):
            sd.sleep(int(duration * 1000))
        return True
    except Exception as e:
        logger.debug(
            f"Тест микрофона {device_index} на {sample_rate}Hz не удался: {e}"
        )
        return False


def is_wdm_ks_device(device_name):
    """Проверяет, является ли устройство WDM-KS."""
    if not device_name:
        return False
    name_lower = device_name.lower()
    return any(
        keyword in name_lower
        for keyword in ['wdm-ks', 'ks', 'kernel streaming']
    )


def auto_select_microphone(preferred_sample_rate=16000):
    """Улучшенный выбор микрофона с обходом WDM-KS устройств."""
    try:
        devices = sd.query_devices()
        working_devices = []

        logger.info("Поиск рабочих микрофонов...")

        for i, dev in enumerate(devices):
            try:
                dev_dict = dev_to_str_dict(dev)
                max_input_channels = int(dev_dict.get("max_input_channels", 0))

                if max_input_channels <= 0:
                    continue

                name = dev_dict.get("name", "Unknown")
                default_rate = int(dev_dict.get("default_samplerate", 44100))

                if is_wdm_ks_device(name):
                    logger.debug(
                        f"Пропущено WDM-KS устройство: {name} (индекс {i})"
                    )
                    continue

                test_rates = [16000, 44100, 48000, 22050, 8000]

                for test_rate in test_rates:
                    if test_microphone(i, test_rate, 0.3):
                        sensitivity_score = test_microphone_sensitivity(
                            i,
                            test_rate,
                            0.5
                        )

                        working_devices.append({
                            'index': i,
                            'name': name,
                            'sample_rate': test_rate,
                            'sensitivity': sensitivity_score,
                            'default_rate': default_rate
                        })

                        logger.info(
                            f"Найдено рабочее устройство: {name} "
                            f"(индекс {i}, {test_rate}Hz, "
                            f"чувствительность: {sensitivity_score:.4f})"
                        )
                        break

            except Exception:
                logger.debug(f"Ошибка тестирования устройства {i}")
                continue

        working_devices.sort(key=lambda x: x['sensitivity'], reverse=True)

        if working_devices:
            best_device = working_devices[0]
            logger.info(
                f"ВЫБРАНО УСТРОЙСТВО: {best_device['name']} "
                f"(индекс {best_device['index']}, "
                f"{best_device['sample_rate']}Hz, "
                f"чувствительность: {best_device['sensitivity']:.4f})"
            )

            # Выполняем калибровку выбранного устройства
            calibrate_microphone(
                best_device['index'], best_device['sample_rate']
            )

            return best_device['index'], best_device['sample_rate']

        logger.warning(
            "Не найдено обычных устройств, пробуем любые доступные..."
        )
        for i, dev in enumerate(devices):
            try:
                dev_dict = dev_to_str_dict(dev)
                max_input_channels = int(dev_dict.get("max_input_channels", 0))

                if max_input_channels <= 0:
                    continue

                name = dev_dict.get("name", "Unknown")
                default_rate = int(dev_dict.get("default_samplerate", 44100))

                if test_microphone(i, default_rate, 0.2):
                    logger.info(
                        f"Выбрано устройство как последний вариант: {name} "
                        f"(индекс {i}, {default_rate}Hz)"
                    )

                    calibrate_microphone(i, default_rate)
                    return i, default_rate

            except Exception:
                continue

        logger.warning("Пробуем устройство 1 с 16000Hz как последний вариант")
        if test_microphone(1, 16000, 0.2):
            calibrate_microphone(1, 16000)
            return 1, 16000

        logger.error(
            "Не найдено рабочих микрофонов, используется устройство 0"
        )
        calibrate_microphone(0, 44100)
        return 0, 44100

    except Exception as e:
        logger.error(f"Критическая ошибка выбора микрофона: {e}")
        return 1, 16000
