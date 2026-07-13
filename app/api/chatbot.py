from flask_restful import Resource
from flask import request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
import requests
import os
import subprocess
import socket
import time
from app.models import UserActivity, ChatHistory, ChatSession, db
import datetime

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except:
            return False

def check_and_start_search_service(search_url):
    try:
        port = int(search_url.split(":")[-1].replace("/", ""))
    except:
        port = 8000

    if not is_port_open(port):
        # Dynamically locate the python interpreter and script relative to this file
        current_dir = os.path.dirname(os.path.abspath(__file__)) # smart_farmasi_backend/app/api
        app_dir = os.path.dirname(current_dir) # smart_farmasi_backend/app
        backend_dir = os.path.dirname(app_dir) # smart_farmasi_backend
        workspace_root = os.path.dirname(backend_dir) # capstone6
        
        chatbot_dir = os.path.join(workspace_root, 'dataset_chatbot', 'buldchtbot')
        venv_python = os.path.join(chatbot_dir, '.venv', 'Scripts', 'python.exe')
        api_script = os.path.join(chatbot_dir, 'scripts', '06_api_server.py')
        
        if os.path.exists(venv_python) and os.path.exists(api_script):
            try:
                subprocess.Popen(
                    [venv_python, api_script, "--port", str(port)],
                    cwd=chatbot_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True
                )
                time.sleep(0.5) # Give it a brief moment to initiate process
                return True, "Starting database search engine..."
            except Exception as e:
                return False, f"Failed to launch database engine: {str(e)}"
        return False, "Database search engine environment not found."
    return True, "Database search engine online."

def retrieve_contexts(query, search_url):
    try:
        response = requests.post(
            f"{search_url}/search",
            json={"query": query, "k": 12, "index_type": "flat"},
            timeout=3.0
        )
        if response.status_code == 200:
            return response.json().get("results", [])
    except Exception as e:
        print(f"Error querying search service: {e}")
    return []

