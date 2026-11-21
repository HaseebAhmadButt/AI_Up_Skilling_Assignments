"""Simulated notification outbox. Replace send_notification with email/chat integration later."""

sent_notifications = []
_notification_keys = {}


def send_notification(employee_id, message, idempotency_key=None):
    if idempotency_key and idempotency_key in _notification_keys:
        return _notification_keys[idempotency_key]
    notification = {"notification_id": f"NTF-{len(sent_notifications) + 1:05d}",
                    "to": employee_id, "message": message, "status": "queued"}
    if idempotency_key:
        notification["idempotency_key"] = idempotency_key
        _notification_keys[idempotency_key] = notification
    sent_notifications.append(notification)
    print(f"  [notify] {employee_id}: {message}")
    return notification


def mark_notification_delivered(notification_id):
    """Mark a queued fixture notification delivered only when an adapter confirms delivery."""
    notification = next((item for item in sent_notifications if item["notification_id"] == notification_id), None)
    if notification is None:
        return {"success": False, "error": "Unknown notification."}
    notification["status"] = "delivered"
    return {"success": True, "notification_id": notification_id, "status": "delivered"}


def clear_notifications():
    sent_notifications.clear()
    _notification_keys.clear()
