# Code Review Checklist

1. **Correctness & Safety**:
   - Are edge cases handled?
   - Are error messages informative?
   - Are open file handles and resources properly closed?

2. **Structure & Maintainability**:
   - Are functions concise and focused on a single task?
   - Are variable and function names self-descriptive?

3. **Security & Path Validation**:
   - Are relative file paths sanitized and constrained to the project root?
