import json
import keyboard
import os
import sys
import tkinter as tk
import threading
import time
from tkinter import ttk, colorchooser

from audio_utils import (
    get_calibrated_amplification,
    get_calibrated_silence_threshold
)
from logger_setup import logger
from translation import Translator, set_amplification_factor


def resource_path(relative_path):
    """Получить абсолютный путь к ресурсу, работает в dev и с PyInstaller"""
    try:
        base_path = sys._MEIPASS  # type: ignore
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def get_model_path(rel_path):
    return resource_path(rel_path)


# Конфигурационный файл для сохранения настроек
CONFIG_FILE = "app_config.json"


def load_config():
    """Загружает конфигурацию из файла."""
    default_config = {
        "bg_color": "#FFC0CB",  # розовый по умолчанию
        "window_alpha": 0.9,
        "input_lang": "ru",
        "output_lang": "en",
        "amplification": 2.0
    }

    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки конфигурации: {e}")

    return default_config


# Загружаем конфигурацию
config = load_config()

models_paths = {
    "en": get_model_path("model_en/vosk-model-small-en-us-0.15"),
    "fr": get_model_path("model_fr/vosk-model-small-fr-0.22"),
    "ru": get_model_path("model_ru/vosk-model-small-ru-0.22"),
    "zh": get_model_path("model_zh/vosk-model-small-cn-0.22"),
}
recording_thread = None


root = tk.Tk()
root.title("Голосовой переводчик с настройкой цвета")

# Загружаем иконки с учётом упаковки в exe
ico_icon_path = resource_path("icons/Ico_transl.ico")

play_icon = tk.PhotoImage(file=resource_path("icons/PLAY.png"))
root.iconphoto(True, play_icon)


root.geometry("600x600")
root.configure(bg=config["bg_color"])
root.attributes("-alpha", config["window_alpha"])

languages = ["ru", "fr", "zh", "en"]

input_lang_var = tk.StringVar(value=config["input_lang"])
output_lang_var = tk.StringVar(value=config["output_lang"])
sensitivity_var = tk.DoubleVar(value=config["amplification"])

input_text = tk.StringVar()
output_text = tk.StringVar()

# Фрейм для настроек цвета
color_frame = tk.Frame(root, bg=config["bg_color"])
color_frame.pack(pady=10, fill="x", padx=10)


def choose_bg_color():
    """Открывает диалог выбора цвета фона."""
    color = colorchooser.askcolor(
        title="Выберите цвет фона окна",
        initialcolor=config["bg_color"]
    )

    if color[1]:  # Если цвет выбран (не None)
        config["bg_color"] = color[1]
        root.configure(bg=config["bg_color"])

        # Обновляем все виджеты
        update_all_widgets_color(config["bg_color"])

        # Сохраняем настройки
        # save_config(config)
        logger.info(f"Цвет фона изменен на: {config['bg_color']}")


def choose_alpha(value):
    """Изменяет прозрачность окна."""
    config["window_alpha"] = float(value)
    root.attributes("-alpha", config["window_alpha"])
    # save_config(config)
    logger.info(f"Прозрачность изменена на: {config['window_alpha']}")


def update_all_widgets_color(bg_color):
    """Обновляет цвет фона всех виджетов, включая шкалы."""
    widgets_to_update = [
        color_frame, settings_frame, lang_frame, translation_frame,
        alpha_frame, status_canvas
    ]

    for widget in widgets_to_update:
        if widget:
            try:
                widget.configure(bg=bg_color)
            except Exception as e:
                logger.debug(f"Ошибка обновления цвета виджета: {e}")

    # Обновляем все дочерние виджеты
    for widget in root.winfo_children():
        update_widget_color(widget, bg_color)


def update_widget_color(widget, bg_color):
    """Рекурсивно обновляет цвет виджета и его детей."""
    try:
        if isinstance(widget, (tk.Label, tk.Button, tk.Frame, tk.Canvas)):
            widget.configure(bg=bg_color)

        # Особые случаи для шкал
        if isinstance(widget, tk.Scale):
            widget.configure(bg=bg_color, troughcolor=bg_color)

        # Рекурсивно обходим детей
        if hasattr(widget, 'winfo_children'):
            for child in widget.winfo_children():
                update_widget_color(child, bg_color)
    except Exception as e:
        logger.debug(f"Ошибка обновления цвета: {e}")


# Кнопка выбора цвета
color_btn = tk.Button(
    color_frame,
    text="🎨 Выбрать цвет фона",
    command=choose_bg_color,
    bg="white",
    font=("Arial", 10)
)
color_btn.pack(side=tk.LEFT, padx=5)

# Слайдер прозрачности
alpha_frame = tk.Frame(color_frame, bg=config["bg_color"])
alpha_frame.pack(side=tk.LEFT, padx=20)

tk.Label(
    alpha_frame,
    text="Прозрачность:",
    bg=config["bg_color"]
).pack(side=tk.LEFT)


