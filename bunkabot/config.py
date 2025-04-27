import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN      : str = os.environ["BOT_TOKEN"]
PORT           : int = int(os.getenv("PORT", 8443))
WEBHOOK_SECRET : str = os.getenv("WEBHOOK_SECRET", "")
BASE_URL       : str = os.getenv("BASE_URL")

ALLOWED_USERS  : set[int] = { int(x) for x in os.getenv("ALLOWED_USERS","").split() if x }