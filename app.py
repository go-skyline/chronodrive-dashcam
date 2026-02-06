import os
import re
import logging
import random
import subprocess
import json
from datetime import datetime
from quart import Quart, Blueprint, request, jsonify, render_template, send_from_directory
from quart_cors import cors
from werkzeug.utils import secure_filename
from werkzeug.routing import BuildError
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import uuid
from celery import Celery
from celery.result import AsyncResult
import aiofiles
import redis.asyncio as redis
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Quart app
app = Quart(__name__)
app = cors(app, allow_origin=["https://tinyomnibus.me", "https://chronodrive.tinyomnibus.me"])
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')

# Set maximum upload size to 2GB
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024
app.config['BODY_TIMEOUT'] = 600  # 10 minutes timeout

# 設定 OpenWeatherMap API
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY', '54f397cc6995fac49eb4ed70d01c290e')
WEATHER_CACHE = {}
CACHE_DURATION = 600  # 10分鐘快取

# Celery configuration
app.config['CELERY_BROKER_URL'] = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')
app.config['CELERY_RESULT_BACKEND'] = os.getenv('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')

# Initialize Celery
celery = Celery(
    app.name,
    broker=app.config['CELERY_BROKER_URL'],
    backend=app.config['CELERY_RESULT_BACKEND']
)
celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    result_expires=86400,  # 24 hours
)

# Redis client for task metadata
redis_client = redis.Redis(host='redis', port=6379, db=6, decode_responses=True)  # Use db=6 to avoid Celery conflicts

# FFmpeg configuration
FFMPEG_CONFIG = {
    'crf': '22',
    'preset': 'medium',
    'duration': '60',
    'white_balance_filter': 'eq=gamma_r=1.15:gamma_g=1.15:gamma_b=1.15',
    'enhance_filter': 'hqdn3d=3:3:2:2,unsharp=5:5:1.0:5:5:0.0,eq=brightness=0.05:contrast=1.5',
    'filter_mode': 'eq',
    'font_size_single': '24',
    'font_size_grid': '32',
    'font_color': 'white',
    'topright_watermark_opacity': '0.85',
    'center_watermark_opacity': '0.85',
    'grid_single_width': '960',
    'grid_single_height': '540',
    # 360 mode specific settings for 16:9 ratio with aligned layout
    '360_large_width': '940',      # Top row cameras (large)
    '360_large_height': '528',
    '360_small_width': '465',      # Bottom row cameras (small)
    '360_small_height': '262',
    '360_total_width': '1920',     # 16:9 aspect ratio
    '360_total_height': '1080',
    '360_crf': '20',              # Better quality for 360 mode
    '360_font_size': '28'
}

# reCAPTCHA configuration
RECAPTCHA_CONFIG = {
    'site_key': os.getenv('RECAPTCHA_SITE_KEY', '6LeRrGErAAAAAM9HZrwhYVTAZZnsua14raXsLTAQ'),
    'secret_key': os.getenv('RECAPTCHA_SECRET_KEY', '6LeRrGErAAAAAGAeDjH7DL26UiLRCX3cx9WJ2U0h'),
    'verify_url': 'https://www.google.com/recaptcha/api/siteverify'
}

async def verify_recaptcha(recaptcha_response):
    """Verify reCAPTCHA v3"""
    try:
        data = {
            'secret': RECAPTCHA_CONFIG['secret_key'],
            'response': recaptcha_response
        }
        response = requests.post(RECAPTCHA_CONFIG['verify_url'], data=data)
        response.raise_for_status()
        result = response.json()
        if result.get('success', False) and result.get('score', 0) >= 0.5:
            return True
        else:
            logger.warning(f"reCAPTCHA verification failed: {result}")
            return False
    except Exception as e:
        logger.error(f"reCAPTCHA verification error: {e}")
        return False

# SMTP configuration
EMAIL_CONFIG = {
    'smtp_host': os.getenv('SMTP_HOST', 'smtp.gmail.com'),
    'smtp_port': int(os.getenv('SMTP_PORT', 587)),
    'smtp_user': os.getenv('SMTP_USER', 'mail.skyline.1982@gmail.com'),
    'smtp_password': os.getenv('SMTP_PASSWORD', 'fkck mwog tczb xzxv'),
    'from_email': os.getenv('FROM_EMAIL', 'mail.skyline.1982@gmail.com'),
    'to_email': os.getenv('TO_EMAIL', 'mail.skyline.1982@gmail.com')
}

# Available audio files
AVAILABLE_AUDIOS = [
    'Do_The_Bop.mp3',
    'Dopamina.mp3',
    'Los_Cabos.mp3',
    'M_Fischer.mp3',
    'Take_Me_Down_To_The_Fashion_Show.mp3',
    'Chicago.mp3',
    'La_Fiesta_Y_La_Cruda.mp3',
    'Sugar_High.mp3',
    'The_Monuments_and_Tunnels_in_Goa_and_Hampi.mp3'
]

# Configuration
UPLOAD_FOLDER = 'static/uploads'
OUTPUT_FOLDER = 'static/output'
ALLOWED_EXTENSIONS = {'mp4'}

# Create necessary folders
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_timestamp_from_any_filename(filename):
    pattern = r'(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})'
    match = re.search(pattern, filename)
    if match:
        date_part = match.group(1)
        hour = match.group(2)
        minute = match.group(3)
        second = match.group(4)
        timestamp_str = f"{date_part} {hour}:{minute}:{second}"
        try:
            return datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except ValueError as e:
            logger.error(f"Invalid timestamp format: {timestamp_str}: {e}")
            return None
    logger.warning(f"No timestamp found in filename: {filename}")
    return None

