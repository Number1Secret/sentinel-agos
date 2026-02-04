"""
E2B Sandbox Service - High-level interface for E2B operations.

Provides:
- Sandbox lifecycle management
- Code deployment and preview
- Code export and storage
- Integration with Supabase Storage
"""
import os
import json
from dataclasses import dataclass
from typing import Optional, Any
from uuid import UUID

import structlog

logger = structlog.get_logger()


@dataclass
class SandboxInfo:
    """Information about an active sandbox."""
    sandbox_id: str
    preview_url: Optional[str]
    template: str
    created_at: str
    files: list[str]
    status: str  # 'running', 'stopped', 'error'


class E2BSandboxService:
    """
    Service for managing E2B sandboxes.

    Handles:
    - Creating sandboxes for mockup generation
    - Managing sandbox lifecycle
    - Saving generated code to storage
    - Tracking sandbox usage and costs
    """

    def __init__(
        self,
        supabase_service: Optional[Any] = None,
        api_key: Optional[str] = None
    ):
        self.db = supabase_service
        self._api_key = api_key or os.getenv("E2B_API_KEY")
        self._active_sandboxes: dict[str, Any] = {}

    @property
    def is_available(self) -> bool:
        """Check if E2B is configured and available."""
        return self._api_key is not None

    async def create_sandbox(
        self,
        template: str = "nextjs-developer",
        files: Optional[dict[str, str]] = None,
        timeout_minutes: int = 10
    ) -> dict:
        """
        Create a new E2B sandbox.

        Args:
            template: E2B template ID
            files: Initial files to write
            timeout_minutes: Sandbox timeout

        Returns:
            Dict with sandbox_id, preview_url, status
        """
        if not self.is_available:
            return {
                "success": False,
                "error": "E2B not configured - missing API key",
                "sandbox_id": None,
                "preview_url": None
            }

        try:
            from e2b_code_interpreter import Sandbox

            # Create sandbox
            sandbox = Sandbox(
                template=template,
                api_key=self._api_key,
                timeout=timeout_minutes * 60
            )

            sandbox_id = sandbox.id
            self._active_sandboxes[sandbox_id] = sandbox

            logger.info(
                "E2B sandbox created",
                sandbox_id=sandbox_id,
                template=template
            )

            # Write initial files
            if files:
                for path, content in files.items():
                    sandbox.files.write(path, content)
                    logger.debug("File written", sandbox_id=sandbox_id, path=path)

            # Start dev server for Next.js
            if "nextjs" in template:
                # Install dependencies first
                sandbox.commands.run("npm install")
                # Start dev server in background
                sandbox.commands.run("npm run dev &", background=True)

                # Wait for server to be ready
                import asyncio
                await asyncio.sleep(5)

            # Get preview URL
            preview_url = None
            try:
                host = sandbox.get_host(3000)
                preview_url = f"https://{host}"
            except Exception as e:
                logger.warning("Could not get preview URL", error=str(e))

            return {
                "success": True,
                "sandbox_id": sandbox_id,
                "preview_url": preview_url,
                "template": template
            }

        except ImportError:
            logger.error("E2B package not installed. Run: pip install e2b-code-interpreter")
            return {
                "success": False,
                "error": "E2B package not installed",
                "sandbox_id": None,
                "preview_url": None
            }

        except Exception as e:
            logger.error("Failed to create sandbox", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "sandbox_id": None,
                "preview_url": None
            }

    async def write_file(
        self,
        sandbox_id: str,
        path: str,
        content: str
    ) -> dict:
        """Write a file to a sandbox."""
        sandbox = self._active_sandboxes.get(sandbox_id)
        if not sandbox:
            return {"success": False, "error": "Sandbox not found"}

        try:
            sandbox.files.write(path, content)
            return {"success": True, "path": path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def read_file(
        self,
        sandbox_id: str,
        path: str
    ) -> dict:
        """Read a file from a sandbox."""
        sandbox = self._active_sandboxes.get(sandbox_id)
        if not sandbox:
            return {"success": False, "error": "Sandbox not found"}

        try:
            content = sandbox.files.read(path)
            return {"success": True, "content": content}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def run_command(
        self,
        sandbox_id: str,
        command: str
    ) -> dict:
        """Run a command in a sandbox."""
        sandbox = self._active_sandboxes.get(sandbox_id)
        if not sandbox:
            return {"success": False, "error": "Sandbox not found"}

        try:
            result = sandbox.commands.run(command)
            return {
                "success": result.exit_code == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_preview_url(
        self,
        sandbox_id: str,
        port: int = 3000
    ) -> Optional[str]:
        """Get the preview URL for a sandbox."""
        sandbox = self._active_sandboxes.get(sandbox_id)
        if not sandbox:
            return None

        try:
            host = sandbox.get_host(port)
            return f"https://{host}"
        except Exception:
            return None

    async def export_code(
        self,
        sandbox_id: str,
        include_paths: Optional[list[str]] = None
    ) -> dict:
        """
        Export code files from a sandbox.

        Args:
            sandbox_id: Sandbox to export from
            include_paths: Specific paths to include (or all if None)

        Returns:
            Dict with files content
        """
        sandbox = self._active_sandboxes.get(sandbox_id)
        if not sandbox:
            return {"success": False, "error": "Sandbox not found"}

        default_paths = [
            "app/page.tsx",
            "app/layout.tsx",
            "app/globals.css",
            "tailwind.config.js",
            "package.json",
            "tsconfig.json"
        ]

        paths_to_export = include_paths or default_paths
        files = {}

        for path in paths_to_export:
            try:
                content = sandbox.files.read(path)
                files[path] = content
            except Exception:
                # File doesn't exist, skip
                pass

        return {
            "success": True,
            "files": files,
            "file_count": len(files)
        }

    async def save_to_storage(
        self,
        sandbox_id: str,
        lead_id: UUID,
        bucket: str = "generated-code"
    ) -> dict:
        """
        Save sandbox code to Supabase Storage.

        Args:
            sandbox_id: Source sandbox
            lead_id: Lead to associate with
            bucket: Storage bucket name

        Returns:
            Dict with storage URLs
        """
        if not self.db:
            return {"success": False, "error": "Database service not configured"}

        # Export code
        export_result = await self.export_code(sandbox_id)
        if not export_result.get("success"):
            return export_result

        files = export_result.get("files", {})

        # Create a zip archive
        import io
        import zipfile

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for path, content in files.items():
                zf.writestr(path, content)

        zip_buffer.seek(0)
        zip_data = zip_buffer.read()

        # Upload to storage
        try:
            storage_path = f"{lead_id}/mockup-code.zip"
            self.db.client.storage.from_(bucket).upload(
                storage_path,
                zip_data,
                {"content-type": "application/zip"}
            )

            # Get public URL
            public_url = self.db.client.storage.from_(bucket).get_public_url(storage_path)

            logger.info(
                "Code saved to storage",
                lead_id=str(lead_id),
                path=storage_path
            )

            return {
                "success": True,
                "storage_path": storage_path,
                "public_url": public_url,
                "file_count": len(files)
            }

        except Exception as e:
            logger.error("Failed to save to storage", error=str(e))
            return {"success": False, "error": str(e)}

    async def close_sandbox(self, sandbox_id: str) -> dict:
        """Close and cleanup a sandbox."""
        sandbox = self._active_sandboxes.pop(sandbox_id, None)
        if not sandbox:
            return {"success": False, "error": "Sandbox not found"}

        try:
            sandbox.close()
            logger.info("Sandbox closed", sandbox_id=sandbox_id)
            return {"success": True}
        except Exception as e:
            logger.warning("Error closing sandbox", error=str(e))
            return {"success": False, "error": str(e)}

    async def close_all(self):
        """Close all active sandboxes."""
        for sandbox_id in list(self._active_sandboxes.keys()):
            await self.close_sandbox(sandbox_id)

    def get_active_sandboxes(self) -> list[str]:
        """Get list of active sandbox IDs."""
        return list(self._active_sandboxes.keys())


# Factory function
def create_e2b_service(supabase_service: Optional[Any] = None) -> E2BSandboxService:
    """Create an E2B sandbox service instance."""
    return E2BSandboxService(supabase_service=supabase_service)
