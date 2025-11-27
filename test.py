import smtplib
from email.message import EmailMessage

msg = EmailMessage()
msg['Subject'] = 'Test SMTP Gmail'
msg['From'] = 'moussahassan7758@gmail.com'
msg['To'] = 'gestionbibliotheque70@gmail.com'
msg.set_content("SMTP OK !")

with smtplib.SMTP('smtp.gmail.com', 587) as server:
    server.starttls()
    server.login('gestionbibliotheque70@gmail.com', 'meou huya kclk vmab')
    server.send_message(msg)

print("Email envoyé !")
