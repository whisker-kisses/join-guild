import httpx
import time
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import json
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from datetime import datetime
import data_pb2
import encode_id_clan_pb2
import reqClan_pb2
import jwt as pyjwt
import os

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes
freefire_version = "OB55"
key = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
iv = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# JWT token generation API - auto-generates tokens for all requests
JWT_API_URL = "https://jwt-server-gilt.vercel.app/token"
JWT_API_UID = "8393911274"
JWT_API_PASSWORD = "7861865AE915176F1BA973EFD8251B2A74484ADD69F37B8114DE59A7E2E9A44C"
JWT_CACHE_TTL = 300  # reuse generated tokens for 5 minutes

_jwt_cache = {"tokens": [], "expires_at": 0}

def get_jwt_tokens_from_api():
    """Generate JWT tokens from the external JWT API endpoint"""
    try:
        params = {"uid": JWT_API_UID, "password": JWT_API_PASSWORD}
        with httpx.Client(timeout=30.0) as client:
            response = client.get(JWT_API_URL, params=params)

        if response.status_code != 200:
            print(f"JWT API error: HTTP {response.status_code}")
            return []

        body = response.text.strip()
        if not body:
            print("JWT API error: empty response")
            return []

        # Try JSON response first
        try:
            json_data = response.json()
            if isinstance(json_data, dict):
                token = json_data.get("token") or json_data.get("jwt") or json_data.get("data") or json_data.get("access_token")
                if token:
                    return [token]
            elif isinstance(json_data, list):
                tokens = [t for t in json_data if t and not str(t).startswith("PASTE_YOUR")]
                if tokens:
                    return tokens
        except Exception:
            pass

        # Fall back to plain-text JWT
        if body.startswith("eyJ"):
            return [body]

        print("JWT API error: unrecognized response format")
        return []
    except Exception as e:
        print(f"JWT API error: {e}")
        return []

def get_jwt_tokens():
    """Get JWT tokens: prefer API-generated tokens, fall back to config.json"""
    now = time.time()
    if _jwt_cache["tokens"] and now < _jwt_cache["expires_at"]:
        return _jwt_cache["tokens"]

    tokens = get_jwt_tokens_from_api()
    if tokens:
        _jwt_cache["tokens"] = tokens
        _jwt_cache["expires_at"] = now + JWT_CACHE_TTL
        return tokens

    return get_jwt_tokens_from_config()

def get_jwt_tokens_from_config():
    """Load all JWT tokens from config.json file"""
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
        tokens = config.get("jwt_tokens", [])
        valid_tokens = [t for t in tokens if t and not t.startswith("PASTE_YOUR")]
        if not valid_tokens:
            print("WARNING: No valid JWT tokens found in config.json")
        return valid_tokens
    except FileNotFoundError:
        print(f"ERROR: config.json not found at {CONFIG_FILE}")
        return []
    except Exception as e:
        print(f"ERROR loading config.json: {e}")
        return []
                  
def get_region_from_jwt(jwt_token):
    try:
        decoded = pyjwt.decode(jwt_token, options={"verify_signature": False})
        lock_region = decoded.get('lock_region', 'BD')
        return lock_region.upper()
    except Exception as e:
        print(f"Region decode error: {e}")
        return 'BD'

def get_region_url(region):
    region = region.upper()
    if region == "IND":
        return "https://client.ind.freefiremobile.com"
    elif region in ["BR", "US", "SAC", "NA"]:
        return "https://client.us.freefiremobile.com/"
    else:
        return "https://clientbp.ppmainecoonghj.com/"

def create_join_payload(clan_id):
    message = reqClan_pb2.MyMessage()
    message.field_1 = int(clan_id)
    serialized_data = message.SerializeToString()
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted_data = cipher.encrypt(pad(serialized_data, AES.block_size))
    return encrypted_data

def create_leave_payload():
    """Create payload for leaving clan - empty encrypted payload"""
    message = reqClan_pb2.MyMessage()
    serialized_data = message.SerializeToString()
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted_data = cipher.encrypt(pad(serialized_data, AES.block_size))
    return encrypted_data

