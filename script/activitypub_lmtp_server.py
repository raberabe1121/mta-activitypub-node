#!/usr/bin/env python3
import asyncio, sys, subprocess, logging
from aiosmtpd.controller import Controller
from aiosmtpd.handlers import AsyncMessage
from aiosmtpd.lmtp import LMTP
from email.message import EmailMessage

LOG_PATH = "/var/log/activitypub-lmtp.log"
HOST = "127.0.0.1"
PORT = 2626
HANDLER_CMD = [sys.executable, "/usr/local/bin/activitypub-lmtp.py"]  # RFC822 を stdin で渡す

# File + console logging (goes to journalctl)
logger = logging.getLogger("activitypub-lmtp")
logger.setLevel(logging.INFO)
fmt = logging.Formatter('[%(asctime)s] %(message)s')
fh = logging.FileHandler(LOG_PATH)
fh.setFormatter(fmt); fh.setLevel(logging.INFO)
ch = logging.StreamHandler(sys.stderr)
ch.setFormatter(fmt); ch.setLevel(logging.INFO)
logger.addHandler(fh); logger.addHandler(ch)

class PipeToHandler(AsyncMessage):
    async def handle_message(self, message: EmailMessage):
        data = message.as_bytes()
        logger.info(f"LMTP received From:{message.get('From')} To:{message.get_all('To')}")
        try:
            p = subprocess.Popen(HANDLER_CMD, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate(input=data, timeout=60)
            if out:
                for line in out.decode(errors="ignore").splitlines():
                    logger.info(line)
            if err:
                for line in err.decode(errors="ignore").splitlines():
                    logger.error(line)
            logger.info(f"handler exit={p.returncode}")
        except Exception as e:
            logger.exception(f"handler error: {e}")

# For older aiosmtpd: override factory() to create LMTP server
class LMTPController(Controller):
    def factory(self):
        return LMTP(self.handler, enable_SMTPUTF8=True, decode_data=False, ident="activitypub")

async def main():
    handler = PipeToHandler()
    try:
        controller = LMTPController(handler, hostname=HOST, port=PORT, server_hostname="activitypub", decode_data=False)
        controller.start()
        logger.info(f"listening on {HOST}:{PORT}")
    except Exception as e:
        logger.exception(f"controller.start failed: {e}")
        await asyncio.sleep(5)
        raise
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        controller.stop()

if __name__ == "__main__":
    try:
        logger.info("service starting…")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("service stopping (KeyboardInterrupt)")
    except Exception as e:
        logger.exception(f"fatal: {e}")
        raise