def _build_system_content(contexts):
    # Absolute topic guardrail at the very top of prompt
    guardrail_header = """PENTING: BATASAN TOPIK MUTLAK (WAJIB DIIKUTI SECARA KETAT)
Anda HANYA diperbolehkan menjawab pertanyaan seputar kesehatan, obat-obatan, gejala penyakit, gaya hidup sehat, tips medis, atau fitur aplikasi SEHATI.
Jika pengguna bertanya tentang hal lain di luar topik kesehatan (seperti coding/pemrograman, bahasa komputer, matematika, sejarah, politik umum, resep masakan non-diet, tips teknologi, dll), Anda WAJIB MENOLAK secara sopan dan tegas. 
JANGAN PERNAH memberikan contoh kode program (seperti python, javascript, dll), rumus matematika, atau informasi non-kesehatan lainnya.
Contoh penolakan: "Maaf, saya hanya dapat membantu menjawab pertanyaan seputar kesehatan dan obat-obatan."
"""

    if contexts:
        context_str = ""
        for i, doc in enumerate(contexts):
            context_str += f"\n[Dokumen {i+1}] (Sumber: {doc.get('source', 'Unknown')})\n{doc.get('text', '')}\n"
            
        return f"""Anda adalah Asisten Kesehatan SEHATI (Smart Farmasi) yang ramah dan interaktif! Tugas Anda adalah menjelaskan informasi obat/kesehatan secara RINGKAS, jelas, dan asik bagi orang awam.

{guardrail_header}

Gunakan data obat/kesehatan dari database internal SEHATI berikut jika relevan:
{context_str}

ATURAN RESPON & FORMAT TAMPILAN:
1. Bahasa Ramah & Asik: Gunakan bahasa Indonesia yang santai, bersahabat, ramah (seperti menyapa teman), dan mudah dipahami. Terjemahkan/sederhanakan istilah medis yang rumit.
2. Singkat & Padat: Jawab secara langsung ke inti pertanyaan. Batasi panjang jawaban maksimal 120-180 kata (cukup 2-3 paragraf pendek). Jangan menulis teks panjang yang melelahkan.
3. STRUKTUR & TAMPILAN TANPA BINTANG (NO ASTERISKS):
   - JANGAN PERNAH menggunakan karakter bintang (*) atau ganda (**) untuk membuat teks tebal, miring, atau daftar list di chatbot.
   - JANGAN menggunakan karakter simbol unicode '•' (karena sering kali rusak/menjadi simbol jelek di layar) atau tanda hubung '-' untuk list.
   - Sebagai gantinya, gunakan EMOJI (stiker) yang sesuai di awal baris/poin untuk memetakan informasi secara rapi dan menarik.
4. Format Penjelasan Obat:
   Jika pengguna menanyakan tentang obat tertentu (nama/merk obat), susun penjelasan dengan format emoji berikut secara rapi (tanpa tanda bintang):
   
   💊 GUNA OBAT: (tuliskan kegunaan praktisnya di sini)
   
   ⏱️ DOSIS & ANJURAN USIA: (tuliskan aturan pakai, dosis ringkas, serta batasan/anjuran usia pengguna secara jelas, misalnya untuk dewasa atau anak-anak di atas usia tertentu)
   
   ⚠️ EFEK SAMPING: (tuliskan 1-2 efek samping utama di sini)
   
5. Format Gejala / Rekomendasi / Tips Umum:
    - Jika pengguna menanyakan rekomendasi obat untuk gejala tertentu (seperti batuk, pilek, demam, maag, dll), periksa dokumen database internal SEHATI yang dilampirkan. Jika ada obat yang cocok (seperti Bisolvon Extra untuk batuk berdahak), rekomendasikan obat tersebut secara ramah dan jelaskan kegunaan, dosis/aturan pakai, batasan/anjuran usia (apakah aman untuk anak-anak atau hanya untuk dewasa), serta efek sampingnya menggunakan emoji menarik.
    - Gunakan emoji menarik (seperti 👉, 💊, ⏱️, 👶, ⚠️, 💡, 🩺) sebagai penanda poin untuk memetakan informasi secara bersih, rapi, dan terstruktur.
6. Penanganan Sumber/Konteks:
   - Jika obat tidak ditemukan di database internal SEHATI, jawab bahwa obat tersebut tidak ditemukan di database internal SEHATI.
   - Jika berupa gejala/tips kesehatan umum, Anda boleh menggunakan pengetahuan medis umum yang akurat jika database kurang lengkap.
7. Disclaimer Medis: Selalu akhiri jawaban Anda dengan disclaimer berikut di baris baru (tanpa bintang/simbol jelek):

📌 Catatan: Informasi ini hanya edukasi umum. Selalu konsultasikan dengan dokter atau apoteker sebelum minum obat ya!"""
    else:
        return f"""Anda adalah Asisten Kesehatan SEHATI (Smart Farmasi) yang ramah dan interaktif! Tugas Anda adalah menjelaskan informasi kesehatan umum secara RINGKAS, jelas, dan asik bagi orang awam.

{guardrail_header}

Catatan: Database internal sedang memuat/offline. Jawablah menggunakan pengetahuan medis umum Anda secara singkat dan praktis.

ATURAN RESPON & FORMAT TAMPILAN:
1. Bahasa Ramah & Asik: Gunakan bahasa Indonesia yang santai, bersahabat, ramah (seperti menyapa teman), dan mudah dipahami. Terjemahkan/sederhanakan istilah medis yang rumit.
2. Singkat & Padat: Jawab secara langsung ke inti pertanyaan (maksimal 120-180 kata, cukup 2-3 paragraf pendek).
3. STRUKTUR & TAMPILAN TANPA BINTANG (NO ASTERISKS):
   - JANGAN PERNAH menggunakan karakter bintang (*) atau ganda (**) untuk membuat teks tebal, miring, atau daftar list di chatbot.
   - JANGAN menggunakan karakter simbol unicode '•' (karena sering kali rusak/menjadi simbol jelek di layar) atau tanda hubung '-' untuk list.
   - Sebagai gantinya, gunakan EMOJI (stiker) yang sesuai di awal baris/poin untuk memetakan informasi secara rapi dan menarik.
4. Format Poin: Gunakan emoji menarik (seperti 👉, 💡, 🩺, 💊, ⚠️) sebagai penanda poin untuk memetakan informasi secara bersih dan terstruktur.
5. Disclaimer Medis: Selalu akhiri jawaban Anda dengan disclaimer berikut di baris baru (tanpa bintang/simbol jelek):

📌 Catatan: Informasi ini hanya edukasi umum. Selalu konsultasikan dengan dokter atau apoteker sebelum minum obat ya!"""

