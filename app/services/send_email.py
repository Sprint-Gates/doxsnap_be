from email.mime.text import MIMEText
import smtplib
import base64
import json
import os
from operations.common_operation import load_app_config

otp_time_delta_minutes = 5


def send_mail(email: str, iccid: str, smdp: str, matching_id: str):

    app_config = load_app_config()
    subject = f"eSim QR Code from {app_config['company_name']}"
    encoded_image = ""

    with open(f"{iccid}.png", "rb") as image_file:
        encoded_image = base64.b64encode(image_file.read()).decode("utf-8")

    img_qr_code = (
        f"<img src='data:image/jpeg;base64,{encoded_image}' style='width: 200px;' >"
    )

    setup_guide = f"<a href='{app_config['company_domain']}/user-guide'> {app_config['company_name']} Setup Guide</a>"

    body = (
        """
                <!DOCTYPE html>        
         <html>
             <bod style='font-size: 15px;'> 
                    
                    Dear Customer, <br><br><br>
                    Thank you for choosing """
        + app_config["company_name"]
        + """ eSIM for your connectivity needs while traveling. 
                    <br><br>
                    Below are the instructions to install your eSIM
                    <h3>eSIM Installation</h3>
                
                    <ul>
                        <li><b>Scan the QR Code:</b> Make sure your device is connected to Wi-Fi.</li>
                        <li><b>Open Your Camera App:</b> On your iPhone or Android device, launch the camera.</li>
                        <li><b>Point at the QR Code:</b> Direct your camera at the QR code provided to initiate the eSIM installation and activation process automatically.</li>
                    </ul>
                    <br>
                
                    <div style:"width: 100%; text-align: center;">
                         """
        + img_qr_code
        + """
                     </div>

                     <br>

                     <h3>If you have an Apple Device, you can install direcly by clicking on the below:</h3>
                     <br>

                     <a style=" display: inline-block; padding: 10px 20px; background-color: black; color: white; text-align: center; text-decoration: none; border-radius: 5px; font-size: 16px; cursor: pointer; transition: background-color 0.3s;" href="https://esimsetup.apple.com/esim_qrcode_provisioning?carddata=LPA:1$"""
        + smdp
        + """$"""
        + matching_id
        + """">Install Directly on Apple Device</a> 

                    <br><br><br>
                    
                    Please be aware that installing the eSIM does not activate your plan subscription. 
                    <br>
                    Your plan will automatically activate once you connect for the first time in your chosen destination country.
                    <br>
                    For more information on how to set up your eSIM, please visit """
        + setup_guide
        + """.
                    <br><br>
                    Need Assistance? Feel free to contact our support team at: """
        + app_config["company_support_email"]
        + """.

             </body>
         </html>
            """
    )

    msg = MIMEText(body, "html")
    msg["Subject"] = subject
    msg["From"] = app_config["company_noreply_email"]
    msg["To"] = email

    server = smtplib.SMTP("smtp.office365.com", 587)
    server.starttls()
    server.login(
        app_config["company_noreply_email"], app_config["company_noreply_password"]
    )
    text = msg.as_string()
    server.sendmail(app_config["company_noreply_email"], email, text)

    server.quit()

