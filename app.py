from flask import Flask, render_template, request, jsonify
from pymongo import MongoClient
from datetime import datetime
import os
import logging
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB Configuration - USE YOUR CONNECTION STRING
MONGO_URI = os.getenv('MONGODB_URI', 'mongodb+srv://siddharth:siddharth@cluster0.s5vmk2i.mongodb.net/github_events?retryWrites=true&w=majority&appName=Cluster0')

# Global MongoDB variables
client = None
db = None
events_collection = None

def init_mongodb():
    """Initialize MongoDB connection with retry logic"""
    global client, db, events_collection
    
    try:
        logger.info("🔄 Connecting to MongoDB...")
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
        
        # Test connection
        client.admin.command('ping')
        logger.info("✅ MongoDB connection successful!")
        
        # Get database and collection
        db = client.github_events
        events_collection = db.events
        
        # Create index for faster queries
        events_collection.create_index([("timestamp", -1)])
        events_collection.create_index([("action", 1)])
        
        logger.info(f"📊 Database: github_events, Collection: events")
        return True
        
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {str(e)}")
        client = None
        db = None
        events_collection = None
        return False

# Initialize MongoDB on startup
init_mongodb()

def format_timestamp(timestamp_str):
    """Format ISO timestamp to human readable format"""
    try:
        if not timestamp_str:
            return "Just now"
        
        # Clean the timestamp string
        if 'Z' in timestamp_str:
            timestamp_str = timestamp_str.replace('Z', '+00:00')
        
        # Parse the timestamp
        dt = datetime.fromisoformat(timestamp_str)
        
        # Add ordinal suffix to day
        day = dt.day
        if 4 <= day <= 20 or 24 <= day <= 30:
            suffix = "th"
        else:
            suffix = ["st", "nd", "rd"][day % 10 - 1]
        
        # Format the date
        formatted = dt.strftime(f"%d{suffix} %B %Y - %I:%M %p UTC")
        return formatted
        
    except Exception as e:
        logger.warning(f"Could not format timestamp '{timestamp_str}': {e}")
        return timestamp_str

@app.route('/')
def index():
    """Main UI page"""
    return render_template('index.html')