def classify_files_by_position(files_dict):
    position_map = {}
    pattern = re.compile(r'.*-(front|back|left_repeater|right_repeater|left_pillar|right_pillar).*\.mp4$', re.IGNORECASE)
    for file_obj in files_dict.getlist('videos'):
        if file_obj.filename == '':
            continue
        if not allowed_file(file_obj.filename):
            logger.warning(f"Only MP4 files allowed: {file_obj.filename}")
            continue
        match = pattern.search(file_obj.filename)
        if match:
            position = match.group(1).lower()
            position_map[position] = file_obj
        else:
            logger.warning(f"Unable to identify file position: {file_obj.filename}")
    return position_map

def get_position_from_filename(filename):
    filename_lower = filename.lower()
    if 'front' in filename_lower:
        return 'front'
    elif 'back' in filename_lower:
        return 'back'
    elif 'left_repeater' in filename_lower:
        return 'left_repeater'
    elif 'right_repeater' in filename_lower:
        return 'right_repeater'
    elif 'left_pillar' in filename_lower:
        return 'left_pillar'
    elif 'right_pillar' in filename_lower:
        return 'right_pillar'
    return None

async def cleanup_files(file_paths):
    for file_path in file_paths if isinstance(file_paths, list) else [file_paths]:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up file: {file_path}")
        except Exception as e:
            logger.error(f"Failed to clean up file {file_path}: {e}")

async def get_random_audio_path():
    try:
        selected_audio = random.choice(AVAILABLE_AUDIOS)
        audio_path = os.path.join('static/audios', selected_audio)
        if os.path.exists(audio_path):
            logger.info(f"Randomly selected audio: {selected_audio}")
            return audio_path, selected_audio
        else:
            logger.warning(f"Audio file not found: {audio_path}")
            return None, None
    except Exception as e:
        logger.error(f"Error selecting random audio: {e}")
        return None, None

