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

# MongoDB configuration - USE YOUR CONNECTION STRING
MONGO_URI = os.getenv('MONGODB_URI', 'mongodb+srv://siddharth:siddharth@cluster0.s5vmk2i.mongodb.net/github_events?appName=Cluster0')
DB_NAME = 'github_events'  # Fixed database name

# Initialize MongoDB
try:
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    events_collection = db['events']
    logger.info("✅ Connected to MongoDB successfully!")
    logger.info(f"Database: {DB_NAME}, Collection: events")
except Exception as e:
    logger.error(f"❌ Failed to connect to MongoDB: {str(e)}")
    logger.error(f"Connection string used: {MONGO_URI[:50]}...")
    events_collection = None

def format_timestamp(timestamp_str):
    """Format timestamp to readable format"""
    try:
        # Handle both ISO format and string format
        if 'T' in timestamp_str:
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            dt = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S.%f")
        
        formatted = dt.strftime("%d %B %Y - %I:%M %p UTC")
        
        # Add ordinal suffix to day
        day = dt.day
        if 4 <= day <= 20 or 24 <= day <= 30:
            suffix = "th"
        else:
            suffix = ["st", "nd", "rd"][day % 10 - 1]
        
        return formatted.replace(str(day), f"{day}{suffix}")
    except Exception as e:
        logger.warning(f"Could not format timestamp {timestamp_str}: {e}")
        return timestamp_str

def parse_github_event(payload):
    """Parse GitHub webhook payload and extract relevant data"""
    event_type = request.headers.get('X-GitHub-Event')
    logger.info(f"Received GitHub event: {event_type}")
    
    if event_type == 'push':
        author = payload.get('pusher', {}).get('name', 'Unknown')
        if not author or author == 'Unknown':
            author = payload.get('sender', {}).get('login', 'Unknown')
        
        return {
            'action': 'PUSH',
            'author': author,
            'to_branch': payload.get('ref', '').replace('refs/heads/', ''),
            'timestamp': payload.get('head_commit', {}).get('timestamp', datetime.utcnow().isoformat()),
            'repository': payload.get('repository', {}).get('full_name', 'Unknown'),
            'event_id': payload.get('after', ''),
            'received_at': datetime.utcnow().isoformat()  # Add when we received it
        }
    
    elif event_type == 'pull_request':
        pr_action = payload.get('action')
        if pr_action == 'opened' or pr_action == 'reopened':
            return {
                'action': 'PULL_REQUEST',
                'author': payload.get('pull_request', {}).get('user', {}).get('login', 'Unknown'),
                'from_branch': payload.get('pull_request', {}).get('head', {}).get('ref', ''),
                'to_branch': payload.get('pull_request', {}).get('base', {}).get('ref', ''),
                'timestamp': payload.get('pull_request', {}).get('created_at', datetime.utcnow().isoformat()),
                'repository': payload.get('repository', {}).get('full_name', 'Unknown'),
                'event_id': str(payload.get('pull_request', {}).get('id', '')),
                'received_at': datetime.utcnow().isoformat()
            }
        elif pr_action == 'closed' and payload.get('pull_request', {}).get('merged', False):
            return {
                'action': 'MERGE',
                'author': payload.get('pull_request', {}).get('merged_by', {}).get('login', 
                          payload.get('sender', {}).get('login', 'Unknown')),
                'from_branch': payload.get('pull_request', {}).get('head', {}).get('ref', ''),
                'to_branch': payload.get('pull_request', {}).get('base', {}).get('ref', ''),
                'timestamp': payload.get('pull_request', {}).get('merged_at', datetime.utcnow().isoformat()),
                'repository': payload.get('repository', {}).get('full_name', 'Unknown'),
                'event_id': str(payload.get('pull_request', {}).get('id', '')),
                'received_at': datetime.utcnow().isoformat()
            }
    
    return None