@app.route('/webhook', methods=['POST'])
def webhook():
    """Receive GitHub webhooks and store in MongoDB"""
    # Log the incoming request
    logger.info("=" * 50)
    logger.info("📥 NEW WEBHOOK RECEIVED")
    
    try:
        # Get event type from headers
        event_type = request.headers.get('X-GitHub-Event', 'unknown')
        delivery_id = request.headers.get('X-GitHub-Delivery', 'unknown')
        
        logger.info(f"Event Type: {event_type}")
        logger.info(f"Delivery ID: {delivery_id}")
        
        # Parse JSON payload
        payload = request.json
        
        # Log repository info
        repo_name = payload.get('repository', {}).get('full_name', 'unknown')
        logger.info(f"Repository: {repo_name}")
        
        # Process based on event type
        event_data = None
        timestamp = datetime.utcnow().isoformat()
        
        if event_type == 'push':
            # PUSH EVENT
            author = 'Unknown'
            # Try multiple places for author name
            if payload.get('pusher') and payload['pusher'].get('name'):
                author = payload['pusher']['name']
            elif payload.get('sender') and payload['sender'].get('login'):
                author = payload['sender']['login']
            
            # Get branch name
            ref = payload.get('ref', '')
            to_branch = ref.replace('refs/heads/', '') if ref.startswith('refs/heads/') else ref
            
            # Get commit count
            commits = payload.get('commits', [])
            commit_count = len(commits)
            
            # Get timestamp from head commit if available
            if payload.get('head_commit') and payload['head_commit'].get('timestamp'):
                timestamp = payload['head_commit']['timestamp']
            
            event_data = {
                'action': 'PUSH',
                'author': author,
                'to_branch': to_branch,
                'timestamp': timestamp,
                'repository': repo_name,
                'commit_count': commit_count,
                'event_type': event_type,
                'delivery_id': delivery_id,
                'received_at': datetime.utcnow().isoformat(),
                'display_message': f'{author} pushed to {to_branch}'
            }
            
            logger.info(f"📝 Push event: {author} pushed {commit_count} commit(s) to {to_branch}")
        
        elif event_type == 'pull_request':
            # PULL REQUEST EVENT
            pr_data = payload.get('pull_request', {})
            action = payload.get('action', 'unknown')
            
            if action in ['opened', 'reopened']:
                # PULL REQUEST OPENED
                author = pr_data.get('user', {}).get('login', 'Unknown')
                from_branch = pr_data.get('head', {}).get('ref', 'feature')
                to_branch = pr_data.get('base', {}).get('ref', 'main')
                pr_number = pr_data.get('number', '?')
                pr_title = pr_data.get('title', 'No title')
                
                # Use PR creation time
                if pr_data.get('created_at'):
                    timestamp = pr_data['created_at']
                
                event_data = {
                    'action': 'PULL_REQUEST',
                    'author': author,
                    'from_branch': from_branch,
                    'to_branch': to_branch,
                    'timestamp': timestamp,
                    'repository': repo_name,
                    'pr_number': pr_number,
                    'pr_title': pr_title,
                    'event_type': event_type,
                    'delivery_id': delivery_id,
                    'received_at': datetime.utcnow().isoformat(),
                    'display_message': f'{author} submitted pull request #{pr_number} from {from_branch} to {to_branch}'
                }
                
                logger.info(f"🔀 PR opened: #{pr_number} by {author} ({from_branch} → {to_branch})")
            
            elif action == 'closed':
                # PULL REQUEST CLOSED (might be merged)
                is_merged = pr_data.get('merged', False)
                
                if is_merged:
                    # MERGE EVENT
                    author = pr_data.get('merged_by', {}).get('login', 'Unknown')
                    if author == 'Unknown':
                        author = payload.get('sender', {}).get('login', 'Unknown')
                    
                    from_branch = pr_data.get('head', {}).get('ref', 'feature')
                    to_branch = pr_data.get('base', {}).get('ref', 'main')
                    pr_number = pr_data.get('number', '?')
                    
                    # Use merge time
                    if pr_data.get('merged_at'):
                        timestamp = pr_data['merged_at']
                    
                    event_data = {
                        'action': 'MERGE',
                        'author': author,
                        'from_branch': from_branch,
                        'to_branch': to_branch,
                        'timestamp': timestamp,
                        'repository': repo_name,
                        'pr_number': pr_number,
                        'event_type': event_type,
                        'delivery_id': delivery_id,
                        'received_at': datetime.utcnow().isoformat(),
                        'display_message': f'{author} merged pull request #{pr_number} from {from_branch} to {to_branch}'
                    }
                    
                    logger.info(f"✅ PR merged: #{pr_number} by {author}")
                else:
                    # PR closed without merge
                    logger.info(f"❌ PR closed (not merged): #{pr_data.get('number', '?')}")
        
        elif event_type == 'ping':
            # GitHub webhook test ping
            logger.info("🏓 Received ping from GitHub (webhook test)")
            return jsonify({
                'status': 'success',
                'message': 'Webhook is working!',
                'event': 'ping'
            }), 200
        
        else:
            # Other events (issues, comments, etc.)
            logger.info(f"ℹ️ Other event: {event_type}")
            author = payload.get('sender', {}).get('login', 'Unknown')
            
            event_data = {
                'action': event_type.upper(),
                'author': author,
                'timestamp': timestamp,
                'repository': repo_name,
                'event_type': event_type,
                'delivery_id': delivery_id,
                'received_at': datetime.utcnow().isoformat(),
                'display_message': f'{author} triggered {event_type} event'
            }
        
        # Store in MongoDB if we have data
        if event_data and events_collection is not None:
            try:
                result = events_collection.insert_one(event_data)
                logger.info(f"💾 Stored in MongoDB with ID: {result.inserted_id}")
                
                # Return success
                return jsonify({
                    'status': 'success',
                    'event': event_data['action'],
                    'stored': True,
                    'message': f"Stored {event_data['action']} event"
                }), 200
                
            except Exception as e:
                logger.error(f"❌ Failed to store in MongoDB: {str(e)}")
                return jsonify({
                    'status': 'error',
                    'message': f'Database error: {str(e)}'
                }), 500
        else:
            if events_collection is None:
                logger.warning("⚠️ MongoDB not connected, event not stored")
            return jsonify({
                'status': 'ignored',
                'message': 'Event not processed or MongoDB not available'
            }), 200
            
    except Exception as e:
        logger.error(f"💥 Error processing webhook: {str(e)}")
        logger.error(f"Request headers: {dict(request.headers)}")
        return jsonify({
            'status': 'error',
            'message': f'Processing error: {str(e)}'
        }), 500

