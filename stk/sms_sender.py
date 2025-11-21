import africastalking

# Initialize SDK
username = "sandbox"   # <-- If using real account, replace with your username
api_key = "YOUR_API_KEY_HERE"  # <-- Replace with your Africa's Talking API Key

africastalking.initialize(username, api_key)

sms = africastalking.SMS

def send_sms_message(phone_number, message_text):
    try:
        response = sms.send(
            message_text,
            [phone_number]
        )
        print("SMS Response:", response)
        return True
    except Exception as e:
        print("SMS Error:", e)
        return False