@app.route('/webhook', methods=['POST'])
def webhook():
    """Endpoint to receive GitHub webhooks"""
    if request.headers.get('Content-Type') != 'application/json':
        logger.warning("Invalid content type received")
        return jsonify({'error': 'Invalid content type'}), 400
    
    try:
        payload = request.json
        
        # Log minimal info (not entire payload)
        event_type = request.headers.get('X-GitHub-Event')
        repo = payload.get('repository', {}).get('full_name', 'unknown')
        logger.info(f"📥 Webhook received: {event_type} from {repo}")
        
        # Parse the event
        event_data = parse_github_event(payload)
        
        if event_data and events_collection:
            # Store in MongoDB
            result = events_collection.insert_one(event_data)
            logger.info(f"✅ Stored {event_data['action']} by {event_data['author']}. ID: {result.inserted_id}")
            
            return jsonify({'status': 'success', 'event': event_data['action']}), 200
        else:
            logger.info(f"ℹ️ No event data parsed for {event_type}")
            return jsonify({'status': 'ignored'}), 200
            
    except Exception as e:
        logger.error(f"❌ Error processing webhook: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/')
def index():
    """Render the main UI page"""
    return render_template('index.html')

@app.route('/api/events')
def get_events():
    """API endpoint to fetch events for the UI"""
    try:
        if not events_collection:
            logger.error("Database collection not available")
            return jsonify({'error': 'Database not available'}), 500
        
        # Get latest events, sorted by timestamp
        events = list(events_collection.find(
            {}, 
            {'_id': 0}
        ).sort('timestamp', -1).limit(50))
        
        logger.info(f"📊 Returning {len(events)} events to UI")
        
        # Format events for UI
        formatted_events = []
        for event in events:
            formatted_event = {
                'action': event.get('action'),
                'author': event.get('author', 'Unknown'),
                'timestamp': format_timestamp(event.get('timestamp', '')),
                'original_timestamp': event.get('timestamp', '')
            }
            
            if event['action'] == 'PUSH':
                formatted_event['message'] = f'{event["author"]} pushed to {event.get("to_branch", "unknown")} on {format_timestamp(event.get("timestamp", ""))}'
                formatted_event['to_branch'] = event.get('to_branch')
                
            elif event['action'] == 'PULL_REQUEST':
                formatted_event['message'] = f'{event["author"]} submitted a pull request from {event.get("from_branch", "unknown")} to {event.get("to_branch", "unknown")} on {format_timestamp(event.get("timestamp", ""))}'
                formatted_event['from_branch'] = event.get('from_branch')
                formatted_event['to_branch'] = event.get('to_branch')
                
            elif event['action'] == 'MERGE':
                formatted_event['message'] = f'{event["author"]} merged branch {event.get("from_branch", "unknown")} to {event.get("to_branch", "unknown")} on {format_timestamp(event.get("timestamp", ""))}'
                formatted_event['from_branch'] = event.get('from_branch')
                formatted_event['to_branch'] = event.get('to_branch')
            else:
                formatted_event['message'] = f'{event["author"]} performed {event.get("action", "unknown")} action'
            
            formatted_events.append(formatted_event)
        
        return jsonify(formatted_events)
        
    except Exception as e:
        logger.error(f"❌ Error fetching events: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    try:
        mongo_status = "connected" if events_collection else "disconnected"
        event_count = events_collection.count_documents({}) if events_collection else 0
        return jsonify({
            'status': 'ok',
            'mongodb': mongo_status,
            'event_count': event_count,
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/test-db')
def test_db():
    """Test MongoDB connection"""
    if not events_collection:
        return "❌ MongoDB not connected", 500
    
    count = events_collection.count_documents({})
    return f"""
    <h1>✅ MongoDB Test</h1>
    <p><b>Status:</b> Connected</p>
    <p><b>Database:</b> github_events</p>
    <p><b>Collection:</b> events</p>
    <p><b>Total Events:</b> {count}</p>
    <p><b>Connection:</b> {MONGO_URI[:60]}...</p>
    <hr>
    <p><a href="/">Go to Dashboard</a></p>
    """

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting Flask app on port {port}")
    logger.info(f"📦 MongoDB URI: {MONGO_URI[:50]}...")
    app.run(host='0.0.0.0', port=port, debug=False)