alpha_scale = tk.Scale(
    alpha_frame,
    from_=0.3,
    to=1.0,
    resolution=0.1,
    orient=tk.HORIZONTAL,
    bg=config["bg_color"],
    fg="black",
    troughcolor=config["bg_color"],
    length=120,
    command=choose_alpha,
)
alpha_scale.set(config["window_alpha"])
alpha_scale.pack(side=tk.LEFT, padx=5)


# Кнопка сброса к стандартным настройкам
def reset_settings():
    """Сбрасывает настройки к значениям по умолчанию."""
    config.update({
        "bg_color": "#FFC0CB",
        "window_alpha": 0.9,
        "input_lang": "ru",
        "output_lang": "fr",
        "amplification": 2.0
    })

    # Применяем настройки
    root.configure(bg=config["bg_color"])
    root.attributes("-alpha", config["window_alpha"])
    input_lang_var.set(config["input_lang"])
    output_lang_var.set(config["output_lang"])
    sensitivity_var.set(config["amplification"])
    alpha_scale.set(config["window_alpha"])

    # Обновляем все виджеты
    update_all_widgets_color(config["bg_color"])

    #  save_config(config)
    logger.info("Настройки сброшены к значениям по умолчанию")


reset_btn = tk.Button(
    color_frame,
    text="🔄 Сброс",
    command=reset_settings,
    bg="white",
    font=("Arial", 10)
)
reset_btn.pack(side=tk.RIGHT, padx=5)

progress_bar = ttk.Progressbar(root, mode="indeterminate")
progress_bar.pack(pady=10, fill="x", padx=10)

status_canvas = tk.Canvas(root, width=20, height=20, bg=config["bg_color"])
status_canvas.pack(pady=10)
status_oval = status_canvas.create_oval(2, 2, 18, 18, fill="green")

translator = Translator(models_paths)

tts_busy = threading.Event()
recording_active = threading.Event()
recording_lock = threading.Lock()
last_spoken_text = ""
last_spoken_time = 0

manual_stop_requested = threading.Event()

# Фрейм для настроек микрофона
settings_frame = tk.Frame(root, bg=config["bg_color"])
settings_frame.pack(pady=5, fill="x", padx=10)

tk.Label(
    settings_frame,
    text="Усиление микрофона:",
    bg=config["bg_color"]
).pack(side=tk.LEFT)

sensitivity_scale = tk.Scale(
    settings_frame,
    from_=1.0,
    to=5.0,
    resolution=0.1,
    orient=tk.HORIZONTAL,
    variable=sensitivity_var,
    bg=config["bg_color"],  # Используем общий цвет
    fg="black",
    troughcolor=config["bg_color"],
    length=200,
    command=set_amplification_factor,
)


def translate_text_from_input_field():
    text = input_text_widget.get("1.0", "end-1c").strip()
    if not text:
        logger.info("Поле ввода пустое")
        return
    try:
        translated = translator.translate_text(
            text, input_lang_var.get(), output_lang_var.get()
        )
        output_text.set(translated)
        translator.last_translation = translated
        speak_and_notify(translated, output_lang_var.get())
    except Exception as exc:
        logger.error(f"Ошибка перевода текста: {exc}", exc_info=True)


def set_status_color(color):
    status_canvas.itemconfig(status_oval, fill=color)


def on_tts_finish():
    tts_busy.clear()
    root.after(0, lambda: set_status_color("green"))


def speak_and_notify(text, lang):
    global last_spoken_text, last_spoken_time

    current_time = time.time()
    if text == last_spoken_text and (current_time - last_spoken_time) < 5:
        logger.debug("Пропускаем озвучку - тот же текст был недавно")
        return

    last_spoken_text = text
    last_spoken_time = current_time

    tts_busy.set()
    translator.speak(text, lang, finish_callback=on_tts_finish)


def play_last_translation():
    if translator.last_translation:
        speak_and_notify(translator.last_translation, output_lang_var.get())
    else:
        logger.info("Нет перевода для воспроизведения")


def safe_release_lock(lock):
    try:
        if lock.locked():
            lock.release()
            logger.debug("Блокировка освобождена")
    except Exception as e:
        logger.error(f"Ошибка при освобождении блокировки: {e}")


def start_recording():
    global recording_thread

    if tts_busy.is_set() or recording_active.is_set():
        logger.info("Занято или запись уже идет, старт пропущен")
        return

    if recording_thread and recording_thread.is_alive():
        logger.info("Поток записи уже активен, старт пропущен")
        return

    acquired = recording_lock.acquire(blocking=False)
    if not acquired:
        logger.info("Запись занята, старт отклонен")
        return

    logger.info("Старт записи")
    try:
        recording_active.set()
        manual_stop_requested.clear()
        root.after(0, progress_bar.start)
        root.after(0, lambda: set_status_color("red"))
        root.after(0, lambda: input_text.set("Говорите..."))

        recording_thread = threading.Thread(
            target=record_and_process,
            daemon=True
        )
        recording_thread.start()

    except Exception as e:
        logger.error(f"Ошибка при старте записи: {e}")
        recording_active.clear()
        safe_release_lock(recording_lock)


