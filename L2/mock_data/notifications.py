"""Simulated notification outbox. Replace send_notification with email/chat integration later."""

sent_notifications = []


def send_notification(employee_id, message):
    sent_notifications.append({"to": employee_id, "message": message})
    print(f"  [notify] {employee_id}: {message}")


def clear_notifications():
    sent_notifications.clear()
