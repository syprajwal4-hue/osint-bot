from flask import Flask, render_template, request, jsonify
import aiohttp
import asyncio
import re
import logging
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ===================== CONFIG =====================
API_URL = "https://api.b77bf911.workers.dev/mobile?number="
DAILY_LIMIT = 5
# =================================================

# In-memory storage (use database in production)
user_queries = {}

def get_today_count(user_ip):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return user_queries.get(user_ip, {}).get(today, 0)

def increment_count(user_ip):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if user_ip not in user_queries:
        user_queries[user_ip] = {}
    user_queries[user_ip][today] = get_today_count(user_ip) + 1

async def fetch_number(phone: str):
    if not re.match(r'^[6-9]\d{9}$', phone):
        return None, "Invalid number! Use 10-digit Indian mobile."
    
    url = f"{API_URL}{phone}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
                logging.info("Requested URL %s, status %s", url, r.status)
                if r.status != 200:
                    return None, f"API error (status {r.status}). Try again later."
                
                result = await r.json()

                # API sometimes returns nested structure: {"data": {"data": [ ... ] } }
                data_field = result.get("data")
                records = None

                if isinstance(data_field, dict) and isinstance(data_field.get("data"), list):
                    records = data_field.get("data")
                elif isinstance(data_field, list):
                    records = data_field
                elif data_field is None and isinstance(result.get("results"), list):
                    records = result.get("results")

                if not records:
                    return None, f"No info found for +91{phone}"

                return records[:5], None
    except asyncio.TimeoutError:
        return None, "Request timeout. API not responding."
    except aiohttp.ClientError as e:
        return None, "Network error. Check your connection."
    except Exception as e:
        logging.exception("Error fetching: %s", str(e))
        return None, "API error occurred. Try again later."

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    try:
        data = request.get_json()
        phone = data.get('phone', '').strip().replace(' ', '').replace('+91', '')
        user_ip = request.remote_addr
        
        # Check daily limit
        if get_today_count(user_ip) >= DAILY_LIMIT:
            return jsonify({
                'success': False,
                'error': f'Daily limit reached ({DAILY_LIMIT} queries/day). Try tomorrow!'
            }), 429

        # Validate phone
        if not re.match(r'^\d{10}$', phone):
            return jsonify({
                'success': False,
                'error': 'Invalid! Enter 10-digit number (6-9 start)'
            }), 400

        # Fetch async
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        records, error = loop.run_until_complete(fetch_number(phone))
        loop.close()

        if error or not records:
            return jsonify({
                'success': False,
                'error': error or 'No records found'
            }), 400

        increment_count(user_ip)
        
        # Format response
        formatted = []
        for r in records:
            formatted.append({
                'mobile': r.get('mobile'),
                'name': r.get('name', 'N/A'),
                'father': r.get('fname', 'N/A'),
                'address': r.get('address', 'N/A'),
                'alt_number': r.get('alt', 'N/A'),
                'carrier': r.get('circle', 'N/A'),
                'id': r.get('id', 'N/A')
            })

        return jsonify({
            'success': True,
            'phone': f'+91{phone}',
            'count': len(formatted),
            'records': formatted,
            'remaining': DAILY_LIMIT - get_today_count(user_ip)
        })

    except Exception as e:
        logging.exception("Error in search: %s", str(e))
        return jsonify({
            'success': False,
            'error': 'Server error'
        }), 500

@app.route('/stats', methods=['GET'])
def stats():
    user_ip = request.remote_addr
    used = get_today_count(user_ip)
    return jsonify({
        'used': used,
        'limit': DAILY_LIMIT,
        'remaining': max(0, DAILY_LIMIT - used)
    })

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
