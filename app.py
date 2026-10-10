import os
import asyncio
import requests
import telebot
from flask import Flask, request
from google import genai
import edge_tts
from moviepy.editor import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip

# Initialize App & Clients
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# Helper: Async edge-tts wrapper
def generate_voiceover(text, output_audio_path):
    async def _tts():
        communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural")
        await communicate.save(output_audio_path)
    asyncio.run(_tts())

# Helper: Fetch free stock video clip from Pixabay
def get_pixabay_video(query, output_video_path):
    url = f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}&q={query}&per_page=3"
    response = requests.get(url).json()
    
    if response.get("hits") and len(response["hits"]) > 0:
        videos = response["hits"][0]["videos"]
        video_url = videos.get("medium", {}).get("url") or videos.get("small", {}).get("url")
        
        if video_url:
            video_data = requests.get(video_url).content
            with open(output_video_path, "wb") as f:
                f.write(video_data)
            return True
    return False

# Telegram Handler: /generate <topic>
@bot.message_handler(commands=['generate'])
def handle_generate(message):
    chat_id = message.chat.id
    topic = message.text.replace('/generate', '').strip()
    
    if not topic:
        bot.reply_to(message, "Please supply a topic. Example:\n`/generate 3 mind blowing space facts`", parse_mode="Markdown")
        return

    bot.send_message(chat_id, f"🎬 *Processing Video Request:* '{topic}'\nWriting script...", parse_mode="Markdown")

    try:
        # Step 1: Script via Gemini API
        prompt = f"Write a concise 30-second narration script for a YouTube Short about: {topic}. Return ONLY the spoken words, no cues or headers."
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        script_text = response.text.strip()
        
        # Step 2: Voiceover via Edge-TTS
        bot.send_message(chat_id, "🎙️ Generating voiceover audio...")
        audio_path = "/tmp/voice.mp3"
        generate_voiceover(script_text, audio_path)

        # Step 3: Fetch Stock Background Video from Pixabay
        bot.send_message(chat_id, "📹 Fetching background stock visuals...")
        bg_video_path = "/tmp/bg.mp4"
        success = get_pixabay_video(topic, bg_video_path)
        
        if not success:
            bot.send_message(chat_id, "⚠️ Could not find exact background footage. Retrying with 'nature' fallback...")
            get_pixabay_video("nature", bg_video_path)

        # Step 4: Render Video with MoviePy
        bot.send_message(chat_id, "⚙️ Rendering final MP4 file...")
        audio_clip = AudioFileClip(audio_path)
        video_clip = VideoFileClip(bg_video_path).subclip(0, audio_clip.duration)
        
        final_clip = video_clip.set_audio(audio_clip)
        output_path = "/tmp/final_short.mp4"
        final_clip.write_videofile(output_path, codec="libx264", audio_codec="aac", fps=24)

        # Step 5: Send Video back to Telegram on iPhone
        bot.send_message(chat_id, "✅ *Render Complete!* Sending preview file...", parse_mode="Markdown")
        with open(output_path, "rb") as video_file:
            bot.send_video(chat_id, video_file, caption=f"*Script Preview:*\n{script_text[:200]}...", parse_mode="Markdown")

    except Exception as e:
        bot.send_message(chat_id, f"❌ Error generating video: {str(e)}")

# Webhook Endpoint for Render
@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route('/', methods=['GET'])
def index():
    return "YouTube Automation Backend Active", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
