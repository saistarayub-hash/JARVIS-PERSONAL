"""Push bridges: Telegram + email (v9).

Real sends when credentials are configured (config.yaml or env vars
JARVIS_TELEGRAM_TOKEN / JARVIS_TELEGRAM_CHAT); otherwise every message lands
in an honest outbox labelled simulated — it never pretends something left
the machine when it didn't.

Routing modes (push.mode in config):
  alerts  — only red-alert announcements get pushed (default)
  all     — every announcement gets pushed
  off     — push only on explicit "send X to telegram/mail" commands
"""
from __future__ import annotations

import logging
import os
import smtplib
import time
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

log = logging.getLogger("jarvis.push")


class PushBridge:
    def __init__(self, cfg: Optional[dict], memory=None, demo: bool = False):
        cfg = cfg or {}
        tg = cfg.get("telegram") or {}
        self.tg_token = str(tg.get("bot_token") or
                            os.environ.get("JARVIS_TELEGRAM_TOKEN") or "").strip()
        self.tg_chat = str(tg.get("chat_id") or
                           os.environ.get("JARVIS_TELEGRAM_CHAT") or "").strip()
        ml = cfg.get("mail") or {}
        self.mail_host = str(ml.get("smtp_host") or "").strip()
        self.mail_port = int(ml.get("smtp_port") or 587)
        self.mail_user = str(ml.get("username") or "").strip()
        self.mail_pass = str(ml.get("password") or "")
        self.mail_from = str(ml.get("mail_from") or self.mail_user).strip()
        self.mail_to = str(ml.get("mail_to") or "").strip()
        self.mode = str(cfg.get("mode") or "alerts").lower()
        self.memory = memory
        self.demo = demo

    # ------------------------------------------------------------ capability
    def status(self) -> Dict[str, Any]:
        return {"mode": self.mode,
                "telegram": bool(self.tg_token and self.tg_chat),
                "mail": bool(self.mail_host and self.mail_to),
                "demo": self.demo}

    def configured_channels(self) -> List[str]:
        chans: List[str] = []
        if self.tg_token and self.tg_chat:
            chans.append("telegram")
        if self.mail_host and self.mail_to:
            chans.append("mail")
        return chans

    # ------------------------------------------------------------ sending
    def send(self, text: str,
             channels: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Explicit send to named channels (default: every configured one,
        or an honest simulated outbox entry when nothing is configured)."""
        chans = channels or self.configured_channels() or ["telegram"]
        return [self._send_one(c, text) for c in chans]

    def route(self, text: str, alert: bool = False) -> List[Dict[str, Any]]:
        """Automatic routing from the announce channel, respecting mode.
        Returns [] when nothing was pushed (that's normal, not an error)."""
        if self.mode == "off" or not self.configured_channels():
            return []
        if self.mode == "alerts" and not alert:
            return []
        return self.send(text, self.configured_channels())

    def _send_one(self, channel: str, text: str) -> Dict[str, Any]:
        if channel == "telegram":
            if not (self.tg_token and self.tg_chat):
                return self._log("telegram", text,
                                 "no credentials — kept in outbox, not sent",
                                 True)
            try:
                import requests
                r = requests.post(
                    f"https://api.telegram.org/bot{self.tg_token}/sendMessage",
                    json={"chat_id": self.tg_chat, "text": text[:4000]},
                    timeout=8)
                if r.status_code == 200 and (r.json() or {}).get("ok"):
                    return self._log("telegram", text, "sent", False)
                return self._log("telegram", text,
                                 f"failed: HTTP {r.status_code}", False)
            except Exception as exc:  # noqa: BLE001 — honest failure status
                return self._log("telegram", text,
                                 f"failed: {exc.__class__.__name__}", False)
        if channel == "mail":
            if not (self.mail_host and self.mail_to):
                return self._log("mail", text,
                                 "no credentials — kept in outbox, not sent",
                                 True)
            try:
                msg = MIMEText(text[:8000])
                msg["Subject"] = text.splitlines()[0][:70]
                msg["From"] = self.mail_from or "jarvis@localhost"
                msg["To"] = self.mail_to
                with smtplib.SMTP(self.mail_host, self.mail_port,
                                  timeout=10) as srv:
                    if self.mail_port == 587:
                        srv.starttls()
                    if self.mail_user:
                        srv.login(self.mail_user, self.mail_pass)
                    srv.sendmail(msg["From"], [self.mail_to], msg.as_string())
                return self._log("mail", text, "sent", False)
            except Exception as exc:  # noqa: BLE001
                return self._log("mail", text,
                                 f"failed: {exc.__class__.__name__}", False)
        return self._log(channel or "?", text, "unknown channel", True)

    def _log(self, channel: str, text: str, status: str,
             simulated: bool) -> Dict[str, Any]:
        entry = {"channel": channel, "text": text, "status": status,
                 "simulated": simulated, "ts": time.time()}
        if self.memory is not None:
            try:
                self.memory.push_log(channel, text, status, simulated)
            except Exception:  # noqa: BLE001 — outbox logging must never crash
                pass
        log.info("push [%s] %s — %s", channel, status, text[:60])
        return entry
