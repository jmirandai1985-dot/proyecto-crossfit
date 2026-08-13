"""
Configuración de logging con sanitización de PII y rotación local.

Filtra emails, RUTs y teléfonos de todos los mensajes de log para
poder archivar los logs de forma segura (Ley de protección de datos).
Los logs locales rotan automáticamente (5MB por archivo, máx. 5 respaldos).
"""
import logging
import os
import re
from logging.handlers import RotatingFileHandler


class PIISanitizer(logging.Filter):
    """Sanitiza PII de los logs (emails, RUTs, teléfonos)."""

    # Patrones a ocultar
    EMAIL_PATTERN = r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
    RUT_PATTERN = r"\b\d{1,2}\.\d{3}\.\d{3}-[\dkK]\b|\b\d{7,8}-[\dkK]\b"
    PHONE_PATTERN = r"(?<!\d)\+?56\s?9\d{8}(?!\d)|\b9\d{8}\b"

    def filter(self, record: logging.LogRecord) -> bool:
        # getMessage() ya combina msg + args; luego se resetean los args
        msg = self._sanitize(str(record.getMessage()))
        record.msg = msg
        record.args = ()
        return True

    def _sanitize(self, text: str) -> str:
        text = re.sub(self.EMAIL_PATTERN, "[EMAIL]", text)
        text = re.sub(self.RUT_PATTERN, "[RUT]", text)
        text = re.sub(self.PHONE_PATTERN, "[PHONE]", text)
        return text


def setup_logger(
    name: str = "urban_training_box",
    max_bytes: int = 5 * 1024 * 1024,  # 5 MB
    backup_count: int = 5,             # app.log + app.log.1 ... app.log.5
) -> logging.Logger:
    """Crea/retorna el logger principal con sanitización PII y rotación local.

    - Escribe en backend/logs/app.log (gitignored) con rotación automática
    - Sanitiza PII en TODOS los logs (se agrega el filtro al root logger)
    """
    # Sanitizar también los logs de uvicorn (destinatarios de email, etc.)
    root = logging.getLogger()
    if not any(isinstance(f, PIISanitizer) for f in root.filters):
        root.addFilter(PIISanitizer())

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    log_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "logs",
    )
    os.makedirs(log_dir, exist_ok=True)

    handler = RotatingFileHandler(
        os.path.join(log_dir, "app.log"),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    handler.addFilter(PIISanitizer())

    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Capturar también los logs de uvicorn en el mismo archivo (sanitizados)
    if not any(
        getattr(h, "baseFilename", None) == os.path.join(log_dir, "app.log")
        for h in root.handlers
    ):
        root.addHandler(handler)

    return logger
