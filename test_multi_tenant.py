import sqlite3
from datetime import datetime
from groq import Groq

client = Groq(api_key="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")

def setup_database():
    conn = sqlite3.connect("callcenter.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            api_key TEXT UNIQUE NOT NULL,
            industry TEXT DEFAULT 'general',
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            topic TEXT,
            content TEXT,
            source TEXT DEFAULT 'manual',
            created_at TEXT,
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            customer_identifier TEXT DEFAULT 'anonymous',
            question TEXT,
            answer TEXT,
            was_helpful INTEGER,
            created_at TEXT,
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        )
    """)
    
    conn.commit()
    return conn

def create_tenant(conn, company_name, industry="general"):
    import secrets
    api_key = secrets.token_hex(16)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tenants (company_name, api_key, industry, created_at) VALUES (?, ?, ?, ?)",
        (company_name, api_key, industry, datetime.now().isoformat())
    )
    conn.commit()
    print(f"\n✅ Company '{company_name}' created!")
    print(f"   Their API Key: {api_key}")
    return cursor.lastrowid

def list_tenants(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT id, company_name, industry, is_active FROM tenants")
    tenants = cursor.fetchall()
    print("\n🏢 YOUR CLIENTS:")
    print("-" * 40)
    for t_id, name, industry, active in tenants:
        status = "✅ Active" if active else "❌ Inactive"
        print(f"  [{t_id}] {name} | {industry} | {status}")
    print("-" * 40)
    return tenants

def get_tenant_knowledge(conn, tenant_id):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT topic, content FROM knowledge_base WHERE tenant_id = ?",
        (tenant_id,)
    )
    rows = cursor.fetchall()
    knowledge_text = ""
    for topic, content in rows:
        knowledge_text += f"\n{topic}:\n{content}\n"
    return knowledge_text

def add_knowledge(conn, tenant_id, topic, content, source="manual"):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO knowledge_base (tenant_id, topic, content, source, created_at) VALUES (?, ?, ?, ?, ?)",
        (tenant_id, topic, content, source, datetime.now().isoformat())
    )
    conn.commit()

def seed_demo_tenants(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM tenants")
    count = cursor.fetchone()[0]
    if count > 0:
        return
    
    acme_id = create_tenant(conn, "Acme Corp", "retail")
    add_knowledge(conn, acme_id, "Return Policy", "30-day returns. Original packaging required. Refunds in 5-7 business days.")
    add_knowledge(conn, acme_id, "Shipping", "Free shipping over $50. Standard 3-5 days. Express 1-2 days ($12.99).")
    add_knowledge(conn, acme_id, "Business Hours", "Mon-Fri 8AM-8PM. Sat 9AM-5PM. Sun closed.")
    
    tgi_id = create_tenant(conn, "TechGuard Insurance", "insurance")
    add_knowledge(conn, tgi_id, "Claims Process", "File claims online or call 1-800-TECH. Response within 24 hours.")
    add_knowledge(conn, tgi_id, "Coverage", "Covers accidental damage, theft, and mechanical failure. $50 deductible.")

def ask_ai(question, knowledge_base, company_name):
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are a customer support agent for {company_name}. "
                    "Answer using ONLY the knowledge base provided below. "
                    "If the information doesn't contain the answer, say: "
                    "'I don't have that information available. Let me connect you with a human agent.' "
                    "Never make up information. Be professional and helpful.\n\n"
                    f"KNOWLEDGE BASE:\n{knowledge_base}"
                )
            },
            {"role": "user", "content": question}
        ],
        temperature=0.3
    )
    return response.choices[0].message.content

def save_conversation(conn, tenant_id, question, answer, helpful=None):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO conversations (tenant_id, question, answer, was_helpful, created_at) VALUES (?, ?, ?, ?, ?)",
        (tenant_id, question, answer, helpful, datetime.now().isoformat())
    )
    conn.commit()

def handle_command(user_input, conn, tenant_id, company_name, last_question, last_answer):
    """Process special commands. Returns (should_continue, new_tenant_id, new_company_name)."""
    cmd = user_input.lower()
    cursor = conn.cursor()
    
    if cmd == "/switch":
        list_tenants(conn)
        try:
            new_id = int(input("Switch to tenant ID: "))
            cursor.execute("SELECT company_name FROM tenants WHERE id = ?", (new_id,))
            row = cursor.fetchone()
            if row:
                print(f"✅ Switched to {row[0]}\n")
                return True, new_id, row[0]
            else:
                print("Invalid ID.\n")
        except ValueError:
            print("Please enter a number.\n")
        return True, tenant_id, company_name
    
    elif cmd == "/add":
        topic = input("Topic: ")
        content = input("Content: ")
        if topic.strip() and content.strip():
            add_knowledge(conn, tenant_id, topic, content)
            print(f"✅ Knowledge added to {company_name}!\n")
        return True, tenant_id, company_name
    
    elif cmd == "/history":
        cursor.execute(
            "SELECT question, answer, created_at FROM conversations WHERE tenant_id = ? ORDER BY id DESC LIMIT 5",
            (tenant_id,)
        )
        rows = cursor.fetchall()
        print(f"\n📜 Recent conversations for {company_name}:")
        if rows:
            for q, a, t in reversed(rows):
                print(f"  Q: {q}")
                print(f"  A: {a[:80]}...")
                print(f"  {t[:16]}\n")
        else:
            print("  No conversations yet.\n")
        return True, tenant_id, company_name
    
    elif cmd == "/learn":
        if last_question and last_answer:
            print(f"Previous question: {last_question}")
            print(f"AI's answer was: {last_answer[:100]}...")
            new_info = input("What should the AI have said? ")
            if new_info.strip():
                topic = f"Q: {last_question[:50]}"
                add_knowledge(conn, tenant_id, topic, new_info, source="learned_from_chat")
                print(f"✅ Knowledge added to {company_name}!\n")
            else:
                print("Nothing saved.\n")
        else:
            print("No recent conversation to learn from.\n")
        return True, tenant_id, company_name
    
    elif cmd == "/quit":
        return False, tenant_id, company_name
    
    elif cmd == "":
        return True, tenant_id, company_name
    
    # Not a command - it's a question for the AI
    return "ask_ai", tenant_id, company_name

def main():
    conn = setup_database()
    seed_demo_tenants(conn)
    
    print("=" * 55)
    print("  CALL CENTER AI - MULTI-TENANT PLATFORM")
    print("=" * 55)
    
    tenants = list_tenants(conn)
    if not tenants:
        name = input("Company name: ")
        industry = input("Industry: ")
        tenant_id = create_tenant(conn, name, industry)
    else:
        tenant_id = int(input("\nSelect a tenant ID to test: "))
    
    cursor = conn.cursor()
    cursor.execute("SELECT company_name FROM tenants WHERE id = ?", (tenant_id,))
    tenant = cursor.fetchone()
    if not tenant:
        print("Invalid tenant ID.")
        conn.close()
        return
    
    company_name = tenant[0]
    
    print(f"\n🤖 Now testing AI for: {company_name}")
    print("Commands: /switch, /add, /learn, /history, /quit\n")
    
    last_question = ""
    last_answer = ""
    running = True
    
    while running:
        user_input = input("Customer: ").strip()
        
        result, tenant_id, company_name = handle_command(
            user_input, conn, tenant_id, company_name, last_question, last_answer
        )
        
        if result == False:  # /quit
            running = False
        
        elif result == True:  # Command was handled
            continue
        
        elif result == "ask_ai":  # It's a question for the AI
            knowledge = get_tenant_knowledge(conn, tenant_id)
            
            if not knowledge:
                print("⚠️  This company has no knowledge base yet. Use /add to add some.\n")
                continue
            
            answer = ask_ai(user_input, knowledge, company_name)
            print(f"AI Agent ({company_name}): {answer}\n")
            
            save_conversation(conn, tenant_id, user_input, answer)
            last_question = user_input
            last_answer = answer
    
    conn.close()
    print("\nGoodbye! All data saved per tenant.")

if __name__ == "__main__":
    main()