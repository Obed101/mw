import logging
import requests
from flask import current_app
from ..utils.phone_utils import normalize_ghana_phone

logger = logging.getLogger(__name__)

ARKESEL_SMS_URL = "https://sms.arkesel.com/api/v2/sms/send"

def send_sms(phone_number: str, message: str) -> tuple[bool, str]:
    """
    Sends an SMS message using the Arkesel SMS API.
    
    Args:
        phone_number: Phone number string (will be normalized to 233XXXXXXXXX format)
        message: SMS message text
        
    Returns:
        (success: bool, message: str)
    """
    normalized_phone = normalize_ghana_phone(phone_number)
    if not normalized_phone:
        return False, "Invalid phone number format. Must be a valid Ghanaian phone number."

    api_key = current_app.config.get("ARKESEL_API_KEY")
    sender_id = current_app.config.get("ARKESEL_SENDER_ID", "MarketWindow")

    if not api_key:
        logger.warning(
            "[Arkesel SMS] ARKESEL_API_KEY is not configured. SMS dispatch simulated for recipient: %s",
            normalized_phone[-4:]
        )
        return True, "SMS simulated (API key not configured)"

    headers = {
        "api-key": api_key,
        "Content-Type": "application/json"
    }

    payload = {
        "sender": sender_id,
        "message": message,
        "recipients": [normalized_phone]
    }

    try:
        response = requests.post(ARKESEL_SMS_URL, json=payload, headers=headers, timeout=10)
        
        if response.status_code in (200, 201):
            res_data = response.json() if response.content else {}
            # Arkesel returns status "success" in response JSON
            if res_data.get("status") == "success" or res_data.get("code") == "100":
                logger.info("[Arkesel SMS] SMS successfully dispatched to ***%s", normalized_phone[-4:])
                return True, "SMS sent successfully"
            else:
                msg = res_data.get("message", "SMS provider returned unsuccessful status")
                logger.error("[Arkesel SMS] Provider response error: %s", msg)
                return False, f"SMS dispatch failed: {msg}"
        else:
            logger.error("[Arkesel SMS] HTTP status error: %d", response.status_code)
            return False, f"SMS provider error (Status code: {response.status_code})"

    except requests.exceptions.Timeout:
        logger.error("[Arkesel SMS] Request timed out for recipient ending in ***%s", normalized_phone[-4:])
        return False, "SMS gateway timed out. Please try again."
    except requests.exceptions.RequestException as e:
        logger.error("[Arkesel SMS] Network exception occurred: %s", str(e))
        return False, "Failed to connect to SMS gateway. Please try again later."


def send_phone_otp_sms(phone_number: str, otp_code: str) -> tuple[bool, str]:
    """
    Helper function to send a standard Market Window OTP via SMS.
    """
    message = f"Your Market Window verification code is {otp_code}. Valid for 10 minutes. Do not share this code."
    return send_sms(phone_number, message)
