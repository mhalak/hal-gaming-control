import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading
import servicemanager
import win32service
import win32serviceutil
from .agent import run

CONFIG_DIR = Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'SmartHouseGamingControl'

class GamingService(win32serviceutil.ServiceFramework):
    _svc_name_ = 'SmartHouseGamingControl'
    _svc_display_name_ = 'SmartHouse Gaming Control'
    _svc_description_ = 'Windows game telemetry and explicit Home Assistant MQTT actions.'

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = threading.Event()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop_event.set()

    def SvcDoRun(self):
        handler = RotatingFileHandler(CONFIG_DIR / 'service.log', maxBytes=2_000_000, backupCount=2)
        logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(name)s %(message)s')
        try:
            run(CONFIG_DIR / 'config.yaml', self.stop_event)
        except Exception:
            logging.exception('Service failed')
            servicemanager.LogErrorMsg('SmartHouse Gaming Control failed; see service.log')
            raise