@app.route('/api/events')
def get_events():
    """API endpoint for UI to fetch events"""
    try:
        # Reconnect if needed
        if events_collection is None:
            if not init_mongodb():
                return jsonify([]), 200
        
        # Get latest events (most recent first)
        cursor = events_collection.find(
            {},
            {'_id': 0, 'event_type': 0, 'delivery_id': 0, 'received_at': 0}
        ).sort('timestamp', -1).limit(50)
        
        events = list(cursor)
        logger.info(f"📤 Sending {len(events)} events to UI")
        
        # Format for frontend
        formatted_events = []
        for event in events:
            # Create display message
            action = event.get('action', 'UNKNOWN')
            author = event.get('author', 'Unknown')
            timestamp = event.get('timestamp', '')
            formatted_time = format_timestamp(timestamp)
            
            message = event.get('display_message', '')
            if not message:
                # Build message based on action type
                if action == 'PUSH':
                    to_branch = event.get('to_branch', 'branch')
                    commit_count = event.get('commit_count', 0)
                    plural = 's' if commit_count != 1 else ''
                    message = f'{author} pushed {commit_count} commit{plural} to {to_branch}'
                
                elif action == 'PULL_REQUEST':
                    from_branch = event.get('from_branch', 'feature')
                    to_branch = event.get('to_branch', 'main')
                    pr_number = event.get('pr_number', '')
                    pr_title = event.get('pr_title', '')
                    title_part = f': {pr_title}' if pr_title else ''
                    message = f'{author} submitted pull request #{pr_number}{title_part} from {from_branch} to {to_branch}'
                
                elif action == 'MERGE':
                    from_branch = event.get('from_branch', 'feature')
                    to_branch = event.get('to_branch', 'main')
                    pr_number = event.get('pr_number', '')
                    message = f'{author} merged pull request #{pr_number} from {from_branch} to {to_branch}'
                
                else:
                    message = f'{author} performed {action.lower()} action'
            
            formatted_event = {
                'action': action,
                'author': author,
                'timestamp': formatted_time,
                'message': f'{message} on {formatted_time}',
                'original_timestamp': timestamp
            }
            
            # Add branch info if available
            if 'to_branch' in event:
                formatted_event['to_branch'] = event['to_branch']
            if 'from_branch' in event:
                formatted_event['from_branch'] = event['from_branch']
            if 'pr_number' in event:
                formatted_event['pr_number'] = event['pr_number']
            
            formatted_events.append(formatted_event)
        
        return jsonify(formatted_events)
        
    except Exception as e:
        logger.error(f"❌ Error in /api/events: {str(e)}")
        return jsonify([]), 200

@app.route('/health')
def health_check():
    """Health check endpoint"""
    mongo_status = "connected" if events_collection is not None else "disconnected"
    event_count = 0
    
    if events_collection is not None:
        try:
            event_count = events_collection.count_documents({})
        except:
            mongo_status = "error"
    
    return jsonify({
        'status': 'ok',
        'service': 'github-webhook-receiver',
        'mongodb': mongo_status,
        'event_count': event_count,
        'timestamp': datetime.utcnow().isoformat(),
        'endpoints': {
            'webhook': '/webhook (POST)',
            'events': '/api/events (GET)',
            'health': '/health (GET)',
            'cleanup': '/cleanup (GET)',
            'test': '/test-mongo (GET)'
        }
    })