def stop_recording():
    global recording_thread

    if not recording_active.is_set():
        logger.info("Стоп записи: запись не активна")
        return

    logger.info("Запрос ручной остановки записи")
    manual_stop_requested.set()


def record_and_process():
    global recording_thread

    try:
        translator.set_language(input_lang_var.get())

        text = translator.recognize(
            manual_stop_callback=lambda: manual_stop_requested.is_set()
        )

        def update_input_text_widget(t):
            input_text_widget.delete("1.0", "end")
            input_text_widget.insert("1.0", t)

        root.after(0, lambda: update_input_text_widget(text))

        if text.strip():
            translated = translator.translate_text(
                text, input_lang_var.get(), output_lang_var.get()
            )
            root.after(0, lambda: output_text.set(translated))
            speak_and_notify(translated, output_lang_var.get())
        else:
            logger.info("Пустой результат распознавания, пропускаем перевод")

    except Exception as exc:
        logger.error(f"Error in record_and_process: {exc}", exc_info=True)
        err_msg = "Ошибка распознавания"
        root.after(0, lambda: input_text_widget.delete("1.0", "end"))
        root.after(0, lambda: input_text_widget.insert("1.0", err_msg))
    finally:
        root.after(0, progress_bar.stop)
        root.after(0, lambda: set_status_color("green"))
        recording_active.clear()
        manual_stop_requested.clear()
        safe_release_lock(recording_lock)
        recording_thread = None


def on_language_change(*args):
    """Сохраняет настройки языков при изменении."""
    config["input_lang"] = input_lang_var.get()
    config["output_lang"] = output_lang_var.get()
    # save_config(config)


# Привязываем обработчики изменений
input_lang_var.trace("w", on_language_change)
output_lang_var.trace("w", on_language_change)

btn_hold = tk.Button(
    root,
    text="Нажмите и говорите (отпустите для остановки)",
    bg=config["bg_color"],
    font=("Arial", 12),
)
btn_hold.pack(pady=15)
btn_hold.bind("<ButtonPress>", lambda e: start_recording())
btn_hold.bind("<ButtonRelease>", lambda e: stop_recording())


def hotkey_press():
    root.after(0, start_recording)


def hotkey_release():
    root.after(0, stop_recording)


keyboard.on_press_key("left alt", lambda e: hotkey_press())
keyboard.on_release_key("left alt", lambda e: hotkey_release())

# Языковые настройки
lang_frame = tk.Frame(root, bg=config["bg_color"])
lang_frame.pack(pady=10)

tk.Label(
    lang_frame,
    text="Язык распознавания:",
    bg=config["bg_color"]
).pack(side=tk.LEFT)

input_lang_menu = tk.OptionMenu(lang_frame, input_lang_var, *languages)
input_lang_menu.pack(side=tk.LEFT, padx=10)

tk.Label(
    lang_frame,
    text="Язык перевода:",
    bg=config["bg_color"]
).pack(side=tk.LEFT)

output_lang_menu = tk.OptionMenu(lang_frame, output_lang_var, *languages)
output_lang_menu.pack(side=tk.LEFT, padx=10)

tk.Label(
    root,
    text="Ввод текста или распознанная речь:",
    bg=config["bg_color"]
).pack(pady=(10, 0))

input_text_widget = tk.Text(root, height=5, width=50, font=("Arial", 10))
input_text_widget.pack(padx=10, pady=(0, 10))

translation_frame = tk.Frame(root, bg=config["bg_color"])
translation_frame.pack(fill="x", pady=(10, 0), padx=10)

play_btn = tk.Button(
    translation_frame,
    image=play_icon,
    compound=tk.LEFT,
    bg="white",
    command=play_last_translation,
    text=" Воспроизвести",
    font=("Arial", 10)
)
play_btn.pack(side=tk.LEFT)

translation_label = tk.Label(
    translation_frame,
    text="Перевод:",
    bg=config["bg_color"],
    font=("Arial", 10)
)
translation_label.pack(side=tk.LEFT, padx=(10, 0))

output_label = tk.Label(
    root,
    textvariable=output_text,
    bg=config["bg_color"],
    font=("Arial", 11),
    wraplength=550
)
output_label.pack(pady=(5, 10))

translate_btn = tk.Button(
    root,
    text="Перевести введённый текст",
    command=translate_text_from_input_field,
    bg="white",
    font=("Arial", 10)
)
translate_btn.pack(pady=(0, 15))

# Информация о калибровке
calibration_info = tk.Label(
    root,
    text=(
        f"Калибровка: усиление {get_calibrated_amplification():.1f}x, "
        f"порог {get_calibrated_silence_threshold():.4f}"
    ),
    bg=config["bg_color"],
    font=("Arial", 8)
)
calibration_info.pack(pady=5)


def on_closing():
    """Обработчик закрытия окна."""
    config["amplification"] = sensitivity_var.get()
    # save_config(config)
    root.destroy()


root.protocol("WM_DELETE_WINDOW", on_closing)

root.mainloop()
