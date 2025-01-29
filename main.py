import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext
from google.generativeai import configure, GenerativeModel
import pymongo
from pymongo.server_api import ServerApi
from pymongo.mongo_client import MongoClient
from dotenv import load_dotenv
import requests

load_dotenv()
# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB setup
# MongoDB setup
try:
    client = pymongo.MongoClient(
        "mongodb+srv://aryan:nowornever098@cluster0.1l2sc.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0",
        serverSelectionTimeoutMS=50000,
        tls=True,
        tlsAllowInvalidCertificates=True
    )
    # Test the connection
    client.admin.command('ping')
    print("Connected to MongoDB successfully.")
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")

db = client["telegram_bot"]
users_collection = db["users"]
chats_collection = db["chats"]
files_collection = db["files"]


# Gemini setup
configure(api_key=os.getenv('API_KEY'))
gemini_model = GenerativeModel('gemini-pro')

# Telegram bot token
TELEGRAM_TOKEN = os.getenv('BOT_TOKEN')

async def start(update: Update, context: CallbackContext):
    user = update.message.from_user
    user_data = {
        "first_name": user.first_name,
        "username": user.username,
        "chat_id": user.id,
        "phone_number": None
    }
    users_collection.update_one({"chat_id": user.id}, {"$set": user_data}, upsert=True)
    await update.message.reply_text("Welcome! Please share your phone number using the contact button.")

async def handle_contact(update: Update, context: CallbackContext):
    user = update.message.from_user
    phone_number = update.message.contact.phone_number
    users_collection.update_one({"chat_id": user.id}, {"$set": {"phone_number": phone_number}})
    await update.message.reply_text(f"Thank you! Your phone number {phone_number} has been saved.")

async def handle_message(update: Update, context: CallbackContext):
    user_input = update.message.text
    chat_id = update.message.chat_id

    # Get Gemini response
    response = gemini_model.generate_content(user_input)
    bot_response = response.text

    # Save chat history
    chat_data = {
        "chat_id": chat_id,
        "user_input": user_input,
        "bot_response": bot_response,
        "timestamp": update.message.date
    }
    chats_collection.insert_one(chat_data)

    await update.message.reply_text(bot_response)

async def handle_image(update: Update, context: CallbackContext):
    file = await update.message.photo[-1].get_file()
    file_path = f"downloads/{file.file_id}.jpg"
    await file.download_to_drive(file_path)

    # Analyze image with Gemini
    response = gemini_model.generate_content(f"Describe the content of this image: {file_path}")
    description = response.text

    # Save file metadata
    file_data = {
        "chat_id": update.message.chat_id,
        "filename": file_path,
        "description": description,
        "timestamp": update.message.date
    }
    files_collection.insert_one(file_data)

    await update.message.reply_text(f"Image analysis: {description}")

async def web_search(update: Update, context: CallbackContext):
    query = " ".join(context.args)
    search_url = f"https://api.duckduckgo.com/?q={query}&format=json"
    response = requests.get(search_url)
    data = response.json()

    summary = data.get('AbstractText', 'No summary available.')
    links = [result['FirstURL'] for result in data.get('RelatedTopics', [])[:3]]

    reply_text = f"Summary: {summary}\n\nTop Links:\n" + "\n".join(links)
    await update.message.reply_text(reply_text)

def main():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(CommandHandler("websearch", web_search))

    application.run_polling()

if __name__ == '__main__':
    main()