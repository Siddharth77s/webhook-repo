from pymongo import MongoClient

# YOUR connection string
MONGO_URI = "mongodb+srv://siddharth:siddharth@cluster0.s5vmk2i.mongodb.net/github_events?appName=Cluster0"

print("🔍 Testing your MongoDB connection...")

try:
    # Connect
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    
    # Test connection
    client.server_info()
    print("✅ SUCCESS: Connected to MongoDB Atlas!")
    
    # Check database
    db = client.github_events
    print(f"📁 Database: {db.name}")
    
    # Create collection
    collection = db.events
    print(f"🗂️  Collection: events")
    
    # Insert test data
    test_doc = {
        "test": "First document",
        "message": "MongoDB is working!",
        "timestamp": "2024-01-01",
        "author": "Siddharth"
    }
    result = collection.insert_one(test_doc)
    print(f"📝 Inserted test document. ID: {result.inserted_id}")
    
    # Count documents
    count = collection.count_documents({})
    print(f"🔢 Total documents: {count}")
    
    print("\n🎉 MongoDB setup is COMPLETE!")
    
except Exception as e:
    print(f"❌ ERROR: {e}")
    print("\n🔧 Quick fixes:")
    print("1. Go to MongoDB Atlas → Network Access")
    print("2. Add IP address: 0.0.0.0/0")
    print("3. Wait 2 minutes")
    print("4. Try again")