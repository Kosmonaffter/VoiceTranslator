import logging

# Создать и настроить логгер
logger = logging.getLogger("voice_translator")
logger.setLevel(logging.DEBUG)  # уровень логирования

# Удалить старые обработчики, если есть
if logger.hasHandlers():
    logger.handlers.clear()

# Создать консольный обработчик с форматом
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)

# Добавляем обработчик в логгер
logger.addHandler(console_handler)

# Тестовое сообщение, должно выводиться в консоль
logger.debug("Понеслась))")
