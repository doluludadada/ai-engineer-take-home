# The colleague's original code for question 1, kept word for word for comparison. This file is deliberately left
# unchanged and is never run, tested or formatted.
import json
from openai import OpenAI

client = OpenAI(base_url="https://llm-gateway.example.internal/v1",
                api_key="sk-agent-order-7f3a9c")

TOOLS = [
    {"type": "function", "function": {
        "name": "get_order",
        "description": "查詢訂單",
        "parameters": {"type": "object",
                       "properties": {"order_id": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "cancel_order",
        "description": "取消訂單",
        "parameters": {"type": "object",
                       "properties": {"order_id": {"type": "string"}}}}},
]

def get_order(order_id):
    return db.query(f"SELECT * FROM orders WHERE id = '{order_id}'")

def cancel_order(order_id):
    return db.execute(f"UPDATE orders SET status='cancelled' WHERE id = '{order_id}'")

def run(user_message):
    messages = [{"role": "system", "content": "你是訂單助理，幫客人查詢與取消訂單。"},
                {"role": "user", "content": user_message}]
    while True:
        resp = client.chat.completions.create(
            model="gpt-4o", messages=messages, tools=TOOLS)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return msg.content
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments)
            result = globals()[call.function.name](**args)
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": str(result)})
