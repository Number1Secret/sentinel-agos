"""
E2B MCP Server Configuration and Client.

Provides sandboxed code execution for mockup generation:
- Create isolated sandbox environments
- Run code in Next.js/React templates
- Install packages dynamically
- Get live preview URLs
- Export generated code

E2B Documentation: https://e2b.dev/docs
"""
import os
from dataclasses import dataclass, field
from typing import Optional, Any
from contextlib import asynccontextmanager

import structlog

logger = structlog.get_logger()


@dataclass
class E2BMCPConfig:
    """Configuration for E2B MCP server."""
    name: str = "e2b"
    api_key_env: str = "E2B_API_KEY"
    default_template: str = "nextjs-developer"
    timeout_seconds: int = 300  # 5 minutes
    max_timeout_hours: int = 72  # Sandbox can live up to 72 hours

    # Available templates
    templates: dict = field(default_factory=lambda: {
        "nextjs": "nextjs-developer",
        "react": "react-developer",
        "python": "python3",
        "node": "nodejs"
    })

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "api_key_env": self.api_key_env,
            "default_template": self.default_template,
            "timeout_seconds": self.timeout_seconds,
            "max_timeout_hours": self.max_timeout_hours,
            "templates": self.templates
        }


# Default configuration
E2B_CONFIG = E2BMCPConfig()

# Mockup template configurations
MOCKUP_TEMPLATES = {
    "modern-professional": {
        "base": "nextjs",
        "packages": ["tailwindcss", "lucide-react", "framer-motion"],
        "starter_files": {
            "tailwind.config.js": True,
            "postcss.config.js": True,
            "globals.css": True
        }
    },
    "minimal-clean": {
        "base": "nextjs",
        "packages": ["tailwindcss"],
        "starter_files": {
            "tailwind.config.js": True,
            "globals.css": True
        }
    },
    "bold-startup": {
        "base": "nextjs",
        "packages": ["tailwindcss", "framer-motion", "@headlessui/react"],
        "starter_files": {
            "tailwind.config.js": True,
            "globals.css": True
        }
    },
    "corporate-trust": {
        "base": "nextjs",
        "packages": ["tailwindcss", "lucide-react"],
        "starter_files": {
            "tailwind.config.js": True,
            "globals.css": True
        }
    }
}


