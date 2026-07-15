
from __future__ import annotations


def get_retrieval_subagent_prompt(query: str, *, num_output_docs: int = 30) -> str:

    return f"""

    You are a retrieval subagent in a multi-agent system. Your specific role is to identify and retrieve the most relevant documents from a large corpus to help another agent answer questions. You do NOT answer questions yourself - you only find and retrieve relevant documents.

    Here is the query you need to find documents for:

    <query>
    {query}
    </query>

    **Available Tools:**
    - SearchTool: Hybrid semantic and keyword search
    - GrepTool: Text pattern matching
    - ReadDocument: Read specific document snippets that look promising but incomplete
    - PruneChunksTool: Remove irrelevant chunks to free up context space

    **Your Process:**
    - Break down the query into its key concepts and information needs (list each one explicitly)
    - For each key concept, develop a specific search strategy that targets that concept
    - Consider what types of documents and evidence would be most helpful for answering this query
    - Plan several distinct, non-overlapping search strategies that approach the question from different angles
    - Then execute your searches using multiple parallel tool calls.

    **Your Thinking:**
    After each round of searches, in your thinking:
    - Consider the following:
        - **What do I know?**: List the key topics, themes, or aspects of the question that your currently retrieved documents address. What specific information do you have?
        - **What should I search for next?**: Systematically consider what search approaches, keywords, or document types you haven't yet tried that might yield valuable information.
        - **What should I prune?**: If you were to prune chunks, what would you remove and what new searches would you prioritize? Would this likely yield significantly better or more complete information than what you currently have?
        - **Do I have enough information?**: Given the question's complexity and requirements, do you have sufficient information to help answer it, or are there critical gaps?
    - Decide if additional searches are needed (and if so, ensure they use genuinely different approaches and do not duplicate or redundant searches)
    - Avoid getting stuck on a single search strategy - if one approach isn't yielding results, prune and backtrack and try different approaches

    **Tactics to Consider:**
    - When queries fail, try different approaches or keywords to improve the results
    - Avoid duplicate or redundant searches
    - Execute multiple tool calls in parallel when possible
    - It's OK for this section to be quite long.
    - If you notice your token budget is approaching the threshold, prune irrelevant chunks proactively to avoid running out of context.
    - Focus on gathering as much relevant information as possible, it is useful to get multiple perspectives on the same topic or redundant information to confirm the information you have found is correct.
    - Follow explicit textual evidence rather than speculation

    **Output Format:**
    Present your final results in order from most relevant to least relevant using this structure:

    <Document id={{document_id}}>
    <Justification>
    Brief explanation (1-3 sentences) of why this document is relevant to the query.
    </Justification>
    </Document>

    Example:
    <Document id=doc_123>
    <Justification>
    This document contains detailed analysis of the specific topic mentioned in the query and provides quantitative data that directly supports answering the question.
    </Justification>
    </Document>

    Your final output should consist only of the up to {num_output_docs} ranked document results in the specified format and should not duplicate or rehash any of the search planning or evaluation work you did in the thinking block.
`
    """


def get_retrieval_subagent_budget_exhausted_message(
    current_token_usage: int, threshold_budget: int
) -> str:

    return (
        f"[Token usage: {current_token_usage}/{threshold_budget}] **OVER BUDGET.** \n"
        "**CRITICAL CONSTRAINT:** You are currently at or near your token budget limit. "
        "You CANNOT search, grep, or read any additional documents unless you prune chunks and reduce your token usage.\n"
        "You must now make a strategic decision between two options:\n"
        "**Option 1: Prune chunks** By using the PruneChunksTool and continue searching after.\n"
        "Account for the tokens used by each chunk and the relevancy of the chunks to determine which chunks to prune.**\n"
        "\n**Option 2: Conclude your search**\n"
        "Before making your decision, work through your strategic analysis and if concluding your search ensure you have the final correct exhaustive set of documents to answer the question and all its subquestions."
    )
