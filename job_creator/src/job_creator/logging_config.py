LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"fmt": {"format": "[%(asctime)s] [%(levelname)s] %(msg)s"}},
    "handlers": {
        "sh": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "fmt",
        },
        "fh": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "fmt",
            "filename": "job_creator.log",
        },
    },
    "loggers": {
        "job_creator": {
            "level": "DEBUG",
            "handlers": ["sh", "fh"]
        }
    }
}
