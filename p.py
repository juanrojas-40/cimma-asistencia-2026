import gspread
from google.oauth2.service_account import Credentials
import json

# Cargar credenciales desde archivo local (solo para prueba)
with open("credentials.json") as f:
    creds_dict = json.load(f)

creds = Credentials.from_service_account_info(creds_dict, scopes=[
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
])

client = gspread.authorize(creds)
sheet = client.open_by_key("1R1KosQtbzJiWc9oQj96NnSybYDevbj0rK2gvKxa1IZM").worksheet("JR_1")
print(sheet.get_all_values())