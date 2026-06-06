from __future__ import annotations

import base64
import hmac
import json
import unittest
from datetime import datetime
from hashlib import sha256
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import httpx

from backend.app import notifier


class DingtalkNotifierTests(unittest.TestCase):
    def test_disabled_alerts_do_not_record_unused_channel(self) -> None:
        run = {"id": 42, "status": "failed"}
        transition = {"current_status": "failed", "previous_status": "ok"}
        settings = {
            "alerts_enabled": False,
            "notification_channels": [
                {
                    "id": "ding",
                    "name": "值班钉钉",
                    "type": "dingtalk",
                    "enabled": True,
                    "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=token",
                }
            ],
        }

        with patch.object(notifier.storage, "get_settings", return_value=settings), patch.object(
            notifier.storage, "update_run_notification"
        ) as update_run_notification:
            self.run_async(notifier.maybe_notify({"id": 1, "type": "api", "name": "接口"}, run, transition))

        update_run_notification.assert_called_once_with(42, "disabled", channel=None, error=None, sent_at=None)

    def test_not_required_alerts_do_not_record_unused_channel(self) -> None:
        run = {"id": 43, "status": "skipped"}
        transition = {"current_status": "skipped", "previous_status": "ok"}
        settings = {
            "alerts_enabled": True,
            "notification_channels": [
                {
                    "id": "ding",
                    "name": "值班钉钉",
                    "type": "dingtalk",
                    "enabled": True,
                    "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=token",
                }
            ],
        }

        with patch.object(notifier.storage, "get_settings", return_value=settings), patch.object(
            notifier.storage, "update_run_notification"
        ) as update_run_notification:
            self.run_async(notifier.maybe_notify({"id": 1, "type": "api", "name": "接口"}, run, transition))

        update_run_notification.assert_called_once_with(43, "not_required", channel=None, error=None, sent_at=None)

    def test_maybe_notify_sends_to_all_enabled_configured_channels(self) -> None:
        run = {"id": 44, "status": "failed", "started_at": "2026-06-05T10:00:00+08:00"}
        transition = {"current_status": "failed", "previous_status": "ok", "consecutive_failures": 1}
        settings = {
            "alerts_enabled": True,
            "alert_cooldown_minutes": 30,
            "alert_detail_base_url": "http://10.168.78.49:8787",
            "recovery_notification": True,
            "notification_channels": [
                {
                    "id": "feishu",
                    "name": "飞书群",
                    "type": "feishu",
                    "enabled": True,
                    "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/token",
                },
                {
                    "id": "ding",
                    "name": "钉钉群",
                    "type": "dingtalk",
                    "enabled": True,
                    "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=token",
                    "dingtalk_secret": "SECabc123",
                },
                {
                    "id": "disabled",
                    "name": "停用渠道",
                    "type": "wecom",
                    "enabled": False,
                    "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=token",
                },
            ],
        }

        with patch.object(notifier.storage, "get_settings", return_value=settings), patch.object(
            notifier, "send_webhook_alert", new_callable=AsyncMock
        ) as send_webhook_alert, patch.object(notifier.storage, "now_iso", return_value="2026-06-05T10:00:01+08:00"), patch.object(
            notifier.storage, "update_run_notification"
        ) as update_run_notification, patch.object(notifier.storage, "update_last_notified") as update_last_notified:
            self.run_async(notifier.maybe_notify({"id": 11, "type": "api", "name": "接口"}, run, transition))

        self.assertEqual(send_webhook_alert.await_count, 2)
        sent_channel_ids = [call.args[0]["id"] for call in send_webhook_alert.await_args_list]
        self.assertEqual(sent_channel_ids, ["feishu", "ding"])
        sent_messages = [call.args[2] for call in send_webhook_alert.await_args_list]
        self.assertTrue(
            all("http://10.168.78.49:8787/runs/44?from=%2Fruns%3Fcheck_id%3D11" in message for message in sent_messages)
        )
        update_run_notification.assert_called_once_with(
            44,
            "sent",
            channel="飞书群、钉钉群",
            error=None,
            sent_at="2026-06-05T10:00:01+08:00",
        )
        update_last_notified.assert_called_once_with(11, "2026-06-05T10:00:01+08:00")

    def test_manual_failure_bypasses_continuous_failure_cooldown(self) -> None:
        run = {"id": 45, "status": "failed", "started_at": "2026-06-05T10:05:00+08:00"}
        transition = {
            "current_status": "failed",
            "previous_status": "failed",
            "last_notified_at": "2026-06-05T10:00:00+08:00",
            "consecutive_failures": 3,
            "trigger": "manual",
        }
        settings = {
            "alerts_enabled": True,
            "alert_cooldown_minutes": 30,
            "alert_detail_base_url": "http://10.168.78.49:8787",
            "notification_channels": [
                {
                    "id": "ding",
                    "name": "值班群",
                    "type": "dingtalk",
                    "enabled": True,
                    "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=token",
                }
            ],
        }

        with patch.object(notifier.storage, "get_settings", return_value=settings), patch.object(
            notifier, "send_webhook_alert", new_callable=AsyncMock
        ) as send_webhook_alert, patch.object(notifier.storage, "now_iso", return_value="2026-06-05T10:05:01+08:00"), patch.object(
            notifier.storage, "update_run_notification"
        ) as update_run_notification, patch.object(notifier.storage, "update_last_notified") as update_last_notified:
            self.run_async(notifier.maybe_notify({"id": 11, "type": "ui", "name": "商品详情"}, run, transition))

        send_webhook_alert.assert_awaited_once()
        self.assertIn("http://10.168.78.49:8787/runs/45?from=%2Fruns%3Fcheck_id%3D11", send_webhook_alert.await_args.args[2])
        update_run_notification.assert_called_once_with(
            45,
            "sent",
            channel="值班群",
            error=None,
            sent_at="2026-06-05T10:05:01+08:00",
        )
        update_last_notified.assert_called_once_with(11, "2026-06-05T10:05:01+08:00")

    def test_scheduled_continuous_failure_records_cooldown_suppression_reason(self) -> None:
        run = {"id": 46, "status": "failed", "started_at": datetime.now().astimezone().isoformat(timespec="seconds")}
        last_notified_at = datetime.now().astimezone().isoformat(timespec="seconds")
        transition = {
            "current_status": "failed",
            "previous_status": "failed",
            "last_notified_at": last_notified_at,
            "consecutive_failures": 4,
            "trigger": "scheduled",
        }
        settings = {
            "alerts_enabled": True,
            "alert_cooldown_minutes": 30,
            "notification_channels": [
                {
                    "id": "ding",
                    "name": "值班群",
                    "type": "dingtalk",
                    "enabled": True,
                    "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=token",
                }
            ],
        }

        with patch.object(notifier.storage, "get_settings", return_value=settings), patch.object(
            notifier, "send_webhook_alert", new_callable=AsyncMock
        ) as send_webhook_alert, patch.object(notifier.storage, "update_run_notification") as update_run_notification, patch.object(
            notifier.storage, "update_last_notified"
        ) as update_last_notified:
            self.run_async(notifier.maybe_notify({"id": 11, "type": "ui", "name": "商品详情"}, run, transition))

        send_webhook_alert.assert_not_awaited()
        update_last_notified.assert_not_called()
        update_run_notification.assert_called_once()
        self.assertEqual(update_run_notification.call_args.args[:2], (46, "suppressed"))
        self.assertIn("冷却窗口", update_run_notification.call_args.kwargs["error"])

    def test_dingtalk_request_url_adds_expected_signature_without_preserving_stale_values(self) -> None:
        settings = {"dingtalk_secret": "SECabc123"}
        webhook_url = "https://oapi.dingtalk.com/robot/send?access_token=token-value&timestamp=old&sign=old"

        with patch.object(notifier.time, "time", return_value=1710000000.123):
            request_url = notifier._request_url("dingtalk", webhook_url, settings)

        parts = urlsplit(request_url)
        query = parse_qs(parts.query)
        expected_timestamp = "1710000000123"
        expected_sign = base64.b64encode(
            hmac.new(
                settings["dingtalk_secret"].encode("utf-8"),
                f"{expected_timestamp}\n{settings['dingtalk_secret']}".encode("utf-8"),
                digestmod=sha256,
            ).digest()
        ).decode("utf-8")

        self.assertEqual(parts.scheme, "https")
        self.assertEqual(parts.netloc, "oapi.dingtalk.com")
        self.assertEqual(parts.path, "/robot/send")
        self.assertEqual(query["access_token"], ["token-value"])
        self.assertEqual(query["timestamp"], [expected_timestamp])
        self.assertEqual(query["sign"], [expected_sign])

    def test_dingtalk_request_url_without_secret_keeps_url_unchanged(self) -> None:
        webhook_url = "https://oapi.dingtalk.com/robot/send?access_token=token-value"

        request_url = notifier._request_url("dingtalk", webhook_url, {"dingtalk_secret": ""})

        self.assertEqual(request_url, webhook_url)

    def test_alert_preview_reports_channels_and_never_leaks_secret_material(self) -> None:
        token = "abc123SECRET456"
        secret = "SECabcdef1234567890SECRET"
        preview = notifier.build_test_alert_preview(
            {
                "notification_channels": [
                    {
                        "id": "ding",
                        "name": "钉钉群",
                        "type": "dingtalk",
                        "enabled": True,
                        "webhook_url": f"https://oapi.dingtalk.com/robot/send?access_token={token}",
                        "dingtalk_secret": secret,
                    }
                ]
            }
        )

        encoded_preview = json.dumps(preview, ensure_ascii=False)
        channel = preview["channels"][0]

        self.assertEqual(channel["type"], "dingtalk")
        self.assertEqual(channel["name"], "钉钉群")
        self.assertTrue(channel["signing_enabled"])
        self.assertEqual(channel["payload"]["msgtype"], "markdown")
        self.assertEqual(channel["payload"]["markdown"]["title"], "PulseGuard 测试告警")
        self.assertEqual(channel["target"]["origin"], "https://oapi.dingtalk.com")
        self.assertEqual(channel["target"]["path"], "/robot/send")
        self.assertEqual(channel["target"]["query_keys"], ["access_token", "timestamp", "sign"])
        self.assertNotIn(token, encoded_preview)
        self.assertNotIn(secret, encoded_preview)

    def test_dingtalk_robot_error_uses_errcode_and_errmsg(self) -> None:
        response = httpx.Response(200, json={"errcode": 310000, "errmsg": "sign not match"})

        error = notifier._robot_error("dingtalk", response)

        self.assertEqual(error, "钉钉返回 310000：sign not match")

    def test_robot_error_accepts_string_error_codes(self) -> None:
        response = httpx.Response(200, json={"errcode": "310000", "errmsg": "sign not match"})

        error = notifier._robot_error("dingtalk", response)

        self.assertEqual(error, "钉钉返回 310000：sign not match")

    def test_robot_error_reports_non_numeric_error_codes_without_crashing(self) -> None:
        response = httpx.Response(200, json={"errcode": "invalid", "errmsg": "bad response"})

        error = notifier._robot_error("dingtalk", response)

        self.assertEqual(error, "钉钉返回 invalid：bad response")

    def test_robot_error_treats_string_zero_as_success(self) -> None:
        response = httpx.Response(200, json={"errcode": "0", "errmsg": "ok"})

        error = notifier._robot_error("wecom", response)

        self.assertIsNone(error)

    def test_feishu_robot_error_uses_status_code_fallback(self) -> None:
        response = httpx.Response(200, json={"code": None, "StatusCode": 999, "StatusMessage": "token expired"})

        error = notifier._robot_error("feishu", response)

        self.assertEqual(error, "飞书返回 999：token expired")

    @staticmethod
    def run_async(awaitable):
        import asyncio

        return asyncio.run(awaitable)


if __name__ == "__main__":
    unittest.main()
