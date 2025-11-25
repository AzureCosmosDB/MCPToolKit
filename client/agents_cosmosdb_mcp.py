# Import necessary libraries

import os, time
from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential
from azure.ai.agents.models import (
    ListSortOrder,
    SubmitToolOutputsAction,
    ToolOutput
)
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
project_endpoint = os.getenv("PROJECT_ENDPOINT")
model_deployment = os.getenv("MODEL_DEPLOYMENT_NAME")
connection_name = os.getenv("CONNECTION_NAME")

# Get MCP server configuration from environment variables
mcp_server_url = os.environ.get("MCP_SERVER_URL", "https://mcp-toolkit-app.icywave-532ba7dd.westus2.azurecontainerapps.io/mcp")
mcp_server_label = os.environ.get("MCP_SERVER_LABEL", "cosmosdb")

project_client = AIProjectClient(
    endpoint=project_endpoint,
    credential=AzureCliCredential(),
)

# Initialize agent MCP tool
mcp_tool_config = {
    "type": "mcp",
    "server_url": mcp_server_url,
    "server_label": mcp_server_label,
    "server_authentication": {
        "type": "connection",
        "connection_name": connection_name,
    }
}

mcp_tool_resources = {
    "mcp": [
        {
            "server_label": mcp_server_label,
            "require_approval": "never"
        }
    ]
}

# Create agent with MCP tool and process agent run
with project_client:
    agents_client = project_client.agents

    # Create a new agent.
    # NOTE: To reuse existing agent, fetch it with get_agent(agent_id)
    agent = agents_client.create_agent(
        model=model_deployment,
        name="cosmosdb-demo-agent-mcp",
        instructions="""
        You are a helpful agent that can use MCP tools to assist users with Azure Cosmos DB queries.
        
        Available tools:
        - list_databases: Lists all databases in the Cosmos DB account
        - list_collections: Lists all containers in a specific database
        - get_recent_documents: Gets the most recent documents from a container
        - text_search: Searches for documents containing specific text in a property
        - find_document_by_id: Finds a specific document by its ID
        - get_approximate_schema: Gets the schema of a container by sampling documents
        - vector_search: Performs semantic search using Azure OpenAI embeddings
        
        When a user asks about their data, use these tools to explore and query the Cosmos DB database.
        Always be helpful and explain what you're doing.
        """,
        tools=[mcp_tool_config],
    )

    print(f"Created agent, ID: {agent.id}")
    print(f"MCP Server: {mcp_server_label} at {mcp_server_url}")

    # Create thread for communication
    thread = agents_client.threads.create()
    print(f"Created thread, ID: {thread.id}")

    # Sample questions for testing
    input_text = [
        "Can you list all the databases in my Cosmos DB account?",
        "Show me the containers in the first database",
        "What does the schema look like for the first container?",
        "Get me the 5 most recent documents from the first container",
        "Search for documents containing 'test' in the name property",
    ]

    # Create message to thread - using the first question
    message = agents_client.messages.create(
        thread_id=thread.id,
        role="user",
        content=input_text[0]  # Change index to test different questions
    )
    print(f"Created message, ID: {message.id}")
    
    # Create and process agent run in thread with MCP tools
    run = agents_client.runs.create(thread_id=thread.id, agent_id=agent.id, tool_resources=mcp_tool_resources)
    print(f"Created run, ID: {run.id}")

    while run.status in ["queued", "in_progress", "requires_action"]:
        time.sleep(1)
        run = agents_client.runs.get(thread_id=thread.id, run_id=run.id)

        if run.status == "requires_action":
            if isinstance(run.required_action, SubmitToolOutputsAction):
                tool_calls = run.required_action.submit_tool_outputs.tool_calls
                if not tool_calls:
                    print("No tool calls provided - cancelling run")
                    agents_client.runs.cancel(thread_id=thread.id, run_id=run.id)
                    break

                tool_outputs = []
                for tool_call in tool_calls:
                    try:
                        print(f"Processing tool call: {tool_call.id}")
                        # For MCP tools, the output is handled by the service
                        # We just acknowledge the tool call
                        tool_outputs.append(
                            ToolOutput(
                                tool_call_id=tool_call.id,
                                output="{}"  # Empty JSON object as placeholder
                            )
                        )
                    except Exception as e:
                        print(f"Error processing tool_call {tool_call.id}: {e}")

                print(f"tool_outputs: {tool_outputs}")
                if tool_outputs:
                    agents_client.runs.submit_tool_outputs(
                        thread_id=thread.id, run_id=run.id, tool_outputs=tool_outputs
                    )

        print(f"Current run status: {run.status}")

    print(f"Run completed with status: {run.status}")
    if run.status == "failed":
        print(f"Run failed: {run.last_error}")

    # Display run steps and tool calls
    run_steps = agents_client.run_steps.list(thread_id=thread.id, run_id=run.id)

    # Loop through each step
    for step in run_steps:
        print(f"Step {step['id']} status: {step['status']}")

        # Check if there are tool calls in the step details
        step_details = step.get("step_details", {})
        tool_calls = step_details.get("tool_calls", [])

        if tool_calls:
            print("  MCP Tool calls:")
            for call in tool_calls:
                print(f"    Tool Call ID: {call.get('id')}")
                print(f"    Type: {call.get('type')}")

        if hasattr(step_details, 'activities'):
            for activity in step_details.activities:
                for function_name, function_definition in activity.tools.items():
                    print(
                        f'  The function {function_name} with description "{function_definition.description}" will be called.:'
                    )
                    if len(function_definition.parameters) > 0:
                        print("  Function parameters:")
                        for argument, func_argument in function_definition.parameters.properties.items():
                            print(f"      {argument}")
                            print(f"      Type: {func_argument.type}")
                            print(f"      Description: {func_argument.description}")
                    else:
                        print("This function has no parameters")

        print()  # add an extra newline between steps

    # Fetch and log all messages
    messages = agents_client.messages.list(thread_id=thread.id, order=ListSortOrder.ASCENDING)
    print("\nConversation:")
    print("-" * 50)
    for msg in messages:
        if msg.text_messages:
            last_text = msg.text_messages[-1]
            print(f"{msg.role.upper()}: {last_text.text.value}")
            print("-" * 50)

    # Clean-up and delete the agent once the run is finished.
    # NOTE: Comment out this line if you plan to reuse the agent later.
    # agents_client.delete_agent(agent.id)
    # print("Deleted agent")
