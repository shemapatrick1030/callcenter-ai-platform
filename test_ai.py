from groq import Groq

# PUT YOUR ACTUAL API KEY HERE (keep the quotes)
client = Groq(api_key="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")

company_knowledge = """
ACME CORP SUPPORT INFORMATION:

RETURN POLICY:
- Returns accepted within 30 days of purchase
- Item must be in original packaging
- Refunds processed within 5-7 business days
- Shipping costs are non-refundable

BUSINESS HOURS:
- Monday to Friday: 8 AM to 8 PM EST
- Saturday: 9 AM to 5 PM EST
- Sunday: Closed

SHIPPING:
- Free shipping on orders over $50
- Standard delivery: 3-5 business days
- Express delivery: 1-2 business days ($12.99 extra)
"""

def ask_ai(question):
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {
                "role": "system",
                "content": f"You are a customer support agent. Answer only using this info. If you don't know, say you'll connect to a human agent.\n\n{company_knowledge}"
            },
            {
                "role": "user",
                "content": question
            }
        ],
        temperature=1.0
    )
    return response.choices[0].message.content

print("=" * 50)
print("  ACME CORP AI SUPPORT AGENT")
print("=" * 50)
print("Type questions or 'quit' to exit\n")

while True:
    question = input("Customer: ")
    if question.lower() == "quit":
        print("Goodbye!")
        break
    if question.strip() == "":
        continue
    
    answer = ask_ai(question)
    print(f"AI Agent: {answer}\n")