async def send_contact_email(name, email, subject, message):
    """Send contact form email asynchronously"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_CONFIG['from_email']
        msg['To'] = EMAIL_CONFIG['to_email']
        msg['Subject'] = f"New Contact Form Submission: {subject}"
        body = f"""
        New contact form submission received:

        Name: {name}
        Email: {email}
        Subject: {subject}
        Message:
        {message}
        
        Submitted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        msg.attach(MIMEText(body, 'plain'))
        smtp = aiosmtplib.SMTP(
            hostname=EMAIL_CONFIG['smtp_host'],
            port=EMAIL_CONFIG['smtp_port'],
            use_tls=False,
            start_tls=True
        )
        await smtp.connect()
        await smtp.login(EMAIL_CONFIG['smtp_user'], EMAIL_CONFIG['smtp_password'])
        await smtp.send_message(msg)
        await smtp.quit()
        logger.info(f"Email sent successfully from {email} to {EMAIL_CONFIG['to_email']}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False

@celery.task(bind=True, max_retries=2)
def schedule_file_deletion(self, file_path, delay_seconds):
    try:
        logger.info(f"Scheduling deletion for file: {file_path} after {delay_seconds} seconds")
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Successfully deleted expired file: {file_path}")
        else:
            logger.warning(f"File not found for deletion: {file_path}")
    except Exception as e:
        logger.error(f"Error deleting file {file_path}: {e}")
        self.retry(countdown=60)

@celery.task(bind=True, max_retries=2)
def process_single_video(self, input_path, output_path, duration, audio_path, filter_mode, unix_timestamp):
    logger.info(f"Processing single video with unix_timestamp: {unix_timestamp} ({datetime.fromtimestamp(unix_timestamp)})")
    try:
        watermark_path_topright = 'static/images/TeslaCAM_256.png'
        font_path = 'static/fonts/dejavu-sans-bold.ttf'
        font_filter = f"fontfile={font_path}:" if os.path.exists(font_path) else ""
        has_topright_watermark = os.path.exists(watermark_path_topright)
        video_filter = FFMPEG_CONFIG['enhance_filter'] if filter_mode == 'enhance' else FFMPEG_CONFIG['white_balance_filter']
        if has_topright_watermark:
            if audio_path:
                cmd = [
                    'ffmpeg', '-y',
                    '-i', input_path,
                    '-i', watermark_path_topright,
                    '-i', audio_path,
                    '-filter_complex',
                    f"""[0:v]{video_filter}[wb];
[1:v]format=rgba,colorchannelmixer=aa={FFMPEG_CONFIG['topright_watermark_opacity']}[watermark_topright];
[wb][watermark_topright]overlay=x=W-w-16:y=16[tmp1];
[tmp1]drawtext={font_filter}text='%{{pts\\:localtime\\:{unix_timestamp}}}':fontsize={FFMPEG_CONFIG['font_size_single']}:fontcolor={FFMPEG_CONFIG['font_color']}:x=16:y=h-th-16[final1]""",
                    '-map', '[final1]',
                    '-map', '2:a',
                    '-c:v', 'libx264',
                    '-c:a', 'aac',
                    '-shortest',
                    '-t', duration,
                    output_path
                ]
            else:
                cmd = [
                    'ffmpeg', '-y',
                    '-i', input_path,
                    '-i', watermark_path_topright,
                    '-filter_complex',
                    f"""[0:v]{video_filter}[wb];
[1:v]format=rgba,colorchannelmixer=aa={FFMPEG_CONFIG['topright_watermark_opacity']}[watermark_topright];
[wb][watermark_topright]overlay=x=W-w-16:y=16[tmp1];
[tmp1]drawtext={font_filter}text='%{{pts\\:localtime\\:{unix_timestamp}}}':fontsize={FFMPEG_CONFIG['font_size_single']}:fontcolor={FFMPEG_CONFIG['font_color']}:x=16:y=h-th-16[final1]""",
                    '-map', '[final1]',
                    '-c:v', 'libx264',
                    '-t', duration,
                    output_path
                ]
        else:
            if audio_path:
                cmd = [
                    'ffmpeg', '-y',
                    '-i', input_path,
                    '-i', audio_path,
                    '-vf',
                    f"{video_filter},drawtext={font_filter}text='%{{pts\\:localtime\\:{unix_timestamp}}}':fontsize={FFMPEG_CONFIG['font_size_single']}:fontcolor={FFMPEG_CONFIG['font_color']}:x=16:y=h-th-16",
                    '-c:v', 'libx264',
                    '-c:a', 'aac',
                    '-shortest',
                    '-t', duration,
                    output_path
                ]
            else:
                cmd = [
                    'ffmpeg', '-y',
                    '-i', input_path,
                    '-vf',
                    f"{video_filter},drawtext={font_filter}text='%{{pts\\:localtime\\:{unix_timestamp}}}':fontsize={FFMPEG_CONFIG['font_size_single']}:fontcolor={FFMPEG_CONFIG['font_color']}:x=16:y=h-th-16",
                    '-c:v', 'libx264',
                    '-t', duration,
                    output_path
                ]
        logger.info(f"Single file FFmpeg command: {' '.join(cmd)}")
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if process.returncode == 0:
            logger.info(f"Successfully processed single file: {output_path}")
            schedule_file_deletion.apply_async(args=[output_path, 21600], countdown=21600)
            return {'status': 'success', 'output_path': output_path}
        else:
            logger.error(f"FFmpeg error: {process.stderr}")
            raise Exception(f"FFmpeg processing failed: {process.stderr}")
    except Exception as e:
        logger.error(f"Error processing single file watermark: {e}")
        self.retry(countdown=60)

@celery.task(bind=True, max_retries=3)
def process_four_grid_video(self, video_files, output_path, start_time, audio_path, filter_mode):
    unix_timestamp = int(start_time.timestamp())
    logger.info(f"Processing four-grid video with unix_timestamp: {unix_timestamp} ({datetime.fromtimestamp(unix_timestamp)})")
    try:
        positions = ['front', 'back', 'left', 'right']
        position_files = {}
        for file_path in video_files:
            filename = os.path.basename(file_path)
            position = get_position_from_filename(filename)
            if position:
                # Map repeater positions to simplified names for four_grid
                if position == 'left_repeater':
                    position_files['left'] = file_path
                elif position == 'right_repeater':
                    position_files['right'] = file_path
                else:
                    position_files[position] = file_path
        gap = 4
        total_width = 1920 + gap
        total_height = 1080 + gap
        single_width = int(FFMPEG_CONFIG['grid_single_width']) - gap // 2
        single_height = int(FFMPEG_CONFIG['grid_single_height']) - gap // 2
        watermark_path_center = 'static/images/dirpng.png'
        watermark_path_topright = 'static/images/TeslaCAM.png'
        background_path = 'static/images/pixbg02.jpg'
        font_path = 'static/fonts/dejavu-sans-bold.ttf'
        font_filter = f"fontfile={font_path}:" if os.path.exists(font_path) else ""
        has_center_watermark = os.path.exists(watermark_path_center)
        has_topright_watermark = os.path.exists(watermark_path_topright)
        has_background = os.path.exists(background_path)
        inputs = []
        for position in positions:
            if position in position_files:
                inputs.extend(['-i', position_files[position]])
            else:
                inputs.extend(['-f', 'lavfi', '-i', f'color=#4DA8DA:s={single_width}x{single_height}:d={FFMPEG_CONFIG["duration"]}'])
        if has_background:
            inputs.extend(['-i', background_path])
        if has_center_watermark:
            inputs.extend(['-i', watermark_path_center])
        if has_topright_watermark:
            inputs.extend(['-i', watermark_path_topright])
        if audio_path:
            inputs.extend(['-i', audio_path])
        video_filter = FFMPEG_CONFIG['enhance_filter'] if filter_mode == 'enhance' else FFMPEG_CONFIG['white_balance_filter']
        filter_parts = []
        current_input_idx = 0
        for i, position in enumerate(positions):
            if position in position_files:
                if has_background:
                    filter_parts.append(f"[{len(positions) + has_background - 1}:v]scale={single_width}:{single_height}[bg_{position}];")
                    filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS,{video_filter},scale={single_width}:{single_height}:force_original_aspect_ratio=decrease[scaled_{position}];")
                    filter_parts.append(f"[bg_{position}][scaled_{position}]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2[{position}];")
                else:
                    filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS,{video_filter},scale={single_width}:{single_height}:force_original_aspect_ratio=decrease,pad={single_width}:{single_height}:(ow-iw)/2:(oh-ih)/2[{position}];")
            else:
                filter_parts.append(f"[{i}:v]drawtext={font_filter}text='No Source':fontcolor={FFMPEG_CONFIG['font_color']}:fontsize=42:x=(w-text_w)/2:y=(h-text_h)/2[{position}];")
            current_input_idx += 1
        if has_background:
            current_input_idx += 1
        filter_parts.append(f"color=white:s={total_width}x{total_height}[base];")
        filter_parts.append(f"[base][front]overlay=shortest=1:x=0:y=0[tmp1];")
        filter_parts.append(f"[tmp1][back]overlay=shortest=1:x={single_width + gap}:y=0[tmp2];")
        filter_parts.append(f"[tmp2][left]overlay=shortest=1:x=0:y={single_height + gap}[tmp3];")
        filter_parts.append(f"[tmp3][right]overlay=shortest=1:x={single_width + gap}:y={single_height + gap}[tmp4];")
        if has_center_watermark:
            filter_parts.append(f"[{current_input_idx}:v]format=rgba,colorchannelmixer=aa={FFMPEG_CONFIG['center_watermark_opacity']}[watermark_center];")
            filter_parts.append(f"[tmp4][watermark_center]overlay=x=(W-w)/2:y=(H-h)/2[tmp5];")
            current_input_idx += 1
        else:
            filter_parts.append(f"[tmp4]null[tmp5];")
        if has_topright_watermark:
            filter_parts.append(f"[{current_input_idx}:v]format=rgba,colorchannelmixer=aa={FFMPEG_CONFIG['topright_watermark_opacity']}[watermark_topright];")
            filter_parts.append(f"[tmp5][watermark_topright]overlay=x=W-w-16:y=16[tmp6];")
            current_input_idx += 1
        else:
            filter_parts.append(f"[tmp5]null[tmp6];")
        filter_parts.append(f"[tmp6]drawtext={font_filter}text='%{{pts\\:localtime\\:{unix_timestamp}}}':fontsize={FFMPEG_CONFIG['font_size_grid']}:fontcolor={FFMPEG_CONFIG['font_color']}:x=10:y=h-th-10[final]")
        filter_complex = "".join(filter_parts)
        cmd = [
            'ffmpeg', '-y'
        ] + inputs + [
            '-filter_complex', filter_complex,
            '-map', '[final]'
        ]
        if audio_path:
            cmd.extend(['-map', f'{current_input_idx}:a', '-c:a', 'aac', '-shortest'])
        cmd.extend([
            '-c:v', 'libx264',
            '-preset', FFMPEG_CONFIG['preset'],
            '-crf', FFMPEG_CONFIG['crf'],
            '-t', FFMPEG_CONFIG['duration'],
            output_path
        ])
        logger.info(f"Four-grid FFmpeg command: {' '.join(cmd)}")
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if process.returncode == 0:
            logger.info(f"Successfully created four-grid video: {output_path}")
            schedule_file_deletion.apply_async(args=[output_path, 43200], countdown=43200)
            return {'status': 'success', 'output_path': output_path}
        else:
            logger.error(f"FFmpeg error: {process.stderr}")
            raise Exception(f"FFmpeg processing failed: {process.stderr}")
    except Exception as e:
        logger.error(f"Four-grid processing error: {e}")
        self.retry(countdown=60)

@celery.task(bind=True, max_retries=3)
def process_360_video(self, video_files, output_path, start_time, audio_path, filter_mode):
    unix_timestamp = int(start_time.timestamp())
    logger.info(f"Processing 360 video with unix_timestamp: {unix_timestamp} ({datetime.fromtimestamp(unix_timestamp)})")
    try:
        positions = ['front', 'back', 'left_repeater', 'left_pillar', 'right_repeater', 'right_pillar']
        position_files = {}
        for file_path in video_files:
            filename = os.path.basename(file_path)
            position = get_position_from_filename(filename)
            if position:
                position_files[position] = file_path

        # 360 mode layout: Top row 2 large cameras, bottom row 4 small cameras (16:9 format)
        # Perfect alignment: top camera width = bottom two cameras width + gap
        gap = 10
        large_width = int(FFMPEG_CONFIG['360_large_width'])      # 940px per large camera (top)
        large_height = int(FFMPEG_CONFIG['360_large_height'])    # 528px per large camera (top)
        small_width = int(FFMPEG_CONFIG['360_small_width'])      # 465px per small camera (bottom)
        small_height = int(FFMPEG_CONFIG['360_small_height'])    # 262px per small camera (bottom)

        # Use fixed 16:9 ratio (1920x1080)
        total_width = int(FFMPEG_CONFIG['360_total_width'])      # 1920px
        total_height = int(FFMPEG_CONFIG['360_total_height'])    # 1080px

        watermark_path_center = 'static/images/360pie.png'
        watermark_path_topright = 'static/images/TeslaCAM.png'
        background_path = 'static/images/pixbg02.jpg'
        font_path = 'static/fonts/dejavu-sans-bold.ttf'
        font_filter = f"fontfile={font_path}:" if os.path.exists(font_path) else ""

        has_center_watermark = os.path.exists(watermark_path_center)
        has_topright_watermark = os.path.exists(watermark_path_topright)
        has_background = os.path.exists(background_path)

        inputs = []
        for position in positions:
            if position in position_files:
                inputs.extend(['-i', position_files[position]])
            else:
                # Use appropriate size based on position (top row = large, bottom row = small)
                if position in ['front', 'back']:  # Top row positions
                    placeholder_size = f'{large_width}x{large_height}'
                else:  # Bottom row positions
                    placeholder_size = f'{small_width}x{small_height}'
                inputs.extend(['-f', 'lavfi', '-i', f'color=#4DA8DA:s={placeholder_size}:d={FFMPEG_CONFIG["duration"]}'])

        if has_background:
            inputs.extend(['-i', background_path])
        if has_center_watermark:
            inputs.extend(['-i', watermark_path_center])
        if has_topright_watermark:
            inputs.extend(['-i', watermark_path_topright])
        if audio_path:
            inputs.extend(['-i', audio_path])

        video_filter = FFMPEG_CONFIG['enhance_filter'] if filter_mode == 'enhance' else FFMPEG_CONFIG['white_balance_filter']
        filter_parts = []
        current_input_idx = 0

        # Process each position with video filters (different sizes for top/bottom row)
        top_positions = ['front', 'back']  # Large cameras on top row
        bottom_positions = ['left_repeater', 'left_pillar', 'right_repeater', 'right_pillar']  # Small cameras on bottom row

        for i, position in enumerate(positions):
            if position in position_files:
                # Determine size based on position (top row = large, bottom row = small)
                if position in top_positions:
                    cam_width, cam_height = large_width, large_height
                else:
                    cam_width, cam_height = small_width, small_height

                if has_background:
                    # Use correct background input index: it's always after all 6 video positions
                    filter_parts.append(f"[{len(positions)}:v]scale={cam_width}:{cam_height}[bg_{position}];")
                    filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS,{video_filter},scale={cam_width}:{cam_height}:force_original_aspect_ratio=decrease[scaled_{position}];")
                    filter_parts.append(f"[bg_{position}][scaled_{position}]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2[{position}];")
                else:
                    filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS,{video_filter},scale={cam_width}:{cam_height}:force_original_aspect_ratio=decrease,pad={cam_width}:{cam_height}:(ow-iw)/2:(oh-ih)/2[{position}];")
            else:
                # Create placeholder for missing cameras (size depends on position)
                if position in top_positions:
                    cam_width, cam_height = large_width, large_height
                    font_size = 42
                else:
                    cam_width, cam_height = small_width, small_height
                    font_size = 24
                filter_parts.append(f"[{i}:v]drawtext={font_filter}text='No Source':fontcolor={FFMPEG_CONFIG['font_color']}:fontsize={font_size}:x=(w-text_w)/2:y=(h-text_h)/2[{position}];")
            current_input_idx += 1

        if has_background:
            current_input_idx += 1

        # Create base canvas - use black background for 360 mode
        filter_parts.append(f"color=black:s={total_width}x{total_height}[base];")

        # Calculate positions for perfect alignment
        # Top row: 2 large cameras centered
        top_y = (total_height - large_height - small_height - gap) // 2
        top_left_x = (total_width - 2 * large_width - gap) // 2
        top_right_x = top_left_x + large_width + gap

        # Bottom row: 4 small cameras, perfectly aligned under the top cameras
        bottom_y = top_y + large_height + gap
        bottom_x_start = top_left_x  # Align with top row start

        # Position top row cameras (large)
        filter_parts.append(f"[base][front]overlay=shortest=1:x={top_left_x}:y={top_y}[tmp1];")
        filter_parts.append(f"[tmp1][back]overlay=shortest=1:x={top_right_x}:y={top_y}[tmp2];")

        # Position bottom row cameras (small) - 4 cameras aligned under the 2 large ones
        filter_parts.append(f"[tmp2][left_repeater]overlay=shortest=1:x={bottom_x_start}:y={bottom_y}[tmp3];")
        filter_parts.append(f"[tmp3][left_pillar]overlay=shortest=1:x={bottom_x_start + small_width + gap}:y={bottom_y}[tmp4];")
        filter_parts.append(f"[tmp4][right_repeater]overlay=shortest=1:x={bottom_x_start + 2 * (small_width + gap)}:y={bottom_y}[tmp5];")
        filter_parts.append(f"[tmp5][right_pillar]overlay=shortest=1:x={bottom_x_start + 3 * (small_width + gap)}:y={bottom_y}[tmp6];")

        # Add watermarks - position center watermark at the intersection of 2x3 grid lines
        if has_center_watermark:
            # Calculate intersection point:
            # - Horizontal: between front and back cameras (top row division)
            # - Vertical: between top and bottom rows
            intersection_x = top_left_x + large_width + gap // 2  # Center of gap between front/back cameras
            intersection_y = top_y + large_height + gap // 2     # Center of gap between top/bottom rows
            filter_parts.append(f"[{current_input_idx}:v]format=rgba,colorchannelmixer=aa={FFMPEG_CONFIG['center_watermark_opacity']}[watermark_center];")
            filter_parts.append(f"[tmp6][watermark_center]overlay=x={intersection_x}-w/2:y={intersection_y}-h/2[tmp7];")
            current_input_idx += 1
        else:
            filter_parts.append(f"[tmp6]null[tmp7];")

        if has_topright_watermark:
            filter_parts.append(f"[{current_input_idx}:v]format=rgba,colorchannelmixer=aa={FFMPEG_CONFIG['topright_watermark_opacity']}[watermark_topright];")
            filter_parts.append(f"[tmp7][watermark_topright]overlay=x=W-w-16:y=16[tmp8];")
            current_input_idx += 1
        else:
            filter_parts.append(f"[tmp7]null[tmp8];")

        # Add timestamp
        filter_parts.append(f"[tmp8]drawtext={font_filter}text='%{{pts\\:localtime\\:{unix_timestamp}}}':fontsize={FFMPEG_CONFIG['360_font_size']}:fontcolor={FFMPEG_CONFIG['font_color']}:x=10:y=h-th-10[final]")

        filter_complex = "".join(filter_parts)
        cmd = [
            'ffmpeg', '-y'
        ] + inputs + [
            '-filter_complex', filter_complex,
            '-map', '[final]'
        ]

        if audio_path:
            cmd.extend(['-map', f'{current_input_idx}:a', '-c:a', 'aac', '-shortest'])

        cmd.extend([
            '-c:v', 'libx264',
            '-preset', FFMPEG_CONFIG['preset'],
            '-crf', FFMPEG_CONFIG['360_crf'],  # Use better quality for 360 mode
            '-t', FFMPEG_CONFIG['duration'],
            output_path
        ])

        logger.info(f"360 mode FFmpeg command: {' '.join(cmd)}")
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if process.returncode == 0:
            logger.info(f"Successfully created 360 video: {output_path}")
            schedule_file_deletion.apply_async(args=[output_path, 43200], countdown=43200)
            return {'status': 'success', 'output_path': output_path}
        else:
            logger.error(f"FFmpeg error: {process.stderr}")
            raise Exception(f"FFmpeg processing failed: {process.stderr}")
    except Exception as e:
        logger.error(f"360 processing error: {e}")
        self.retry(countdown=60)

# Create Blueprint for /clips and /clips/static prefix
#clips_bp = Blueprint('clips', __name__, url_prefix='/clips')
clips_bp = Blueprint('clips', __name__)

@clips_bp.route('/', strict_slashes=False)
async def index():
    logger.info(f"Accessing clips index route: {request.path}")
    return await render_template('index.html')

@clips_bp.route('/landing', strict_slashes=False)
async def landing():
    logger.info(f"Accessing clips landing page: {request.path}")
    return await render_template('landing.html')

@clips_bp.route('/upload', methods=['GET', 'POST'])
async def upload():
    logger.info(f"Accessing upload route: {request.path}")
    if request.method == 'GET':
        return await render_template('upload.html')
    files = await request.files
    form = await request.form
    mode = form.get('mode', 'single')
    logger.info(f"Upload mode detected: '{mode}'")
    if mode == 'single':
        return await handle_single_upload(files, form)
    elif mode == 'four_grid':
        return await handle_four_grid_upload(files, form)
    elif mode == '360':
        return await handle_360_upload(files, form)
    else:
        logger.warning(f"Unknown mode '{mode}', defaulting to four_grid")
        return await handle_four_grid_upload(files, form)

async def handle_single_upload(files, form):
    if 'video' not in files:
        return await render_template('upload.html', error='請選擇影片檔案')
    file = files['video']
    if file.filename == '':
        return await render_template('upload.html', error='請選擇有效的 MP4 影片檔案')
    if not allowed_file(file.filename):
        return await render_template('upload.html', error='請選擇有效的 MP4 影片檔案')
    audio_option = form.get('audio_option', 'no_audio')
    filter_mode = form.get('filter_mode', 'white_balance')
    if filter_mode not in ['white_balance', 'enhance']:
        filter_mode = 'white_balance'
    audio_path = None
    selected_audio_name = None
    if audio_option == 'embed_audio':
        audio_path, selected_audio_name = await get_random_audio_path()
        if not audio_path:
            return await render_template('upload.html', error='系統音效檔案不可用')
    filename = secure_filename(file.filename)
    unique_id = str(uuid.uuid4())
    input_path = os.path.join(UPLOAD_FOLDER, f"{unique_id}_{filename}")
    async with aiofiles.open(input_path, 'wb') as f:
        await f.write(file.read())
    output_filename = f"{unique_id}_watermarked.mp4"
    output_path = os.path.join(OUTPUT_FOLDER, output_filename)
    start_time = extract_timestamp_from_any_filename(filename)
    if start_time is None:
        await cleanup_files(input_path)
        return await render_template('upload.html',
                                   error='檔案名稱不包含有效的時間戳格式（YYYY-MM-DD_HH-MM-SS）')
    unix_timestamp = int(start_time.timestamp())
    task = process_single_video.delay(
        input_path, output_path, FFMPEG_CONFIG['duration'], audio_path, filter_mode, unix_timestamp
    )
    task_metadata = {
        'mode': 'single',
        'input_path': input_path,
        'output_filename': output_filename,
        'output_path': output_path,
        'audio_path': audio_path,
        'audio_name': selected_audio_name,
        'created_at': datetime.now().isoformat()
    }
    await redis_client.setex(f"task:{task.id}", 86400, json.dumps(task_metadata))
    logger.info(f"Submitted single task {task.id} with metadata: {task_metadata}")
    return jsonify({'task_id': task.id})

async def handle_four_grid_upload(files, form):
    try:
        if 'videos' not in files:
            return await render_template('upload.html',
                                       error='請選擇至少一個 MP4 影片檔案')
        position_files = classify_files_by_position(files)
        if not position_files:
            return await render_template('upload.html',
                                       error='沒有找到有效的 MP4 影片檔案')
        if len(position_files) > 4:
            return await render_template('upload.html',
                                       error='最多只能上傳4個檔案')
        audio_option = form.get('audio_option', 'no_audio')
        filter_mode = form.get('filter_mode', 'white_balance')
        if filter_mode not in ['white_balance', 'enhance']:
            filter_mode = 'white_balance'
        audio_path = None
        selected_audio_name = None
        if audio_option == 'embed_audio':
            audio_path, selected_audio_name = await get_random_audio_path()
            if not audio_path:
                return await render_template('upload.html', error='系統音效檔案不可用')
        uploaded_files = []
        saved_positions = []
        timestamps = []
        for position, file_obj in position_files.items():
            start_time = extract_timestamp_from_any_filename(file_obj.filename)
            if start_time is None:
                await cleanup_files(uploaded_files)
                return await render_template('upload.html',
                                           error=f'檔案 {file_obj.filename} 不包含有效的時間戳格式（YYYY-MM-DD_HH-MM-SS）')
            timestamps.append(start_time)
            filename = secure_filename(file_obj.filename)
            unique_id = str(uuid.uuid4())
            file_path = os.path.join(UPLOAD_FOLDER, f"{unique_id}_{filename}")
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(file_obj.read())
            uploaded_files.append(file_path)
            saved_positions.append(position)
        start_time = min(timestamps)
        output_filename = f"four_grid_{str(uuid.uuid4())}.mp4"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        logger.info(f"Processing four-grid video with positions: {saved_positions}")
        if audio_path:
            logger.info(f"Using background music: {selected_audio_name}")
        logger.info(f"Using filter mode: {filter_mode}")
        task = process_four_grid_video.delay(
            uploaded_files, output_path, start_time, audio_path, filter_mode
        )
        task_metadata = {
            'mode': 'four_grid',
            'input_paths': uploaded_files,
            'output_filename': output_filename,
            'output_path': output_path,
            'audio_path': audio_path,
            'audio_name': selected_audio_name,
            'positions': saved_positions,
            'created_at': datetime.now().isoformat()
        }
        await redis_client.setex(f"task:{task.id}", 86400, json.dumps(task_metadata))
        logger.info(f"Submitted four-grid task {task.id} with metadata: {task_metadata}")
        return jsonify({'task_id': task.id})
    except Exception as e:
        logger.error(f"Four-grid upload error: {e}")
        return await render_template('result.html',
                                   success=False,
                                   error=f'處理過程中發生錯誤：{str(e)}')

async def handle_360_upload(files, form):
    try:
        if 'videos' not in files:
            return await render_template('upload.html',
                                       error='請選擇至少一個 MP4 影片檔案')
        position_files = classify_files_by_position(files)
        if not position_files:
            return await render_template('upload.html',
                                       error='沒有找到有效的 MP4 影片檔案')
        if len(position_files) > 6:
            return await render_template('upload.html',
                                       error='最多只能上傳6個檔案')
        audio_option = form.get('audio_option', 'no_audio')
        filter_mode = form.get('filter_mode', 'white_balance')
        if filter_mode not in ['white_balance', 'enhance']:
            filter_mode = 'white_balance'
        audio_path = None
        selected_audio_name = None
        if audio_option == 'embed_audio':
            audio_path, selected_audio_name = await get_random_audio_path()
            if not audio_path:
                return await render_template('upload.html', error='系統音效檔案不可用')
        uploaded_files = []
        saved_positions = []
        timestamps = []
        for position, file_obj in position_files.items():
            start_time = extract_timestamp_from_any_filename(file_obj.filename)
            if start_time is None:
                await cleanup_files(uploaded_files)
                return await render_template('upload.html',
                                           error=f'檔案 {file_obj.filename} 不包含有效的時間戳格式（YYYY-MM-DD_HH-MM-SS）')
            timestamps.append(start_time)
            filename = secure_filename(file_obj.filename)
            unique_id = str(uuid.uuid4())
            file_path = os.path.join(UPLOAD_FOLDER, f"{unique_id}_{filename}")
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(file_obj.read())
            uploaded_files.append(file_path)
            saved_positions.append(position)
        start_time = min(timestamps)
        output_filename = f"360_{str(uuid.uuid4())}.mp4"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        logger.info(f"Processing 360 video with positions: {saved_positions}")
        if audio_path:
            logger.info(f"Using background music: {selected_audio_name}")
        logger.info(f"Using filter mode: {filter_mode}")
        task = process_360_video.delay(
            uploaded_files, output_path, start_time, audio_path, filter_mode
        )
        task_metadata = {
            'mode': '360',
            'input_paths': uploaded_files,
            'output_filename': output_filename,
            'output_path': output_path,
            'audio_path': audio_path,
            'audio_name': selected_audio_name,
            'positions': saved_positions,
            'created_at': datetime.now().isoformat()
        }
        await redis_client.setex(f"task:{task.id}", 86400, json.dumps(task_metadata))
        logger.info(f"Submitted 360 task {task.id} with metadata: {task_metadata}")
        return jsonify({'task_id': task.id})
    except Exception as e:
        logger.error(f"360 upload error: {e}")
        return await render_template('result.html',
                                   success=False,
                                   error=f'處理過程中發生錯誤：{str(e)}')

@clips_bp.route('/loading', methods=['GET'])
async def loading_page():
    task_id = request.args.get('task_id')
    if not task_id:
        return await render_template('error.html', error="找不到任務 ID")
    return await render_template('loading.html', task_id=task_id)

@clips_bp.route('/task_status/<task_id>')
async def task_status(task_id):
    logger.info(f"Checking status for task_id: {task_id}, path={request.path}")
    task = AsyncResult(task_id, app=celery)
    if task.state == 'PENDING':
        response = {'state': 'PENDING', 'status': 'Pending...'}
    elif task.state == 'STARTED':
        response = {'state': 'STARTED', 'status': 'Processing...'}
    elif task.state == 'SUCCESS':
        result = task.get()
        response = {
            'state': 'SUCCESS',
            'status': 'Completed',
            'output_file': os.path.basename(result['output_path']),
            'output_path': result['output_path']
        }
    elif task.state == 'FAILURE':
        response = {'state': 'FAILURE', 'status': str(task.info)}
    else:
        response = {'state': 'UNKNOWN', 'status': 'Task not found or expired'}
    logger.debug(f"Task status response: {response}")
    return jsonify(response)

@clips_bp.route('/result/<task_id>')
async def show_result(task_id):
    logger.info(f"Accessing result route for task_id: {task_id}, path={request.path}")
    task = AsyncResult(task_id, app=celery)
    if task.state != 'SUCCESS':
        logger.warning(f"Task {task_id} not in SUCCESS state: {task.state}")
        return await render_template('result.html',
                                   success=False,
                                   error='任務未完成或失敗，請重新上傳')
    result = task.get()
    output_filename = os.path.basename(result['output_path'])
    metadata = await redis_client.get(f"task:{task_id}")
    if not metadata:
        logger.error(f"Metadata for task {task_id} not found in Redis")
        return await render_template('result.html',
                                   success=False,
                                   error='任務元數據已過期或不可用，請重新上傳')
    metadata = json.loads(metadata)
    mode = metadata.get('mode')
    try:
        if mode == 'single':
            input_path = metadata.get('input_path')
            audio_path = metadata.get('audio_path')
            audio_name = metadata.get('audio_name')
            await cleanup_files(input_path)
            logger.info(f"Cleaned up input file for task {task_id}: {input_path}")
            return await render_template('result.html',
                                       success=True,
                                       output_filename=output_filename,
                                       mode=mode,
                                       has_audio=audio_path is not None,
                                       audio_name=audio_name)
        elif mode == 'four_grid':
            input_paths = metadata.get('input_paths', [])
            audio_path = metadata.get('audio_path')
            audio_name = metadata.get('audio_name')
            positions = metadata.get('positions', [])
            await cleanup_files(input_paths)
            logger.info(f"Cleaned up input files for task {task_id}: {input_paths}")
            return await render_template('result.html',
                                       success=True,
                                       output_filename=output_filename,
                                       mode=mode,
                                       positions=positions,
                                       has_audio=audio_path is not None,
                                       audio_name=audio_name)
        elif mode == '360':
            input_paths = metadata.get('input_paths', [])
            audio_path = metadata.get('audio_path')
            audio_name = metadata.get('audio_name')
            positions = metadata.get('positions', [])
            await cleanup_files(input_paths)
            logger.info(f"Cleaned up input files for task {task_id}: {input_paths}")
            return await render_template('result.html',
                                       success=True,
                                       output_filename=output_filename,
                                       mode=mode,
                                       positions=positions,
                                       has_audio=audio_path is not None,
                                       audio_name=audio_name)
        else:
            logger.error(f"Invalid mode in metadata for task {task_id}: {mode}")
            return await render_template('result.html',
                                       success=False,
                                       error='無效的任務模式，請重新上傳')
    except Exception as e:
        logger.error(f"Error rendering result for task {task_id}: {e}")
        return await render_template('result.html',
                                   success=False,
                                   error=f'Failed to process task: {str(e)}')

@clips_bp.route('/download/<filename>')
async def download(filename):
    logger.info(f"Accessing download route: {request.path}")
    try:
        file_path = os.path.join(OUTPUT_FOLDER, filename)
        if not os.path.exists(file_path):
            logger.error(f"Download file not found: {file_path}")
            return "檔案不存在", 404
        logger.info(f"Downloading file: {filename}")
        response = await send_from_directory(
            OUTPUT_FOLDER,
            filename,
            as_attachment=True
        )
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        logger.error(f"Download error: {e}")
        return "下載失敗", 500

@clips_bp.route('/preview/<filename>')
async def preview(filename):
    logger.info(f"Accessing preview route: {request.path}")
    try:
        file_path = os.path.join(OUTPUT_FOLDER, filename)
        if not os.path.exists(file_path):
            logger.error(f"Preview file not found: {file_path}")
            return "檔案不存在", 404
        return await send_from_directory(OUTPUT_FOLDER, filename)
    except Exception as e:
        logger.error(f"Preview error: {e}")
        return "預覽失敗", 500

@clips_bp.route('/about_us')
async def about_us():
    logger.info(f"Accessing about_us route: {request.path}")
    return await render_template('about_us.html')

@clips_bp.route('/privacy')
async def privacy():
    logger.info(f"Accessing privacy route: {request.path}")
    return await render_template('privacy.html')

@app.route('/ads.txt')
async def serve_ads_txt():
    logger.info(f"Serving ads.txt from static/ads.txt")
    return await send_from_directory('static', 'ads.txt')

@clips_bp.route('/contact', methods=['GET', 'POST'])
async def contact():
    logger.info(f"Accessing contact route: {request.path}")
    if request.method == 'GET':
        return await render_template('contact.html',
                                   RECAPTCHA_CONFIG=RECAPTCHA_CONFIG)
    try:
        form = await request.form
        if form.get('website'):
            logger.warning("Honeypot field filled, likely spam")
            return await render_template('contact.html',
                                       error='提交失敗，請重新嘗試',
                                       RECAPTCHA_CONFIG=RECAPTCHA_CONFIG)
        recaptcha_response = form.get('g-recaptcha-response')
        if not recaptcha_response:
            return await render_template('contact.html',
                                       error='請完成人機驗證',
                                       RECAPTCHA_CONFIG=RECAPTCHA_CONFIG)
        if not await verify_recaptcha(recaptcha_response):
            return await render_template('contact.html',
                                       error='人機驗證失敗，請重新嘗試',
                                       RECAPTCHA_CONFIG=RECAPTCHA_CONFIG)
        name = form.get('name', '').strip()
        email = form.get('email', '').strip()
        subject = form.get('subject', '').strip()
        message = form.get('message', '').strip()
        privacy = form.get('privacy')
        if not all([name, email, subject, message, privacy]):
            return await render_template('contact.html',
                                       error='請填寫所有必填欄位並同意隱私權政策',
                                       RECAPTCHA_CONFIG=RECAPTCHA_CONFIG)
        spam_keywords = ['viagra', 'casino', 'lottery', 'winner', 'click here', 'free money']
        message_lower = message.lower()
        if any(keyword in message_lower for keyword in spam_keywords):
            logger.warning(f"Spam keyword detected in message from {email}")
            return await render_template('contact.html',
                                       error='訊息內容包含不當內容，請重新撰寫',
                                       RECAPTCHA_CONFIG=RECAPTCHA_CONFIG)
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return await render_template('contact.html',
                                       error='請輸入有效的電子郵件地址',
                                       RECAPTCHA_CONFIG=RECAPTCHA_CONFIG)
        if len(message) > 2000:
            return await render_template('contact.html',
                                       error='訊息內容過長，請控制在 2000 字以內',
                                       RECAPTCHA_CONFIG=RECAPTCHA_CONFIG)
        success = await send_contact_email(name, email, subject, message)
        logger.debug(f"Email sending result: {success}")
        if success:
            logger.info(f"Contact form submitted successfully by {name} ({email})")
            return await render_template('contact.html',
                                       success=True,
                                       RECAPTCHA_CONFIG=RECAPTCHA_CONFIG)
        else:
            logger.warning(f"Failed to send email for contact form from {email}")
            return await render_template('contact.html',
                                       error='郵件發送失敗，請稍後再試',
                                       RECAPTCHA_CONFIG=RECAPTCHA_CONFIG)
    except Exception as e:
        logger.error(f"Contact form error: {str(e)}", exc_info=True)
        return await render_template('contact.html',
                                   error='系統發生錯誤，請稍後再試',
                                   RECAPTCHA_CONFIG=RECAPTCHA_CONFIG)

@app.errorhandler(413)
async def request_entity_too_large(error):
    return await render_template('upload.html',
                               error='上傳檔案總大小超過限制，請確保所有檔案總大小不超過 2GB'), 413

@app.errorhandler(408)
async def request_timeout(error):
    return await render_template('upload.html',
                               error='上傳超時，請檢查網路連線或減少檔案大小'), 408

@app.errorhandler(BuildError)
async def handle_build_error(error):
    logger.error(f"URL build error: {str(error)}")
    return await render_template('error.html',
                               error=f'無法生成 URL：{str(error)}'), 500

# Register Blueprint
app.register_blueprint(clips_bp)

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', '0') == '1'
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', '8282'))
    logger.info(f"Starting TSClips on {host}:{port} (debug={debug_mode})")
    app.run(host=host, debug=debug_mode, port=port, use_reloader=debug_mode)
