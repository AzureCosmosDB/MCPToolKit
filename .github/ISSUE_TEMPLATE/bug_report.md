---
name: Bug Report
about: Report a bug or issue with the Azure Cosmos DB MCP Toolkit
title: '[BUG] '
labels: bug
assignees: ''
---

## Bug Description

A clear and concise description of what the bug is.

## Environment

- **Deployment Method**: [PowerShell Script / azd up / Manual]
- **Azure Region**: [e.g., East US, West Europe]
- **Resource Group**: [Your resource group name]
- **Operating System**: [e.g., Windows 11, macOS 14, Ubuntu 22.04]
- **PowerShell Version**: [e.g., 7.4.0]
- **Azure CLI Version**: [e.g., 2.54.0]
- **.NET Version**: [e.g., 9.0, if building locally]

## Steps to Reproduce

1. Go to '...'
2. Click on '...'
3. Run command '...'
4. See error

## Expected Behavior

A clear and concise description of what you expected to happen.

## Actual Behavior

A clear and concise description of what actually happened.

## Error Messages / Logs

```
Paste any error messages, stack traces, or relevant logs here
```

## Screenshots

If applicable, add screenshots to help explain your problem.

## MCP Tool Context

If this issue relates to a specific MCP tool, please specify:

- **Tool Name**: [e.g., vector_search, get_recent_documents]
- **Parameters Used**: 
  ```json
  {
    "databaseId": "example",
    "containerId": "example",
    ...
  }
  ```

## Deployment Configuration

If relevant, provide your deployment configuration (remove sensitive information):

```json
// Contents from deployment-info.json (if applicable)
{
  "containerAppUrl": "...",
  "entraAppClientId": "...",
  ...
}
```

## Additional Context

Add any other context about the problem here. For example:
- Does this happen consistently or intermittently?
- Did this work before and recently break?
- Are there any workarounds you've found?

## Possible Solution

If you have ideas on how to fix the issue, please share them here.

---

**Checklist:**
- [ ] I have searched existing issues to avoid duplicates
- [ ] I have provided all relevant environment information
- [ ] I have included error messages and logs
- [ ] I have removed any sensitive information (keys, tokens, etc.)
