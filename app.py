import eventlet
eventlet.monkey_patch()

import os
import re
from flask import Flask, render_template, send_from_directory, jsonify
from flask_socketio import SocketIO
import yt_dlp

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

DOWNLOAD_DIR = os.path.dirname(os.path.abspath(__file__))
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def clean_ansi(text):
    if not text: return 'N/A'
    return ANSI_ESCAPE.sub('', text)

class MyLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): 
        socketio.emit('status_msg', {'msg': f'Error: {msg}', 'type': 'error'})

def progress_hook(d):
    # Base data to prevent "undefined" errors in the UI
    data = {
        'status': d['status'],
        'percentage': '0.0',
        'speed': '---',
        'eta': '---',
        'filename': os.path.basename(d.get('filename', 'Unknown'))
    }

    if d['status'] == 'downloading':
        p = d.get('downloaded_bytes', 0)
        t = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        percent = (p / t) * 100 if t > 0 else 0
        
        data.update({
            'percentage': f"{percent:.1f}",
            'speed': clean_ansi(d.get('_speed_str', 'N/A')).strip(),
            'eta': clean_ansi(d.get('_eta_str', 'N/A')).strip(),
        })
        socketio.emit('progress', data)
    
    elif d['status'] == 'finished':
        data.update({'percentage': '100', 'speed': 'COMPLETE', 'eta': '00:00'})
        socketio.emit('progress', data)
        socketio.emit('refresh_list')

def run_download(url):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'merge_output_format': 'mp4',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'progress_hooks': [progress_hook],
        'logger': MyLogger(),
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Pre-check: Get info to see if file exists
            info = ydl.extract_info(url, download=False)
            expected_file = ydl.prepare_filename(info)
            # yt-dlp might change extension during merge, so we check for the .mp4 version
            final_mp4 = os.path.splitext(expected_file)[0] + ".mp4"

            if os.path.exists(final_mp4):
                socketio.emit('status_msg', {'msg': 'We already have this loot! Check the inventory.', 'type': 'info'})
                socketio.emit('progress', {
                    'status': 'finished', 
                    'percentage': '100', 
                    'speed': 'EXISTS', 
                    'eta': '00:00', 
                    'filename': os.path.basename(final_mp4)
                })
                return

            # If not exists, proceed with download
            ydl.download([url])
            
        socketio.emit('status_msg', {'msg': 'Bite my shiny metal download complete!', 'type': 'success'})
    except Exception as e:
        socketio.emit('status_msg', {'msg': f'Error: {str(e)}', 'type': 'error'})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/bender.jpg')
def background_image():
    return send_from_directory('templates', 'bender.jpg')

@app.route('/files')
def list_files():
    files = [f for f in os.listdir(DOWNLOAD_DIR) 
             if f.endswith('.mp4') 
             and not any(x in f for x in ['.part', '.ytdl', '.temp'])]
    return jsonify(files)

@app.route('/download-file/<filename>')
def download_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)

@app.route('/delete-file/<filename>')
def delete_file(filename):
    path = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(path):
        os.remove(path)
        return jsonify({'status': 'deleted'})
    return jsonify({'status': 'error'}), 404

@socketio.on('start_download')
def handle_download(data):
    url = data.get('url')
    if url:
        socketio.emit('status_msg', {'msg': 'Shut up and take my URL!', 'type': 'info'})
        socketio.start_background_task(run_download, url)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)