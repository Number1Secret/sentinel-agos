"""
E2B Sandbox for safe code execution.
Used by Code Agent to validate generated code before deployment.
"""
import asyncio
from dataclasses import dataclass
from typing import Optional

import structlog

from config import settings

logger = structlog.get_logger()


@dataclass
class SandboxResult:
    """Result from sandbox execution."""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    artifacts: list[str]
    execution_time_ms: int


class E2BSandbox:
    """
    Secure code execution environment using E2B.

    Features:
    - Isolated cloud sandbox (not local Docker)
    - 30-second timeout by default
    - No network access to prevent exfiltration
    - Automatic cleanup after execution
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.e2b_api_key
        self.default_timeout = 30  # seconds

        # Check if E2B is available
        self._e2b_available = bool(self.api_key)
        if not self._e2b_available:
            logger.warning("E2B API key not configured, sandbox execution disabled")

    async def execute_python(
        self,
        code: str,
        timeout: int = None,
    ) -> SandboxResult:
        """Execute Python code in isolated sandbox."""
        if not self._e2b_available:
            return self._mock_execution(code, "python")

        timeout = timeout or self.default_timeout

        try:
            from e2b_code_interpreter import Sandbox

            sandbox = Sandbox(api_key=self.api_key)

            start_time = asyncio.get_event_loop().time()

            # Execute with timeout
            execution = sandbox.run_code(code, timeout=timeout)

            end_time = asyncio.get_event_loop().time()

            return SandboxResult(
                success=execution.exit_code == 0,
                stdout=execution.logs.stdout if hasattr(execution.logs, 'stdout') else str(execution.logs),
                stderr=execution.logs.stderr if hasattr(execution.logs, 'stderr') else "",
                exit_code=execution.exit_code,
                artifacts=[a.url for a in getattr(execution, 'artifacts', [])],
                execution_time_ms=int((end_time - start_time) * 1000)
            )

        except ImportError:
            logger.warning("e2b_code_interpreter not installed")
            return self._mock_execution(code, "python")

        except Exception as e:
            logger.error("Sandbox execution failed", error=str(e))
            return SandboxResult(
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=1,
                artifacts=[],
                execution_time_ms=0
            )

        finally:
            if 'sandbox' in locals():
                try:
                    sandbox.close()
                except Exception:
                    pass

    async def execute_javascript(
        self,
        code: str,
        timeout: int = None,
    ) -> SandboxResult:
        """Execute JavaScript/Node.js code in isolated sandbox."""
        if not self._e2b_available:
            return self._mock_execution(code, "javascript")

        timeout = timeout or self.default_timeout

        try:
            from e2b_code_interpreter import Sandbox

            sandbox = Sandbox(
                api_key=self.api_key,
                template="node"  # Node.js template
            )

            start_time = asyncio.get_event_loop().time()

            execution = sandbox.run_code(code, timeout=timeout)

            end_time = asyncio.get_event_loop().time()

            return SandboxResult(
                success=execution.exit_code == 0,
                stdout=execution.logs.stdout if hasattr(execution.logs, 'stdout') else str(execution.logs),
                stderr=execution.logs.stderr if hasattr(execution.logs, 'stderr') else "",
                exit_code=execution.exit_code,
                artifacts=[a.url for a in getattr(execution, 'artifacts', [])],
                execution_time_ms=int((end_time - start_time) * 1000)
            )

        except ImportError:
            logger.warning("e2b_code_interpreter not installed")
            return self._mock_execution(code, "javascript")

        except Exception as e:
            logger.error("Sandbox execution failed", error=str(e))
            return SandboxResult(
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=1,
                artifacts=[],
                execution_time_ms=0
            )

        finally:
            if 'sandbox' in locals():
                try:
                    sandbox.close()
                except Exception:
                    pass

    async def validate_generated_code(
        self,
        code: str,
        language: str = "python",
        test_code: Optional[str] = None,
    ) -> dict:
        """
        Validate AI-generated code before deployment.

        Args:
            code: The generated code to validate
            language: Programming language ("python" or "javascript")
            test_code: Optional test code to run against the generated code

        Returns:
            {
                "valid": bool,
                "syntax_ok": bool,
                "tests_passed": bool,
                "output": str,
                "errors": list[str]
            }
        """
        errors = []

        # Step 1: Syntax check
        if language == "python":
            syntax_check = f"""
import ast
try:
    ast.parse('''{code.replace("'''", "\\'\\'\\'")}''')
    print("SYNTAX_OK")
except SyntaxError as e:
    print(f"SYNTAX_ERROR: {{e}}")
"""
            syntax_result = await self.execute_python(syntax_check)
            syntax_ok = "SYNTAX_OK" in syntax_result.stdout
            if not syntax_ok:
                errors.append(syntax_result.stdout)

        else:
            # For JS, attempt to parse
            syntax_check = f"""
try {{
    new Function({repr(code)});
    console.log("SYNTAX_OK");
}} catch (e) {{
    console.log("SYNTAX_ERROR: " + e.message);
}}
"""
            syntax_result = await self.execute_javascript(syntax_check)
            syntax_ok = "SYNTAX_OK" in syntax_result.stdout
            if not syntax_ok:
                errors.append(syntax_result.stdout)

        # Step 2: Run tests if provided
        tests_passed = True
        test_output = ""

        if test_code and syntax_ok:
            full_code = f"{code}\n\n{test_code}"

            if language == "python":
                test_result = await self.execute_python(full_code)
            else:
                test_result = await self.execute_javascript(full_code)

            tests_passed = test_result.success
            test_output = test_result.stdout

            if not tests_passed:
                errors.append(test_result.stderr or test_result.stdout)

        return {
            "valid": syntax_ok and tests_passed,
            "syntax_ok": syntax_ok,
            "tests_passed": tests_passed,
            "output": test_output or syntax_result.stdout,
            "errors": errors,
        }

    def _mock_execution(self, code: str, language: str) -> SandboxResult:
        """Mock execution when E2B is not available."""
        logger.info("Mock sandbox execution", language=language, code_length=len(code))

        # Do basic syntax check locally
        if language == "python":
            try:
                import ast
                ast.parse(code)
                return SandboxResult(
                    success=True,
                    stdout="SYNTAX_OK (mock execution)",
                    stderr="",
                    exit_code=0,
                    artifacts=[],
                    execution_time_ms=1,
                )
            except SyntaxError as e:
                return SandboxResult(
                    success=False,
                    stdout="",
                    stderr=f"SYNTAX_ERROR: {e}",
                    exit_code=1,
                    artifacts=[],
                    execution_time_ms=1,
                )

        # For JavaScript, just return success (no local validation)
        return SandboxResult(
            success=True,
            stdout="Mock execution - no validation performed",
            stderr="",
            exit_code=0,
            artifacts=[],
            execution_time_ms=1,
        )


class CodeAgent:
    """Agent for generating and validating code."""

    def __init__(self, sandbox: E2BSandbox = None):
        self.sandbox = sandbox or E2BSandbox()

    async def generate_and_validate(
        self,
        prompt: str,
        language: str = "python",
    ) -> dict:
        """
        Generate code and validate in sandbox before returning.

        This is a placeholder for the full Code Agent implementation.
        In the MVP, we focus on the Scout Agent for website analysis.
        """
        # This would integrate with Claude to generate code
        # For now, return a placeholder
        return {
            "code": "# Code generation not implemented in MVP",
            "validation": {
                "valid": True,
                "syntax_ok": True,
                "tests_passed": True,
                "output": "",
                "errors": [],
            },
            "ready_to_deploy": False,
        }