def get_clan_info(base_url, jwt_token, clan_id):
    try:
        json_data = json.dumps({"1": int(clan_id), "2": 1})
        my_data = encode_id_clan_pb2.MyData()
        json_obj = json.loads(json_data)
        my_data.field1 = json_obj["1"]
        my_data.field2 = json_obj["2"]

        data_bytes = my_data.SerializeToString()
        cipher = AES.new(key, AES.MODE_CBC, iv)
        encrypted_info_data = cipher.encrypt(pad(data_bytes, 16))

        info_url = f"https://clientbp.ppmainecoonghj.com/GetClanInfoByClanID"
        
        headers = {
            "Expect": "100-continue",
            "Authorization": f"Bearer {jwt_token}",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": freefire_version,
            "Content-Type": "application/octet-stream",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 11; SM-A305F Build/RP1A.200720.012)",
            "Host": f"{base_url.replace('https://', '').replace('http://', '')}",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip"
        }

        with httpx.Client(timeout=30.0) as client_info:
            info_response = client_info.post(info_url, headers=headers, content=encrypted_info_data)

        print(f"[DEBUG] GetClanInfoByClanID → {info_url} status={info_response.status_code}")
        print(f"[DEBUG] GetClanInfoByClanID raw body: {info_response.content.hex()}")

        if info_response.status_code == 200:
            resp_info = data_pb2.response()
            resp_info.ParseFromString(info_response.content)
            return {
                "clan_name": getattr(resp_info, "special_code", b"").decode("utf-8", errors="ignore"),
                "clan_level": getattr(resp_info, "level", 0)
            }
        else:
            return {"clan_name": "Unknown", "clan_level": "Unknown"}
    except Exception as e:
        print(f"Clan info error: {e}")
        return {"clan_name": "Unknown", "clan_level": "Unknown"}

HTML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guild_manager.html")

# Read HTML content at startup for Vercel compatibility
try:
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        DASHBOARD_HTML = f.read()
except Exception:
    DASHBOARD_HTML = "<h1>Guild Manager Dashboard</h1>"

@app.route('/')
def index():
    """Redirect to the dashboard"""
    return redirect("/dashboard")

@app.route('/dashboard')
def dashboard():
    """Serve the guild manager HTML interface"""
    return DASHBOARD_HTML

@app.route('/joinclan')
def joinclan_alias():
    """Alias for /join so vercel.app/joinclan works too"""
    return join_clan()

@app.route('/join', methods=['GET'])
def join_clan():
    clan_id = request.args.get('clan_id')

    if not clan_id:
        return jsonify({
            "error": "clan_id is required"
        }), 400

    tokens = get_jwt_tokens()
    if not tokens:
        return jsonify({
            "error": "No valid JWT tokens could be generated. Check the JWT API endpoint."
        }), 400

    results = []
    for i, token in enumerate(tokens, 1):
        token_label = f"Token #{i}"
        final_region = get_region_from_jwt(token)
        try:
            base_url = get_region_url(final_region)
            url = f"https://clientbp.ppmainecoonghj.com/RequestJoinClan"
            host = "clientbp.ppmainecoonghj.com"

            encrypted_data = create_join_payload(clan_id)

            headers = {
                "Expect": "100-continue",
                "Authorization": f"Bearer {token}",
                "X-Unity-Version": "2018.4.11f1",
                "X-GA": "v1 1",
                "ReleaseVersion": freefire_version,
                "Content-Type": "application/octet-stream",
                "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 11; SM-A305F Build/RP1A.200720.012)",
                "Host": host,
                "Connection": "Keep-Alive",
                "Accept-Encoding": "gzip"
            }

            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, headers=headers, content=encrypted_data)

            print(f"[DEBUG] RequestJoinClan → {url} status={response.status_code}")
            print(f"[DEBUG] RequestJoinClan raw body: {response.content.hex()}")

            clan_info = get_clan_info("https://clientbp.ppmainecoonghj.com", token, clan_id)

            error_details = None
            try:
                if response.content:
                    error_details = response.content.hex()[:200]
            except:
                pass

            if response.status_code == 200:
                results.append({
                    "token": token_label,
                    "clan_id": clan_id,
                    "region": final_region,
                    "clan_name": clan_info.get("clan_name", "Unknown"),
                    "clan_level": clan_info.get("clan_level", "Unknown"),
                    "message": "Request sent successfully",
                    "status_code": response.status_code,
                    "success": True
                })
            else:
                results.append({
                    "token": token_label,
                    "clan_id": clan_id,
                    "region": final_region,
                    "clan_name": clan_info.get("clan_name", "Unknown"),
                    "message": f"Failed with status {response.status_code}",
                    "status_code": response.status_code,
                    "response_body": error_details,
                    "success": False
                })

        except Exception as e:
            results.append({
                "token": token_label,
                "clan_id": clan_id,
                "error": str(e),
                "success": False
            })

    return jsonify({
        "clan_id": clan_id,
        "total_tokens": len(tokens),
        "successful": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "results": results,
        "timestamp": time.time()
    })