@app.route('/cleanup')
def cleanup():
    """Remove test/old events"""
    try:
        if events_collection is None:
            return "MongoDB not connected", 500
        
        # Delete events older than 7 days or test events
        week_ago = datetime.utcnow().timestamp() - (7 * 24 * 60 * 60)
        week_ago_iso = datetime.fromtimestamp(week_ago).isoformat()
        
        # Delete test events and old events
        result = events_collection.delete_many({
            "$or": [
                {"action": {"$exists": False}},
                {"test": {"$exists": True}},
                {"author": "Unknown"},
                {"timestamp": {"$lt": week_ago_iso}}
            ]
        })
        
        remaining = events_collection.count_documents({})
        
        return jsonify({
            'status': 'success',
            'deleted': result.deleted_count,
            'remaining': remaining,
            'message': f'Deleted {result.deleted_count} events, {remaining} remaining'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/test-mongo')
def test_mongo():
    """Test MongoDB connection page"""
    if init_mongodb() and events_collection is not None:
        count = events_collection.count_documents({})
        
        # Get sample events
        sample_events = list(events_collection.find(
            {},
            {'_id': 0, 'action': 1, 'author': 1, 'timestamp': 1}
        ).limit(5))
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>MongoDB Test</title>
            <style>
                body {{ font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5; }}
                .success {{ color: green; font-weight: bold; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }}
                .event {{ padding: 10px; margin: 5px 0; background: #f0f0f0; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>✅ MongoDB Connection Successful!</h1>
                <p><b>Status:</b> <span class="success">Connected</span></p>
                <p><b>Database:</b> github_events</p>
                <p><b>Collection:</b> events</p>
                <p><b>Total Events:</b> {count}</p>
                <p><b>Connection String:</b> {MONGO_URI[:60]}...</p>
                
                <hr>
                
                <h3>Recent Events ({len(sample_events)}):</h3>
                {"".join([f'<div class="event">{e.get("action", "?")} by {e.get("author", "?")} at {e.get("timestamp", "?")[:19]}</div>' for e in sample_events])}
                
                <hr>
                
                <p>
                    <a href="/">Go to Dashboard</a> | 
                    <a href="/api/events">View API</a> | 
                    <a href="/health">Health Check</a>
                </p>
            </div>
        </body>
        </html>
        """
        return html
    else:
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>MongoDB Test - Failed</title>
            <style>
                body { font-family: Arial, sans-serif; padding: 20px; }
                .error { color: red; font-weight: bold; }
            </style>
        </head>
        <body>
            <h1>❌ MongoDB Connection Failed</h1>
            <p class="error">Please check the following:</p>
            <ol>
                <li>Go to <a href="https://cloud.mongodb.com" target="_blank">MongoDB Atlas</a></li>
                <li>Click "Network Access"</li>
                <li>Add IP address: <code>0.0.0.0/0</code></li>
                <li>Wait 2 minutes</li>
                <li>Check your username/password in connection string</li>
            </ol>
            <p><b>Connection string being used:</b><br>
            <code style="word-break: break-all;">""" + MONGO_URI + """</code></p>
            <hr>
            <p><a href="/">Back to Dashboard</a></p>
        </body>
        </html>
        """, 500

@app.route('/test-webhook', methods=['GET', 'POST'])
def test_webhook_endpoint():
    """Test endpoint to simulate GitHub webhooks"""
    if request.method == 'GET':
        return '''
        <form method="POST">
            <h3>Test Webhook</h3>
            <select name="event_type">
                <option value="push">Push</option>
                <option value="pull_request">Pull Request</option>
                <option value="merge">Merge</option>
                <option value="ping">Ping</option>
            </select><br><br>
            <button type="submit">Send Test Webhook</button>
        </form>
        '''
    else:
        event_type = request.form.get('event_type', 'push')
        
        # Simulate different payloads
        test_payloads = {
            'push': {
                'ref': 'refs/heads/main',
                'pusher': {'name': 'Test User'},
                'sender': {'login': 'testuser'},
                'repository': {'full_name': 'test/repo'},
                'commits': [{'id': 'abc123', 'message': 'Test commit'}],
                'head_commit': {'timestamp': datetime.utcnow().isoformat()}
            },
            'pull_request': {
                'action': 'opened',
                'pull_request': {
                    'number': 1,
                    'title': 'Test PR',
                    'user': {'login': 'testuser'},
                    'head': {'ref': 'feature-branch'},
                    'base': {'ref': 'main'},
                    'created_at': datetime.utcnow().isoformat()
                },
                'repository': {'full_name': 'test/repo'},
                'sender': {'login': 'testuser'}
            },
            'merge': {
                'action': 'closed',
                'pull_request': {
                    'number': 1,
                    'merged': True,
                    'merged_by': {'login': 'testuser'},
                    'head': {'ref': 'feature-branch'},
                    'base': {'ref': 'main'},
                    'merged_at': datetime.utcnow().isoformat()
                },
                'repository': {'full_name': 'test/repo'},
                'sender': {'login': 'testuser'}
            },
            'ping': {'zen': 'Testing', 'hook_id': 123}
        }
        
        # Create a test request
        from flask import Request
        test_request = Request.from_values(
            method='POST',
            content_type='application/json',
            headers={'X-GitHub-Event': event_type},
            data=json.dumps(test_payloads.get(event_type, {}))
        )
        
        # Store directly for testing
        if events_collection is not None:
            events_collection.insert_one({
                'action': event_type.upper(),
                'author': 'Test User',
                'timestamp': datetime.utcnow().isoformat(),
                'repository': 'test/repo',
                'display_message': f'Test {event_type} event from web interface',
                'test': True
            })
        
        return f'''
        <h3>✅ Test {event_type} webhook sent!</h3>
        <p>Check the <a href="/">dashboard</a> to see the event.</p>
        <p><a href="/test-webhook">Send another test</a></p>
        '''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting GitHub Webhook Receiver on port {port}")
    logger.info(f"📦 MongoDB URI: {MONGO_URI[:50]}...")
    logger.info(f"🌐 Webhook URL: http://localhost:{port}/webhook")
    logger.info(f"📊 Dashboard: http://localhost:{port}/")
    app.run(host='0.0.0.0', port=port, debug=False)