class E2BMCPClient:
    """
    Client for E2B sandboxed code execution.

    Provides methods to:
    - Create sandboxes from templates
    - Run code and commands
    - Write/read files
    - Get preview URLs
    - Clean up sandboxes
    """

    def __init__(self, config: Optional[E2BMCPConfig] = None):
        self.config = config or E2BMCPConfig()
        self._sandbox = None
        self._api_key = os.getenv(self.config.api_key_env)

    @property
    def is_available(self) -> bool:
        """Check if E2B is available (API key configured)."""
        return self._api_key is not None

    async def create_sandbox(
        self,
        template: str = "nextjs",
        files: Optional[dict[str, str]] = None,
        packages: Optional[list[str]] = None,
        timeout_seconds: Optional[int] = None
    ) -> dict:
        """
        Create a new E2B sandbox.

        Args:
            template: Template name (nextjs, react, python, node)
            files: Dict of filename -> content to write
            packages: List of packages to install
            timeout_seconds: Override timeout

        Returns:
            Dict with sandbox_id and preview_url
        """
        if not self.is_available:
            logger.warning("E2B not available - no API key")
            return {"error": "E2B not configured", "sandbox_id": None, "preview_url": None}

        try:
            from e2b_code_interpreter import Sandbox

            # Get template ID
            template_id = self.config.templates.get(template, self.config.default_template)

            # Create sandbox
            timeout = timeout_seconds or self.config.timeout_seconds
            self._sandbox = Sandbox(
                template=template_id,
                api_key=self._api_key,
                timeout=timeout
            )

            sandbox_id = self._sandbox.id
            logger.info("E2B sandbox created", sandbox_id=sandbox_id, template=template)

            # Write files if provided
            if files:
                for filename, content in files.items():
                    await self.write_file(filename, content)

            # Install packages if provided
            if packages:
                await self.install_packages(packages)

            # Get preview URL
            preview_url = await self._get_preview_url()

            return {
                "sandbox_id": sandbox_id,
                "preview_url": preview_url,
                "template": template
            }

        except ImportError:
            logger.error("E2B package not installed")
            return {"error": "E2B package not installed", "sandbox_id": None, "preview_url": None}

        except Exception as e:
            logger.error("Failed to create E2B sandbox", error=str(e))
            return {"error": str(e), "sandbox_id": None, "preview_url": None}

    async def run_code(
        self,
        code: str,
        language: str = "python"
    ) -> dict:
        """
        Execute code in the sandbox.

        Args:
            code: Code to execute
            language: Programming language

        Returns:
            Dict with stdout, stderr, result
        """
        if not self._sandbox:
            return {"error": "No active sandbox"}

        try:
            execution = self._sandbox.run_code(code)

            return {
                "success": True,
                "stdout": execution.logs.stdout,
                "stderr": execution.logs.stderr,
                "result": execution.results,
                "error": execution.error.message if execution.error else None
            }

        except Exception as e:
            logger.error("Code execution failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def run_command(self, command: str) -> dict:
        """
        Run a shell command in the sandbox.

        Args:
            command: Shell command to run

        Returns:
            Dict with stdout, stderr, exit_code
        """
        if not self._sandbox:
            return {"error": "No active sandbox"}

        try:
            result = self._sandbox.commands.run(command)

            return {
                "success": result.exit_code == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code
            }

        except Exception as e:
            logger.error("Command execution failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def install_packages(self, packages: list[str]) -> dict:
        """
        Install npm packages in the sandbox.

        Args:
            packages: List of package names

        Returns:
            Dict with success status
        """
        if not packages:
            return {"success": True}

        packages_str = " ".join(packages)
        return await self.run_command(f"npm install {packages_str}")

    async def write_file(self, path: str, content: str) -> dict:
        """
        Write a file to the sandbox.

        Args:
            path: File path in sandbox
            content: File content

        Returns:
            Dict with success status
        """
        if not self._sandbox:
            return {"error": "No active sandbox"}

        try:
            self._sandbox.files.write(path, content)
            logger.debug("File written to sandbox", path=path)
            return {"success": True, "path": path}

        except Exception as e:
            logger.error("Failed to write file", path=path, error=str(e))
            return {"success": False, "error": str(e)}

    async def read_file(self, path: str) -> dict:
        """
        Read a file from the sandbox.

        Args:
            path: File path in sandbox

        Returns:
            Dict with content or error
        """
        if not self._sandbox:
            return {"error": "No active sandbox"}

        try:
            content = self._sandbox.files.read(path)
            return {"success": True, "content": content, "path": path}

        except Exception as e:
            logger.error("Failed to read file", path=path, error=str(e))
            return {"success": False, "error": str(e)}

    async def _get_preview_url(self, port: int = 3000) -> Optional[str]:
        """Get the public preview URL for the sandbox."""
        if not self._sandbox:
            return None

        try:
            # Start dev server if needed
            await self.run_command("npm run dev &")

            # Wait for server to start
            import asyncio
            await asyncio.sleep(3)

            # Get URL
            url = self._sandbox.get_host(port)
            return f"https://{url}"

        except Exception as e:
            logger.warning("Failed to get preview URL", error=str(e))
            return None

    async def close(self):
        """Close and cleanup the sandbox."""
        if self._sandbox:
            try:
                self._sandbox.close()
                logger.info("E2B sandbox closed", sandbox_id=self._sandbox.id)
            except Exception as e:
                logger.warning("Error closing sandbox", error=str(e))
            finally:
                self._sandbox = None

    @asynccontextmanager
    async def session(
        self,
        template: str = "nextjs",
        files: Optional[dict[str, str]] = None,
        packages: Optional[list[str]] = None
    ):
        """
        Context manager for sandbox session.

        Usage:
            async with e2b_client.session(template="nextjs") as sandbox:
                await sandbox.write_file("page.tsx", code)
                url = await sandbox.get_preview_url()
        """
        try:
            await self.create_sandbox(template, files, packages)
            yield self
        finally:
            await self.close()


class E2BSandboxService:
    """
    High-level service for E2B sandbox operations.

    Provides convenient methods for mockup generation workflow.
    """

    def __init__(self, config: Optional[E2BMCPConfig] = None):
        self.config = config or E2BMCPConfig()
        self._client = E2BMCPClient(self.config)

    @property
    def is_available(self) -> bool:
        return self._client.is_available

    async def create_mockup_sandbox(
        self,
        template_name: str = "modern-professional",
        code_files: Optional[dict[str, str]] = None
    ) -> dict:
        """
        Create a sandbox configured for mockup generation.

        Args:
            template_name: Mockup template (modern-professional, etc.)
            code_files: Generated code files to deploy

        Returns:
            Dict with sandbox_id, preview_url
        """
        template_config = MOCKUP_TEMPLATES.get(template_name, MOCKUP_TEMPLATES["modern-professional"])

        # Create sandbox with appropriate base template
        result = await self._client.create_sandbox(
            template=template_config["base"],
            files=code_files,
            packages=template_config["packages"]
        )

        return result

    async def deploy_code(
        self,
        sandbox_id: str,
        files: dict[str, str]
    ) -> dict:
        """
        Deploy code files to an existing sandbox.

        Args:
            sandbox_id: Target sandbox ID
            files: Dict of filename -> content

        Returns:
            Dict with success status and preview_url
        """
        # Write all files
        for filename, content in files.items():
            result = await self._client.write_file(filename, content)
            if not result.get("success"):
                return result

        # Restart dev server
        await self._client.run_command("npm run dev &")

        return {
            "success": True,
            "files_deployed": list(files.keys()),
            "preview_url": await self._client._get_preview_url()
        }

    async def export_code(self, sandbox_id: str) -> dict:
        """
        Export all code files from sandbox.

        Args:
            sandbox_id: Sandbox to export from

        Returns:
            Dict with files content
        """
        # Define files to export
        export_files = [
            "app/page.tsx",
            "app/globals.css",
            "tailwind.config.js",
            "package.json"
        ]

        files = {}
        for filepath in export_files:
            result = await self._client.read_file(filepath)
            if result.get("success"):
                files[filepath] = result["content"]

        return {
            "success": True,
            "files": files
        }

    async def cleanup(self, sandbox_id: str):
        """Close and cleanup a sandbox."""
        await self._client.close()


# Convenience function
def create_e2b_service() -> E2BSandboxService:
    """Create an E2B sandbox service."""
    return E2BSandboxService()
