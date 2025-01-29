import os
import certifi
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext
import pymongo
from pymongo.server_api import ServerApi
from pymongo.mongo_client import MongoClient
from dotenv import load_dotenv
import requests
import json

load_dotenv()

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

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

# Gemini API details
GEMINI_API_KEY = os.getenv('API_KEY')
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

# Telegram bot token
TELEGRAM_TOKEN = os.getenv('BOT_TOKEN')

# Function to call Gemini API
def call_gemini_api(prompt):
    headers = {
        'Content-Type': 'application/json'
    }
    data = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    try:
        response = requests.post(GEMINI_API_URL, headers=headers, data=json.dumps(data))
        response.raise_for_status()  # Raise an error for bad status codes
        result = response.json()
        return result['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        return "I apologize, but I encountered an error processing your request. Please try again in a moment."

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
    try:
        user_input = update.message.text
        chat_id = update.message.chat_id

        # Get Gemini response
        bot_response = call_gemini_api(user_input)

        # Save chat history
        chat_data = {
            "chat_id": chat_id,
            "user_input": user_input,
            "bot_response": bot_response,
            "timestamp": update.message.date
        }
        chats_collection.insert_one(chat_data)

        await update.message.reply_text(bot_response)
    except Exception as e:
        error_message = "I apologize, but I encountered an error processing your request. Please try again in a moment."
        logger.error(f"Error in handle_message: {e}")
        await update.message.reply_text(error_message)

async def handle_image(update: Update, context: CallbackContext):
    file = await update.message.photo[-1].get_file()
    file_path = f"downloads/{file.file_id}.jpg"
    await file.download_to_drive(file_path)

    # Analyze image with Gemini
    prompt = f"Describe the content of this image: {file_path}"
    description = call_gemini_api(prompt)

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