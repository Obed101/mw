import smtplib

server = smtplib.SMTP_SSL(
    "smtp.gmail.com",
    465
)

server.set_debuglevel(1)

server.login(
    "marketwindowgh@gmail.com",
    "pdbtnuweoviwbqoj"
)

print("SSL login successful")

server.quit()