def call_openrouter(query, contexts, api_key, model_name):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://sehati-app.com",
        "X-Title": "SEHATI Chatbot"
    }
    system_content = _build_system_content(contexts)
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": query}
        ],
        "temperature": 0.3
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=25.0)
        if response.status_code == 200:
            res_data = response.json()
            choices = res_data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
        else:
            print(f"OpenRouter Error Status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"Error calling OpenRouter: {e}")
    return None

def call_groq(query, contexts, api_key, model_name):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    system_content = _build_system_content(contexts)
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": query}
        ],
        "temperature": 0.3
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=25.0)
        if response.status_code == 200:
            res_data = response.json()
            choices = res_data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
        else:
            print(f"Groq Error Status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"Error calling Groq: {e}")
    return None

def call_gemini_direct(query, contexts, api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    system_content = _build_system_content(contexts)
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{system_content}\n\nPertanyaan Pengguna: {query}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.3
        }
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=25.0)
        if response.status_code == 200:
            res_data = response.json()
            candidates = res_data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    return parts[0].get("text", "").strip()
        else:
            print(f"Gemini API Error Status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"Error calling Gemini: {e}")
    return None

class ChatbotAPI(Resource):
    @jwt_required()
    def post(self):
        try:
            user_id = get_jwt_identity()
            data = request.get_json()
            
            if not data or 'message' not in data:
                return {'message': 'Missing message'}, 400
                
            user_message = data['message']
            
            # 1. Retrieve config values
            api_key = current_app.config.get('OPENROUTER_API_KEY')
            model_name = current_app.config.get('OPENROUTER_MODEL', 'google/gemini-2.5-flash')
            search_url = current_app.config.get('SEARCH_SERVICE_URL', 'http://127.0.0.1:8000')
            gemini_key = current_app.config.get('GEMINI_API_KEY') or os.environ.get('GEMINI_API_KEY')
            groq_key = current_app.config.get('GROQ_API_KEY') or os.environ.get('GROQ_API_KEY')
            groq_model = current_app.config.get('GROQ_MODEL', 'llama-3.3-70b-specdec')
            
            # 2. Check search service & startup if offline
            check_and_start_search_service(search_url)
            
            # 3. Retrieve relevant medical contexts
            contexts = retrieve_contexts(user_message, search_url)
            # Filter out completely unrelated search results (score > 22.0)
            contexts = [c for c in contexts if c.get("score", 99.0) <= 22.0]
            
            # 4. Generate RAG response via multi-provider strategy
            ai_response = None
            
            # Try Groq first (extremely fast & high limits)
            if not ai_response and groq_key:
                print("Trying Groq API...")
                ai_response = call_groq(user_message, contexts, groq_key, groq_model)
                
            # Try OpenRouter second
            if not ai_response and api_key:
                print("Trying OpenRouter API...")
                ai_response = call_openrouter(user_message, contexts, api_key, model_name)
                
            # Try direct Gemini third
            if not ai_response and gemini_key:
                print("Trying direct Gemini API...")
                ai_response = call_gemini_direct(user_message, contexts, gemini_key)
                
            # Final hardcoded fallback if all APIs fail
            if not ai_response:
                ai_response = self._get_fallback_response(user_message)
            
            # 5. Save activity and chat log to database
            activity = UserActivity(
                user_id=int(user_id),
                activity_type='chatbot',
                description=f"User asked: {user_message[:50]}..."
            )
            db.session.add(activity)

            # 6. Handle chat session
            session_id = data.get('session_id')
            chat_session = None
            if session_id:
                chat_session = ChatSession.query.filter_by(
                    id=int(session_id), user_id=int(user_id)
                ).first()

            if not chat_session:
                # Auto-create new session with title from first message
                title = user_message[:50].strip()
                if len(user_message) > 50:
                    title += '...'
                chat_session = ChatSession(
                    user_id=int(user_id),
                    title=title,
                )
                db.session.add(chat_session)
                db.session.flush()  # get ID before commit
            else:
                # Update session updated_at
                chat_session.updated_at = datetime.datetime.utcnow()

            chat_log = ChatHistory(
                user_id=int(user_id),
                session_id=chat_session.id,
                user_message=user_message,
                bot_response=ai_response
            )
            db.session.add(chat_log)
            db.session.commit()

            return {
                'reply': ai_response,
                'session_id': chat_session.id,
                'status': 'success'
            }, 200
        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500

    def _get_fallback_response(self, message):
        return (
            "Maaf, asisten SEHATI sedang mengalami gangguan jaringan saat menghubungi mesin kecerdasan buatan. "
            "Namun, untuk pertanyaan Anda mengenai kesehatan, mohon pastikan:\n"
            "• Membaca aturan pakai pada kemasan obat secara teliti.\n"
            "• Istirahat yang cukup dan minum air putih.\n"
            "• Jika gejala berlanjut lebih dari 3 hari atau terasa parah, segera hubungi dokter atau apoteker terdekat.\n\n"
            "Silakan coba kirimkan kembali pertanyaan Anda beberapa saat lagi."
        )

class ChatHistoryAPI(Resource):
    """GET history for a specific session, DELETE all sessions for current user."""

    @jwt_required()
    def get(self):
        try:
            user_id = get_jwt_identity()
            session_id = request.args.get('session_id')
            if session_id:
                history = ChatHistory.query.filter_by(
                    user_id=int(user_id), session_id=int(session_id)
                ).order_by(ChatHistory.timestamp.asc()).all()
            else:
                history = ChatHistory.query.filter_by(
                    user_id=int(user_id)
                ).order_by(ChatHistory.timestamp.asc()).all()
            return {
                'status': 'success',
                'history': [h.to_dict() for h in history]
            }, 200
        except Exception as e:
            return {'message': f'Internal Server Error: {str(e)}'}, 500

    @jwt_required()
    def delete(self):
        """Delete ALL sessions (and their messages) for the current user."""
        try:
            user_id = get_jwt_identity()
            # Deleting sessions cascades to chat_histories
            ChatSession.query.filter_by(user_id=int(user_id)).delete()
            db.session.commit()
            return {
                'status': 'success',
                'message': 'All chat sessions cleared successfully.'
            }, 200
        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class ChatSessionListAPI(Resource):
    """List all sessions for current user."""

    @jwt_required()
    def get(self):
        try:
            user_id = get_jwt_identity()
            sessions = ChatSession.query.filter_by(user_id=int(user_id)).order_by(
                ChatSession.updated_at.desc()
            ).all()
            return {
                'status': 'success',
                'sessions': [s.to_dict() for s in sessions]
            }, 200
        except Exception as e:
            return {'message': f'Internal Server Error: {str(e)}'}, 500

    @jwt_required()
    def post(self):
        """Create a new blank session."""
        try:
            user_id = get_jwt_identity()
            data = request.get_json() or {}
            title = data.get('title', 'Chat Baru')
            session = ChatSession(
                user_id=int(user_id),
                title=title,
            )
            db.session.add(session)
            db.session.commit()
            return {
                'status': 'success',
                'session': session.to_dict()
            }, 201
        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500


class ChatSessionDetailAPI(Resource):
    """Retrieve or delete a specific session."""

    @jwt_required()
    def get(self, session_id):
        try:
            user_id = get_jwt_identity()
            session = ChatSession.query.filter_by(
                id=int(session_id), user_id=int(user_id)
            ).first()
            if not session:
                return {'message': 'Session not found.'}, 404
            history = ChatHistory.query.filter_by(
                session_id=int(session_id)
            ).order_by(ChatHistory.timestamp.asc()).all()
            return {
                'status': 'success',
                'session': session.to_dict(),
                'history': [h.to_dict() for h in history]
            }, 200
        except Exception as e:
            return {'message': f'Internal Server Error: {str(e)}'}, 500

    @jwt_required()
    def delete(self, session_id):
        try:
            user_id = get_jwt_identity()
            session = ChatSession.query.filter_by(
                id=int(session_id), user_id=int(user_id)
            ).first()
            if not session:
                return {'message': 'Session not found.'}, 404
            db.session.delete(session)
            db.session.commit()
            return {
                'status': 'success',
                'message': 'Session deleted successfully.'
            }, 200
        except Exception as e:
            db.session.rollback()
            return {'message': f'Internal Server Error: {str(e)}'}, 500
