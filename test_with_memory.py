import sqlite3
import json
from datetime import datetime
from groq import Groq

client = Groq(api_key="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")

# ============================================
# PART 1: SET UP THE DATABASE
# ============================================

def setup_database():
    """Create a simple database to store conversations and knowledge."""
    conn = sqlite3.connect("callcenter.db")
    cursor = conn.cursor()
    
    # Table for conversation history
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_question TEXT,
            ai_answer TEXT,
            was_helpful INTEGER,  -- 1=yes, 0=no, NULL=unknown
            created_at TEXT
        )
    """)
    
    # Table for knowledge base (can be updated over time)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            content TEXT,
            source TEXT,  -- 'original' or 'learned_from_chat'
            created_at TEXT
        )
    """)
    
    conn.commit()
    return conn

# ============================================
# PART 2: INITIAL KNOWLEDGE
# ============================================

def seed_initial_knowledge(conn):
    """Add the starting knowledge if the table is empty."""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM knowledge_base")
    count = cursor.fetchone()[0]
    
    if count == 0:
        initial_knowledge = [
            ("Return Policy", "Returns accepted within 30 days. Original packaging required. Refunds take 5-7 business days.", "original"),
            ("Business Hours", "Monday to Friday: 8 AM to 8 PM. Saturday: 9 AM to 5 PM. Sunday: Closed.", "original"),
            ("Shipping", "Free shipping on orders over $50. Standard: 3-5 days. Express: 1-2 days ($12.99 extra).", "original"),
        ]
        
        for topic, content, source in initial_knowledge:
            cursor.execute(
                "INSERT INTO knowledge_base (topic, content, source, created_at) VALUES (?, ?, ?, ?)",
                (topic, content, source, datetime.now().isoformat())
            )
        
        conn.commit()
        print("✅ Initial knowledge seeded into database\n")

# ============================================
# PART 3: GET KNOWLEDGE FROM DATABASE
# ============================================

def get_knowledge_base(conn):
    """Pull all knowledge from the database to give to the AI."""
    cursor = conn.cursor()
    cursor.execute("SELECT topic, content FROM knowledge_base")
    rows = cursor.fetchall()
    
    knowledge_text = ""
    for topic, content in rows:
        knowledge_text += f"\n{topic}:\n{content}\n"
    
    return knowledge_text

# ============================================
# PART 4: THE AI (SAME AS BEFORE, BUT READS FROM DB)
# ============================================

def ask_ai(question, knowledge_base):
    """Same function you know, but knowledge comes from the database now."""
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a customer support agent. "
                    "Answer using ONLY the provided knowledge base. "
                    "If you don't know, say you'll connect to a human agent. "
                    "Be professional but friendly.\n\n"
                    f"KNOWLEDGE BASE:\n{knowledge_base}"
                )
            },
            {"role": "user", "content": question}
        ],
        temperature=0.3
    )
    return response.choices[0].message.content

# ============================================
# PART 5: STORE CONVERSATIONS
# ============================================

def save_conversation(conn, question, answer, was_helpful=None):
    """Save every conversation so we can learn from it."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO conversations (customer_question, ai_answer, was_helpful, created_at) VALUES (?, ?, ?, ?)",
        (question, answer, was_helpful, datetime.now().isoformat())
    )
    conn.commit()

# ============================================
# PART 6: LEARN FROM CONVERSATIONS
# ============================================

def learn_new_knowledge(conn, question, answer):
    """If the AI didn't know something and a human stepped in,
    we can save the new knowledge for next time."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO knowledge_base (topic, content, source, created_at) VALUES (?, ?, 'learned_from_chat', ?)",
        (f"Question: {question[:50]}...", answer, datetime.now().isoformat())
    )
    conn.commit()
    print("📝 New knowledge saved for future conversations!")

def show_conversation_history(conn, limit=5):
    """Display recent conversations."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT customer_question, ai_answer, was_helpful, created_at FROM conversations ORDER BY id DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    
    if not rows:
        print("No conversations yet.")
        return
    
    print("\n📜 RECENT CONVERSATIONS:")
    print("-" * 60)
    for question, answer, helpful, timestamp in reversed(rows):
        helpful_str = {1: "👍", 0: "👎", None: "—"}[helpful]
        print(f"Q: {question}")
        print(f"A: {answer[:100]}{'...' if len(answer) > 100 else ''}")
        print(f"   {helpful_str} | {timestamp[:16]}")
        print("-" * 60)

# ============================================
# PART 7: MAIN PROGRAM
# ============================================

def main():
    conn = setup_database()
    seed_initial_knowledge(conn)
    
    print("=" * 50)
    print("  ACME CORP AI SUPPORT AGENT (WITH MEMORY)")
    print("=" * 50)
    print("Commands:")
    print("  Type a question - talk to the AI")
    print("  /history       - see recent conversations")
    print("  /learn         - add new knowledge from last chat")
    print("  /quit          - exit")
    print("=" * 50 + "\n")
    
    last_question = ""
    last_answer = ""
    
    while True:
        user_input = input("Customer: ").strip()
        
        if user_input.lower() == "/quit":
            break
        
        elif user_input.lower() == "/history":
            show_conversation_history(conn)
            continue
        
        elif user_input.lower() == "/learn":
            if last_question and last_answer:
                new_info = input("What should the AI have said? ")
                if new_info.strip():
                    learn_new_knowledge(conn, last_question, new_info)
                    print("✅ Knowledge base updated!")
            else:
                print("No recent conversation to learn from.")
            continue
        
        elif user_input == "":
            continue
        
        # Normal flow: ask the AI
        knowledge = get_knowledge_base(conn)
        answer = ask_ai(user_input, knowledge)
        
        print(f"AI Agent: {answer}\n")
        
        # Store the conversation
        save_conversation(conn, user_input, answer)
        
        # Remember for potential /learn command
        last_question = user_input
        last_answer = answer
        
        # Ask if the answer was helpful
        feedback = input("Was this helpful? (y/n/enter to skip): ").lower()
        if feedback == "y":
            save_conversation(conn, user_input, answer, was_helpful=1)
        elif feedback == "n":
            save_conversation(conn, user_input, answer, was_helpful=0)
    
    conn.close()
    print("\nGoodbye! All conversations saved to callcenter.db")

if __name__ == "__main__":
    main()