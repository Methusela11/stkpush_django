from django.shortcuts import render, redirect
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import base64
import requests
import json
from .models import MpesaPayment
from django.http import HttpResponse
from .sms_sender import send_sms_message

def message_page(request):
    return render(request, "message.html")

import requests
from django.shortcuts import render

TERMI_API_KEY = "TLSptHuXCudyZzoZOdOqJhAAwBsqOvBVreYrleSTTkyLpAmNnUUTUfJksZetQI"  # Use live API key only
TERMI_SENDER_ID = "Termii"     # or 'Termii' if not approved yet

TERMI_URL = "https://api.ng.termii.com/api/sms/send"

def send_sms(request):
    context = {}

    if request.method == "POST":
        phone = request.POST.get("phone")

        # Format Kenyan number to +2547XXXXXXX
        if phone.startswith("0"):
            phone = "+254" + phone[1:]
        elif phone.startswith("254"):
            phone = "+" + phone
        elif not phone.startswith("+254"):
            context["error"] = "Phone must be Kenyan format."
            return render(request, "message.html", context)

        payload = {
            "api_key": TERMI_API_KEY,
            "to": phone,
            "from": TERMI_SENDER_ID,
            "sms": "Your confirmation has reached.",
            "type": "plain",
            "channel": "generic"
        }

        try:
            response = requests.post(TERMI_URL, json=payload)
            data = response.json()

            if data.get("code") == "ok":
                context["message"] = f"SMS sent successfully to {phone}"
            else:
                context["error"] = f"Failed: {data}"

        except Exception as e:
            context["error"] = f"Error sending SMS: {str(e)}"

    return render(request, "message.html", context)



def home(request):
    return render(request, 'index.html')


# -----------------------------
# Generate MPesa Access Token
# -----------------------------
def get_access_token():
    consumer_key = settings.MPESA_CONSUMER_KEY
    consumer_secret = settings.MPESA_CONSUMER_SECRET

    auth_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"

    response = requests.get(auth_url, auth=(consumer_key, consumer_secret))
    json_response = response.json()
    return json_response['access_token']


# -----------------------------------------
# Convert phone number to MPesa format
# -----------------------------------------
def format_phone_number(phone):
    phone = phone.replace(" ", "").replace("+", "")

    if phone.startswith("07") or phone.startswith("01"):
        return "254" + phone[1:]

    if phone.startswith("7") or phone.startswith("1"):
        return "254" + phone

    return None   # invalid number


# -----------------------------------------
# Process Payment (STK Push)
# -----------------------------------------
def process_payment(request):

    if request.method == "POST":
        phone = request.POST.get("phone")
        amount = 1  # Change to dynamic amount if needed

        formatted_phone = format_phone_number(phone)

        # Generate STK details (same as before)
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        raw_pass = settings.MPESA_SHORTCODE + settings.MPESA_PASSKEY + timestamp
        password = base64.b64encode(raw_pass.encode()).decode()
        access_token = get_access_token()

        stk_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        stk_request = {
            "BusinessShortCode": settings.MPESA_SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": formatted_phone,
            "PartyB": settings.MPESA_SHORTCODE,
            "PhoneNumber": formatted_phone,
            "CallBackURL": settings.MPESA_CALLBACK_URL,
            "AccountReference": "METHUSELA ENOCH",
            "TransactionDesc": "Payment Request"
        }

        response = requests.post(stk_url, json=stk_request, headers=headers)
        data = response.json()

        # Save initial payment record
        payment = MpesaPayment.objects.create(
            phone=formatted_phone,
            amount=amount,
            status="Pending",
            checkout_request_id=data.get("CheckoutRequestID"),
            merchant_request_id=data.get("MerchantRequestID")
        )

        return JsonResponse({
            "message": "STK Push sent",
            "payment_id": payment.id,
            "response": data
        })


# -----------------------------------------
# Callback URL
# -----------------------------------------
@csrf_exempt
@csrf_exempt
def mpesa_callback(request):
    callback = request.body.decode('utf-8')
    data = json.loads(callback)

    try:
        stk_callback = data["Body"]["stkCallback"]
        merchant_id = stk_callback["MerchantRequestID"]
        checkout_id = stk_callback["CheckoutRequestID"]

        # Find the payment record
        payment = MpesaPayment.objects.filter(
            checkout_request_id=checkout_id,
            merchant_request_id=merchant_id
        ).first()

        if payment:
            payment.raw_callback = callback  # Save raw data for debugging

            if stk_callback["ResultCode"] == 0:
                # Successful payment
                metadata = stk_callback["CallbackMetadata"]["Item"]

                # Extract values
                for item in metadata:
                    if item["Name"] == "MpesaReceiptNumber":
                        payment.mpesa_receipt = item["Value"]
                    if item["Name"] == "TransactionDate":
                        # Convert YYYYMMDDHHMMSS to datetime
                        from datetime import datetime
                        payment.transaction_date = datetime.strptime(str(item["Value"]), "%Y%m%d%H%M%S")
                    if item["Name"] == "Amount":
                        payment.amount = item["Value"]

                payment.status = "Completed"

            else:
                payment.status = "Failed"

            payment.save()

    except Exception as e:
        print("Callback Error:", e)

    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})


