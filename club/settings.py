# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': True,
    'root': {
        'handlers': ['null'],
        'level': 'ERROR',
    },
    'handlers': {
        'null': {
            'class': 'logging.NullHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['null'],
            'propagate': False,
            'level': 'ERROR',
        },
        'django.db.backends': {
            'handlers': ['null'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.template': {
            'handlers': ['null'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.utils.autoreload': {
            'handlers': ['null'],
            'level': 'ERROR',
            'propagate': False,
        }
    }
} 