@app.route('/search', methods=['GET'])
def search_clan():
    """Search for clan information by clan ID"""
    clan_id = request.args.get('clan_id')

    if not clan_id:
        return jsonify({
            "error": "clan_id is required"
        }), 400

    tokens = get_jwt_tokens()
    if not tokens:
        return jsonify({
            "error": "No valid JWT tokens could be generated. Check the JWT API endpoint."
        }), 400

    # Use first token for search (only need one to look up clan info)
    final_token = tokens[0]
    final_region = get_region_from_jwt(final_token)

    try:
        base_url = get_region_url(final_region)
        clan_info = get_clan_info(base_url, final_token, clan_id)
        
        return jsonify({
            "clan_id": clan_id,
            "region": final_region,
            "clan_name": clan_info.get("clan_name", "Unknown"),
            "clan_level": clan_info.get("clan_level", "Unknown"),
            "success": True,
            "timestamp": time.time()
        })

    except Exception as e:
        return jsonify({
            "error": "Server error",
            "details": str(e)
        }), 500

@app.route('/leave', methods=['GET'])
def leave_clan():
    """Leave current clan - all tokens leave"""
    tokens = get_jwt_tokens()
    if not tokens:
        return jsonify({
            "error": "No valid JWT tokens could be generated. Check the JWT API endpoint."
        }), 400

    results = []
    for i, token in enumerate(tokens, 1):
        token_label = f"Token #{i}"
        final_region = get_region_from_jwt(token)
        try:
            url = "https://clientbp.ppmainecoonghj.com/QuitClan"
            host = "clientbp.ppmainecoonghj.com"

            encrypted_data = create_leave_payload()

            headers = {
                "Expect": "100-continue",
                "Authorization": f"Bearer {token}",
                "X-Unity-Version": "2018.4.11f1",
                "X-GA": "v1 1",
                "ReleaseVersion": freefire_version,
                "Content-Type": "application/octet-stream",
                "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 11; SM-A305F Build/RP1A.200720.012)",
                "Host": host,
                "Connection": "Keep-Alive",
                "Accept-Encoding": "gzip"
            }

            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, headers=headers, content=encrypted_data)

            print(f"[DEBUG] QuitClan → {url} status={response.status_code}")
            print(f"[DEBUG] QuitClan raw body: {response.content.hex()}")

            error_details = None
            try:
                if response.content:
                    error_details = response.content.hex()[:200]
            except:
                pass

            if response.status_code == 200:
                results.append({
                    "token": token_label,
                    "region": final_region,
                    "message": "Successfully left the clan",
                    "status_code": response.status_code,
                    "success": True
                })
            else:
                results.append({
                    "token": token_label,
                    "region": final_region,
                    "message": f"Failed to leave clan with status {response.status_code}",
                    "status_code": response.status_code,
                    "response_body": error_details,
                    "success": False
                })

        except Exception as e:
            results.append({
                "token": token_label,
                "error": str(e),
                "success": False
            })

    return jsonify({
        "total_tokens": len(tokens),
        "successful": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "results": results,
        "timestamp": time.time()
    })

if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"Starting Clan Join API on port {port} ...")
    app.run(host='0.0.0.0', port=port, debug=False)