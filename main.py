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
import mimetypes
import base64

load_dotenv()

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB setup remains the same
try:
    client = pymongo.MongoClient(
        os.getenv('MONGODB_URI')
    )
    client.admin.command('ping')
    print("Connected to MongoDB successfully.")
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")

db = client["telegram_bot"]
users_collection = db["users"]
chats_collection = db["chats"]
files_collection = db["files"]

# API configurations
GEMINI_API_KEY = os.getenv('API_KEY')
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
TELEGRAM_TOKEN = os.getenv('BOT_TOKEN')

# Supported file types
SUPPORTED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
SUPPORTED_DOC_TYPES = {'application/pdf'}

def encode_image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def call_gemini_api(prompt, image_path=None):
    headers = {'Content-Type': 'application/json'}
    
    if image_path:
        # For image analysis, use Gemini's vision capabilities
        image_base64 = encode_image_to_base64(image_path)
        data = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_base64
                        }
                    }
                ]
            }]
        }
    else:
        # For text-only analysis
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

async def handle_file(update: Update, context: CallbackContext):
    """Generic file handler for both images and documents"""
    try:
        # Determine if it's a photo or document
        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            mime_type = 'image/jpeg'  # Telegram converts all photos to JPEG
        else:
            file = await update.message.document.get_file()
            mime_type = update.message.document.mime_type or mimetypes.guess_type(file.file_path)[0]

        if not mime_type:
            await update.message.reply_text("Sorry, I couldn't determine the file type. Please try again.")
            return

        # Check if file type is supported
        if mime_type not in SUPPORTED_IMAGE_TYPES and mime_type not in SUPPORTED_DOC_TYPES:
            await update.message.reply_text(
                "Sorry, I can only process the following file types:\n"
                "• Images: JPG, PNG, GIF, WebP\n"
                "• Documents: PDF"
            )
            return

        # Create unique filename
        file_extension = mimetypes.guess_extension(mime_type) or '.unknown'
        file_path = f"downloads/{file.file_id}{file_extension}"
        
        # Download file
        await file.download_to_drive(file_path)

        # Process file based on type
        if mime_type in SUPPORTED_IMAGE_TYPES:
            # Image analysis
            prompt = """Analyze this image and provide:
            1. A detailed description of what you see
            2. Any text or writing visible in the image
            3. Notable objects, people, or elements
            4. The overall context or setting
            5. Any relevant details about quality, style, or composition"""
            
            analysis = call_gemini_api(prompt, file_path)
            
        elif mime_type == 'application/pdf':
            # PDF analysis
            pdf_text = extract_text_from_pdf(file_path)
            prompt = f"""Analyze this PDF content and provide:
            1. A comprehensive summary
            2. Key topics or themes
            3. Important points or findings
            4. Document structure and organization
            
            Content: {pdf_text[:4000]}"""  # Limit text length
            
            analysis = call_gemini_api(prompt)

        # Save metadata to MongoDB
        file_data = {
            "chat_id": update.message.chat_id,
            "file_id": file.file_id,
            "filename": file_path,
            "mime_type": mime_type,
            "analysis": analysis,
            "timestamp": update.message.date,
            "file_size": os.path.getsize(file_path)
        }
        files_collection.insert_one(file_data)

        # Send analysis to user
        await update.message.reply_text(f"File Analysis:\n\n{analysis}")

    except Exception as e:
        logger.error(f"Error handling file: {e}")
        await update.message.reply_text("Sorry, I couldn't process this file. Please try again.")

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

    # Handler registration
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("websearch", web_search))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    # application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    # application.add_handler(MessageHandler(filters.Document.PDF, handle_document))  # Specifically handle PDFs
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    
    # Combine photo and document handling into one handler
    application.add_handler(MessageHandler(
        filters.PHOTO | 
        (filters.Document.IMAGE | filters.Document.PDF), 
        handle_file
    ))
    
    # Text message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling()

if __name__ == '__main__':
    main()
