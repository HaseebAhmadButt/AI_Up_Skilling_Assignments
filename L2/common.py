import json
import os

from dotenv import load_dotenv
from langchain_core.messages import ToolMessage, convert_to_messages
from langchain_openai import ChatOpenAI

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

REFUSAL = "I am Help Desk AI Assistant, I can only help you to get the approvers list if you need."


def invoke_agent(messages, tools=None, tool_map=None, max_steps=6, verbose=True):
    """Call the model. If tools are given, run requested tools and feed results back until the model answers."""
    llm = ChatOpenAI(
        model="gpt-4o",
        api_key=OPENAI_API_KEY,
        temperature=0.0,
        max_tokens=500,
    )
    if not tools:
        return llm.invoke(messages).content

    llm = llm.bind_tools(tools)
    conversation = convert_to_messages(messages)
    for _ in range(max_steps):
        response = llm.invoke(conversation)
        if not response.tool_calls:
            return response.content
        conversation.append(response)
        for call in response.tool_calls:
            try:
                result = tool_map[call["name"]].invoke(call["args"])
            except Exception as error:
                result = {"error": f"Tool failed: {error}"}
            if verbose:
                print(f"  [tool] {call['name']}({call['args']}) -> {result}")
            conversation.append(ToolMessage(content=json.dumps(result), tool_call_id=call["id"]))
    return "Routing cannot be completed: manual escalation required."


def read_required(prompt_text):
    """Keep asking until the user enters a non-empty value."""
    while True:
        value = input(prompt_text).strip()
        if value:
            return value
        print("This field is required. Please try again.")


def read_cost():
    """Keep asking until the user enters a valid positive number."""
    while True:
        raw = input("Request cost (USD): ").strip()
        cleaned = raw.replace("$", "").replace(",", "")
        try:
            cost = float(cleaned)
        except ValueError:
            print("Please enter a numeric amount, for example 1800 or $1,800.")
            continue
        if cost <= 0:
            print("Cost must be greater than zero.")
            continue
        return cost


def read_user_request():
    """Collect the four fields the system prompt expects."""
    print("\nPlease enter the software request details.\n")
    request_cost = read_cost()
    requester_identity = read_required("Requester identity (name, title, department): ")
    manager_name = read_required("Manager name: ")
    policy_context = input("Policy context (optional, e.g. software name): ").strip()

    return {
        "request_cost": request_cost,
        "requester_identity": requester_identity,
        "manager_name": manager_name,
        "policy_context": policy_context or "Not provided",
    }


def build_user_message(request):
    """Format the fields as labeled lines so they match the system prompt."""
    return (
        f"Request cost: ${request['request_cost']:,.2f}\n"
        f"Requester identity: {request['requester_identity']}\n"
        f"Manager name: {request['manager_name']}\n"
        f"Policy context: {request['policy_context']}"
    )
