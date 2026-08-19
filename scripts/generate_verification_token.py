import secrets
import string

alphabet = string.ascii_letters + string.digits + "_-"
token = "".join(secrets.choice(alphabet) for _ in range(48))
print(token)
