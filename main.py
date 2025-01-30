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
import fitz
from googlesearch import search

load_dotenv()

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB setup
try:
    client = pymongo.MongoClient(
        "mongodb+srv://aryan:nowornever098@cluster0.1l2sc.mongodb.net/?retryWrites=true&w=majority&serverSelectionTimeoutMS=50000&tls=True&tlsAllowInvalidCertificates=True"
    )
    client.admin.command('ping')
    print("Connected to MongoDB successfully.")
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")

db = client["telegram_bot"]
users_collection = db["users"]
chats_collection = db["chats"]
files_collection = db["files"]

# API keys and configurations remain the same
GEMINI_API_KEY = os.getenv('API_KEY')
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
TELEGRAM_TOKEN = os.getenv('BOT_TOKEN')

# Existing API call function remains the same
def call_gemini_api(prompt):
    headers = {'Content-Type': 'application/json'}
    data = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    try:
        response = requests.post(GEMINI_API_URL, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        result = response.json()
        return result['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        return "I apologize, but I encountered an error processing your request. Please try again in a moment."

# Command handlers
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
        bot_response = call_gemini_api(user_input)
        
        chat_data = {
            "chat_id": chat_id,
            "user_input": user_input,
            "bot_response": bot_response,
            "timestamp": update.message.date
        }
        chats_collection.insert_one(chat_data)
        
        await update.message.reply_text(bot_response)
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        await update.message.reply_text("I apologize, but I encountered an error processing your request. Please try again in a moment.")

async def handle_image(update: Update, context: CallbackContext):
    try:
        file = await update.message.photo[-1].get_file()
        file_path = f"downloads/{file.file_id}.jpg"
        await file.download_to_drive(file_path)
        
        prompt = f"Describe the content of this image: {file_path}"
        description = call_gemini_api(prompt)
        
        file_data = {
            "chat_id": update.message.chat_id,
            "filename": file_path,
            "description": description,
            "timestamp": update.message.date
        }
        files_collection.insert_one(file_data)
        
        await update.message.reply_text(f"Image analysis: {description}")
    except Exception as e:
        logger.error(f"Error handling image: {e}")
        await update.message.reply_text("Sorry, I couldn't process this image. Please try again.")

async def handle_document(update: Update, context: CallbackContext):
    try:
        if not update.message.document.mime_type == 'application/pdf':
            await update.message.reply_text("Please send a PDF document only.")
            return

        file = await update.message.document.get_file()
        file_path = f"downloads/{file.file_id}.pdf"
        await file.download_to_drive(file_path)
        
        pdf_text = extract_text_from_pdf(file_path)
        summary = call_gemini_api(f"Summarize this text: {pdf_text[:4000]}")  # Limit text length
        
        file_data = {
            "chat_id": update.message.chat_id,
            "filename": file_path,
            "summary": summary,
            "timestamp": update.message.date
        }
        files_collection.insert_one(file_data)
        
        await update.message.reply_text(f"PDF Summary: {summary}")
    except Exception as e:
        logger.error(f"Error handling document: {e}")
        await update.message.reply_text("Sorry, I couldn't process this document. Please ensure it's a valid PDF file.")

def extract_text_from_pdf(file_path):
    text = ""
    try:
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text()
    except Exception as e:
        logger.error(f"Error reading PDF file: {e}")
        return "Could not extract text from the PDF."
    return text

async def web_search(update: Update, context: CallbackContext):
    if not context.args:
        await update.message.reply_text("Please provide a search query. Usage: /websearch your search query")
        return

    query = " ".join(context.args)
    try:
        search_results = list(search(query, num_results=5))
        
        if not search_results:
            await update.message.reply_text("No results found for your query.")
            return
            
        reply_text = "Search Results:\n\n"
        for i, link in enumerate(search_results, 1):
            reply_text += f"{i}. {link}\n"
        
        await update.message.reply_text(reply_text)
    except Exception as e:
        logger.error(f"Error in web search: {e}")
        await update.message.reply_text("Sorry, I encountered an error while searching. Please try again later.")

def main():
    # Create downloads directory if it doesn't exist
    os.makedirs("downloads", exist_ok=True)
    
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Handler registration in correct order
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("websearch", web_search))  # Register web search before general handlers
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_document))  # Specifically handle PDFs
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling()

if __name__ == '__main__':
    main()