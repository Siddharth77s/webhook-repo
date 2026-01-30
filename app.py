from flask import Flask, render_template, request, jsonify, Response
from pymongo import MongoClient
from datetime import datetime
import json
import os
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB configuration - SIMPLIFIED
MONGO_URI = "mongodb+srv://siddharth:siddharth@cluster0.s5vmk2i.mongodb.net/github_events?retryWrites=true&w=majority&appName=Cluster0"

# Global variables
client = None
events_collection = None

def init_mongodb():
    """Initialize MongoDB connection"""
    global client, events_collection
    
    try:
        logger.info("🔄 Attempting MongoDB connection...")
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        
        # Test the connection
        client.admin.command('ping')
        logger.info("✅ MongoDB ping successful!")
        
        # Get database and collection
        db = client.github_events
        events_collection = db.events
        
        # Create index if not exists
        events_collection.create_index([("timestamp", -1)])
        
        logger.info(f"📊 MongoDB initialized. Database: github_events, Collection: events")
        return True
        
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")
        logger.error(f"Connection string: {MONGO_URI[:50]}...")
        client = None
        events_collection = None
        return False

# Initialize on startup
init_mongodb()

def format_timestamp(timestamp_str):
    """Format timestamp to readable format"""
    try:
        if not timestamp_str:
            return "Just now"
            
        # Handle ISO format
        if 'T' in timestamp_str:
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        
        # Format with ordinal suffix
        day = dt.day
        if 4 <= day <= 20 or 24 <= day <= 30:
            suffix = "th"
        else:
            suffix = ["st", "nd", "rd"][day % 10 - 1]
        
        return dt.strftime(f"%d{suffix} %B %Y - %I:%M %p UTC")
    except Exception:
        return timestamp_str

@app.route('/')
def index():
    """Render the main UI page"""
    return render_template('index.html')

@app.route('/webhook', methods=['POST'])
def webhook():
    """Endpoint to receive GitHub webhooks"""
    if request.headers.get('Content-Type') != 'application/json':
        return jsonify({'error': 'Invalid content type'}), 400
    
    try:
        payload = request.json
        event_type = request.headers.get('X-GitHub-Event')
        
        logger.info(f"📥 Received {event_type} event")
        
        # Parse based on event type
        timestamp = datetime.utcnow().isoformat()
        formatted_time = format_timestamp(timestamp)
        
        if event_type == 'push':
            author = payload.get('pusher', {}).get('name', 'Unknown') or \
                    payload.get('sender', {}).get('login', 'Unknown')
            to_branch = payload.get('ref', '').replace('refs/heads/', 'main')
            
            event_data = {
                'action': 'PUSH',
                'author': author,
                'to_branch': to_branch,
                'timestamp': timestamp,
                'formatted_time': formatted_time,
                'message': f'{author} pushed to {to_branch} on {formatted_time}'
            }
            
        elif event_type == 'pull_request':
            pr = payload.get('pull_request', {})
            action = payload.get('action')
            
            if action == 'opened':
                author = pr.get('user', {}).get('login', 'Unknown')
                from_branch = pr.get('head', {}).get('ref', 'feature')
                to_branch = pr.get('base', {}).get('ref', 'main')
                
                event_data = {
                    'action': 'PULL_REQUEST',
                    'author': author,
                    'from_branch': from_branch,
                    'to_branch': to_branch,
                    'timestamp': timestamp,
                    'formatted_time': formatted_time,
                    'message': f'{author} submitted a pull request from {from_branch} to {to_branch} on {formatted_time}'
                }
            elif action == 'closed' and pr.get('merged', False):
                author = pr.get('merged_by', {}).get('login', 'Unknown') or \
                        payload.get('sender', {}).get('login', 'Unknown')
                from_branch = pr.get('head', {}).get('ref', 'feature')
                to_branch = pr.get('base', {}).get('ref', 'main')
                
                event_data = {
                    'action': 'MERGE',
                    'author': author,
                    'from_branch': from_branch,
                    'to_branch': to_branch,
                    'timestamp': timestamp,
                    'formatted_time': formatted_time,
                    'message': f'{author} merged branch {from_branch} to {to_branch} on {formatted_time}'
                }
            else:
                return jsonify({'status': 'ignored'}), 200
        else:
            return jsonify({'status': 'ignored'}), 200
        
        # Store in MongoDB if connected
        if events_collection is not None:
            events_collection.insert_one(event_data)
            logger.info(f"✅ Stored {event_data['action']} by {event_data['author']}")
        else:
            logger.warning("⚠️ MongoDB not connected, event not stored")
        
        return jsonify({'status': 'success'}), 200
        
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/events')
def get_events():
    """API endpoint to fetch events for the UI"""
    try:
        if events_collection is None:
            # Try to reconnect
            if init_mongodb() and events_collection is not None:
                logger.info("✅ Reconnected to MongoDB")
            else:
                return jsonify([]), 200  # Return empty array instead of error
        
        # Get events
        cursor = events_collection.find({}, {'_id': 0}).sort('timestamp', -1).limit(50)
        events = list(cursor)
        
        # Ensure all events have required fields
        for event in events:
            if 'message' not in event:
                event['message'] = f"{event.get('author', 'Someone')} {event.get('action', 'did something')}"
        
        return jsonify(events)
        
    except Exception as e:
        logger.error(f"❌ Error fetching events: {e}")
        return jsonify([]), 200  # Return empty on error

@app.route('/test-mongo')
def test_mongo():
    """Test MongoDB connection"""
    if init_mongodb():
        count = events_collection.count_documents({}) if events_collection else 0
        return f"""
        <h1>✅ MongoDB Connection Test</h1>
        <p><b>Status:</b> Connected</p>
        <p><b>Events in DB:</b> {count}</p>
        <p><b>Connection:</b> {MONGO_URI[:60]}...</p>
        <p><a href="/">Go to Dashboard</a> | <a href="/api/events">View API</a></p>
        """
    else:
        return f"""
        <h1>❌ MongoDB Connection Failed</h1>
        <p>Please check:</p>
        <ol>
            <li>MongoDB Atlas → Network Access → Add IP 0.0.0.0/0</li>
            <li>Check username/password in connection string</li>
            <li>Wait 2-3 minutes after creating cluster</li>
        </ol>
        <p><b>Connection string:</b> {MONGO_URI}</p>
        """

@app.route('/health')
def health():
    """Health check endpoint"""
    is_connected = events_collection is not None
    count = events_collection.count_documents({}) if is_connected else 0
    return jsonify({
        'status': 'ok' if is_connected else 'degraded',
        'mongodb': 'connected' if is_connected else 'disconnected',
        'event_count': count,
        'timestamp': datetime.utcnow().isoformat()
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)