"""
Firebase Cloud Messaging Push Notification Service

Sends push notifications to mobile devices for:
- Work order assignments
- Stock transfer notifications
"""
import logging
from typing import Optional, Dict
from app.config import settings

logger = logging.getLogger(__name__)

# Firebase Admin SDK - lazy loaded
_firebase_app = None


def _initialize_firebase():
    """Initialize Firebase Admin SDK (lazy loading)"""
    global _firebase_app

    if _firebase_app is not None:
        return True

    if not settings.firebase_service_account_path:
        logger.warning("Firebase service account path not configured. Push notifications disabled.")
        return False

    try:
        import firebase_admin
        from firebase_admin import credentials

        cred = credentials.Certificate(settings.firebase_service_account_path)
        _firebase_app = firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize Firebase Admin SDK: {e}")
        return False


class PushNotificationService:
    """Service for sending FCM push notifications"""

    @staticmethod
    def send_notification(
        fcm_token: str,
        title: str,
        body: str,
        data: Optional[Dict[str, str]] = None,
        notification_type: str = "general"
    ) -> bool:
        """
        Send push notification to a single device.

        Args:
            fcm_token: Device FCM token
            title: Notification title
            body: Notification body text
            data: Additional data payload (must be Dict[str, str])
            notification_type: Type identifier for client-side handling

        Returns:
            True if sent successfully, False otherwise
        """
        if not fcm_token:
            logger.debug("No FCM token provided, skipping notification")
            return False

        if not _initialize_firebase():
            return False

        try:
            from firebase_admin import messaging

            # Prepare data payload
            payload_data = data.copy() if data else {}
            payload_data["notification_type"] = notification_type
            payload_data["click_action"] = "FLUTTER_NOTIFICATION_CLICK"

            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                data=payload_data,
                token=fcm_token,
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        icon="ic_notification",
                        color="#1a56db",
                        sound="default",
                        channel_id="coresrp_notifications"
                    )
                ),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            alert=messaging.ApsAlert(
                                title=title,
                                body=body
                            ),
                            sound="default",
                            badge=1
                        )
                    )
                )
            )

            response = messaging.send(message)
            logger.info(f"Push notification sent successfully: {response}")
            return True

        except Exception as e:
            error_str = str(e)
            if "Requested entity was not found" in error_str or "not a valid FCM registration token" in error_str:
                logger.warning(f"FCM token is invalid/unregistered: {fcm_token[:20]}...")
            else:
                logger.error(f"Failed to send push notification: {e}")
            return False

    @staticmethod
    def send_work_order_assignment_notification(
        fcm_token: str,
        wo_number: str,
        wo_title: str,
        priority: str = "medium"
    ) -> bool:
        """
        Send notification when work order is assigned to HHD.

        Args:
            fcm_token: Device FCM token
            wo_number: Work order number (e.g., "WO-2026-00001")
            wo_title: Work order title/description
            priority: Work order priority (low, medium, high, critical)

        Returns:
            True if sent successfully, False otherwise
        """
        return PushNotificationService.send_notification(
            fcm_token=fcm_token,
            title="New Work Order Assigned",
            body=f"{wo_number}: {wo_title}",
            data={
                "wo_number": wo_number,
                "priority": priority,
            },
            notification_type="work_order_assignment"
        )

    @staticmethod
    def send_transfer_notification(
        fcm_token: str,
        transfer_number: str,
        item_count: int,
        from_warehouse: str
    ) -> bool:
        """
        Send notification when stock transfer is created for HHD.

        Args:
            fcm_token: Device FCM token
            transfer_number: Transfer number (e.g., "TRF-2026-00001")
            item_count: Number of items in the transfer
            from_warehouse: Source warehouse name

        Returns:
            True if sent successfully, False otherwise
        """
        return PushNotificationService.send_notification(
            fcm_token=fcm_token,
            title="New Stock Transfer",
            body=f"{transfer_number}: {item_count} item(s) from {from_warehouse}",
            data={
                "transfer_number": transfer_number,
                "item_count": str(item_count),
                "from_warehouse": from_warehouse,
            },
            notification_type="stock_transfer"
        )
