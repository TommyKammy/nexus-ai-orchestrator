"""
CodeSandbox - Secure sandbox for AI-generated code execution
Phase 1: Core Sandbox Infrastructure

This module provides Docker-based sandbox isolation for executing
untrusted code safely.
"""

import docker
import logging
import os
import re
import tarfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from io import BytesIO
from typing import Dict, List, Optional, Any, Union
from docker.types import Ulimit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


ContainerType = Any
DEFAULT_PIDS_LIMIT = 128
DEFAULT_NOFILE_LIMIT = 1024
DEFAULT_NPROC_LIMIT = 256


class CodeSandbox:
    """Secure sandbox for executing code in isolated Docker containers."""
    
    def __init__(
        self,
        image: str = "executor-sandbox:latest",
        timeout: int = 30,
        memory_limit: str = "512m",
        cpu_quota: int = 100000,
        network_disabled: bool = True
    ):
        """
        Initialize sandbox configuration.
        
        Args:
            image: Docker image for sandbox
            timeout: Maximum execution time in seconds
            memory_limit: Memory limit (e.g., '512m', '1g')
            cpu_quota: CPU quota (100000 = 1 core)
            network_disabled: Whether to disable network access
        """
        if timeout < 1 or timeout > 3600:
            raise ValueError("timeout must be between 1 and 3600 seconds")
        if not isinstance(memory_limit, str) or not re.match(r"^\d+[mMgG]$", memory_limit):
            raise ValueError("memory_limit must match format like '512m' or '1g'")
        if int(memory_limit[:-1]) <= 0:
            raise ValueError("memory_limit must be greater than 0 (e.g., '512m' or '1g')")
        if cpu_quota <= 0:
            raise ValueError("cpu_quota must be greater than 0")

        self.image = image
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.cpu_quota = cpu_quota
        self.network_disabled = network_disabled
        self.container: Optional[ContainerType] = None
        self.container_id: str = str(uuid.uuid4())[:8]
        
        try:
            self.client = docker.from_env()
            logger.info("Docker client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            raise
    
    def create(self) -> 'CodeSandbox':
        """
        Create and start a new sandbox container.
        
        Returns:
            self for method chaining
        """
        try:
            logger.info(f"Creating sandbox container: sandbox-{self.container_id}")
            
            # Container configuration
            container_config = {
                "image": self.image,
                "name": f"sandbox-{self.container_id}",
                "detach": True,
                "tty": True,
                "stdin_open": True,
                "mem_limit": self.memory_limit,
                "memswap_limit": self.memory_limit,
                "cpu_quota": self.cpu_quota,
                "cpu_period": 100000,
                "pids_limit": DEFAULT_PIDS_LIMIT,
                "network_disabled": self.network_disabled,
                "read_only": True,
                "security_opt": ["no-new-privileges:true"],
                "cap_drop": ["ALL"],
                "cap_add": [],
                "ulimits": [
                    Ulimit(name="nofile", soft=DEFAULT_NOFILE_LIMIT, hard=DEFAULT_NOFILE_LIMIT),
                    Ulimit(name="nproc", soft=DEFAULT_NPROC_LIMIT, hard=DEFAULT_NPROC_LIMIT),
                ],
                "tmpfs": {
                    "/tmp": "rw,noexec,nosuid,size=100m,uid=1000,gid=1000",
                    "/workspace": "rw,exec,nosuid,size=50m,uid=1000,gid=1000"
                },
                "environment": {
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONUNBUFFERED": "1",
                    "MPLBACKEND": "Agg",
                    "HOME": "/workspace"
                },
                "working_dir": "/workspace",
                "user": "sandbox"
            }
            
            # Add DNS if network is enabled
            if not self.network_disabled:
                container_config["dns"] = ["8.8.8.8", "1.1.1.1"]
            
            self.container = self.client.containers.run(**container_config)
            container_id = str(self.container.id) if self.container else "unknown"
            logger.info(f"Sandbox container created: {container_id[:12]}")
            
            # Wait for container to be ready
            time.sleep(0.5)
            
            return self
            
        except Exception as e:
            logger.error(f"Failed to create sandbox: {e}")
            self.destroy()
            raise
    
    def run_code(
        self,
        code: str,
        language: str = "python",
        files: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Execute code in the sandbox.
        
        Args:
            code: Code to execute
            language: Programming language ('python' only in Phase 1)
            files: Optional dict of filename -> content to upload
        
        Returns:
            Dict with stdout, stderr, exit_code, execution_time, etc.
        """
        if not self.container:
            raise RuntimeError("Sandbox not created. Call create() first.")
        
        start_time = time.time()
        
        try:
            # Upload files if provided
            if files:
                for filename, content in files.items():
                    self.write_file(filename, content)
            
            # Prepare execution command and source file
            try:
                cmd, source_path = self._prepare_execution(language, code)
            except ValueError:
                # Keep API behavior explicit for invalid language inputs.
                raise
            if source_path:
                if not self.write_file(source_path, code):
                    raise RuntimeError(f"Failed to write source file: {source_path}")
            
            logger.info(f"Executing code in sandbox-{self.container_id}")
            
            # Execute with enforced timeout
            result = self._exec_run_with_timeout(cmd)
            
            execution_time = time.time() - start_time
            
            # Parse output
            stdout = ""
            stderr = ""
            
            if result.output:
                stdout_bytes, stderr_bytes = result.output
                if stdout_bytes:
                    stdout = stdout_bytes.decode('utf-8', errors='replace')
                if stderr_bytes:
                    stderr = stderr_bytes.decode('utf-8', errors='replace')
            
            response = {
                "status": "success" if result.exit_code == 0 else "error",
                "exit_code": result.exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "execution_time": round(execution_time, 3),
                "container_id": self.container_id,
                "language": language
            }
            
            logger.info(f"Code execution completed in {execution_time:.3f}s")
            return response
            
        except ValueError:
            raise
        except SandboxTimeoutError as e:
            logger.error(f"Code execution timed out: {e}")
            return {
                "status": "error",
                "error": str(e),
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "execution_time": time.time() - start_time,
                "container_id": self.container_id,
                "language": language,
            }
        except Exception as e:
            logger.error(f"Code execution failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "execution_time": time.time() - start_time,
                "container_id": self.container_id,
                "language": language
            }

    def _prepare_execution(self, language: str, code: str) -> tuple[List[str], str]:
        """Build execution command for the requested language."""
        lang = (language or "").strip().lower()
        if lang == "python":
            return ["python", "main.py"], "main.py"
        if lang in ("node", "javascript", "js"):
            return ["node", "main.js"], "main.js"
        if lang in ("r", "rscript"):
            return ["Rscript", "main.R"], "main.R"
        if lang in ("bash", "sh", "shell"):
            return ["sh", "main.sh"], "main.sh"
        if lang == "go":
            return ["sh", "-lc", "go run main.go"], "main.go"
        if lang in ("rust", "rs"):
            return ["sh", "-lc", "rustc main.rs -O -o main && ./main"], "main.rs"
        if lang == "java":
            return ["sh", "-lc", "javac Main.java && java Main"], "Main.java"
        if lang in ("cpp", "c++"):
            return ["sh", "-lc", "g++ main.cpp -O2 -o main && ./main"], "main.cpp"
        raise ValueError(f"Unsupported language: {language}")

    def _exec_run_with_timeout(self, cmd: List[str]):
        """Execute container command with hard timeout enforcement."""
        if not self.container:
            raise RuntimeError("Sandbox not created")

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            self.container.exec_run,
            cmd,
            workdir="/workspace",
            user="sandbox",
            demux=True,
            tty=False,
        )
        try:
            return future.result(timeout=self.timeout)
        except FuturesTimeoutError as exc:
            future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            try:
                # Force-stop on timeout so runaway code cannot continue.
                self.destroy()
            finally:
                pass
            raise SandboxTimeoutError(f"Execution exceeded timeout ({self.timeout}s)") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    
    def write_file(self, path: str, content: str) -> bool:
        """
        Write a file to the sandbox.
        
        Args:
            path: File path (relative to /workspace)
            content: File content
        
        Returns:
            True if successful
        """
        if not self.container:
            raise RuntimeError("Sandbox not created")
        
        try:
            # Ensure path is relative and safe
            safe_path = os.path.normpath(path).lstrip('/')
            if '..' in safe_path or safe_path.startswith('/'):
                raise ValueError(f"Invalid path: {path}")
            
            # Create tar archive
            tar_stream = BytesIO()
            with tarfile.open(fileobj=tar_stream, mode='w') as tar:
                data = content.encode('utf-8')
                info = tarfile.TarInfo(name=safe_path)
                info.size = len(data)
                info.uid = 1000  # sandbox user
                info.gid = 1000
                info.mtime = time.time()
                tar.addfile(info, BytesIO(data))
            
            tar_stream.seek(0)
            
            # Upload to container
            success = self.container.put_archive('/workspace', tar_stream)
            
            if success:
                logger.debug(f"File written: /workspace/{safe_path}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to write file: {e}")
            return False
    
    def read_file(self, path: str) -> Optional[str]:
        """
        Read a file from the sandbox.
        
        Args:
            path: File path (relative to /workspace)
        
        Returns:
            File content or None if not found
        """
        if not self.container:
            raise RuntimeError("Sandbox not created")
        
        try:
            # Ensure path is relative and safe
            safe_path = os.path.normpath(path).lstrip('/')
            if '..' in safe_path or safe_path.startswith('/'):
                raise ValueError(f"Invalid path: {path}")
            
            full_path = f"/workspace/{safe_path}"
            
            # Get file from container
            bits, stat = self.container.get_archive(full_path)
            
            if not bits:
                return None
            
            # Extract content from tar
            file_buffer = BytesIO()
            for chunk in bits:
                file_buffer.write(chunk)
            file_buffer.seek(0)
            
            with tarfile.open(fileobj=file_buffer, mode='r') as tar:
                member = tar.getmembers()[0]
                extracted = tar.extractfile(member)
                if extracted is None:
                    return None
                content = extracted.read()
                return content.decode('utf-8', errors='replace')
                
        except Exception as e:
            logger.error(f"Failed to read file: {e}")
            return None
    
    def install_packages(self, packages: List[str]) -> Dict[str, Any]:
        """
        Install Python packages in the sandbox.
        
        Args:
            packages: List of package names
        
        Returns:
            Installation result
        """
        if not self.container:
            raise RuntimeError("Sandbox not created")
        
        try:
            logger.info(f"Installing packages: {packages}")
            
            cmd = ["pip", "install", "--user", "--no-cache-dir"] + packages
            
            result = self.container.exec_run(
                cmd,
                workdir="/workspace",
                user="sandbox",
                demux=True
            )
            
            stdout = ""
            stderr = ""
            
            if result.output:
                stdout_bytes, stderr_bytes = result.output
                if stdout_bytes:
                    stdout = stdout_bytes.decode('utf-8', errors='replace')
                if stderr_bytes:
                    stderr = stderr_bytes.decode('utf-8', errors='replace')
            
            return {
                "status": "success" if result.exit_code == 0 else "error",
                "exit_code": result.exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "packages": packages
            }
            
        except Exception as e:
            logger.error(f"Package installation failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "packages": packages
            }
    
    def destroy(self) -> None:
        """
        Destroy the sandbox container and clean up resources.
        """
        if self.container:
            try:
                logger.info(f"Destroying sandbox-{self.container_id}")
                self.container.stop(timeout=1)
                self.container.remove(force=True)
                logger.info(f"Sandbox-{self.container_id} destroyed")
            except Exception as e:
                logger.warning(f"Error destroying sandbox: {e}")
            finally:
                self.container = None
    
    def __enter__(self) -> 'CodeSandbox':
        """Context manager entry."""
        return self.create()
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.destroy()


class SandboxError(Exception):
    """Base exception for sandbox errors."""
    pass


class SandboxTimeoutError(SandboxError):
    """Raised when code execution times out."""
    pass


class SandboxSecurityError(SandboxError):
    """Raised when a security violation is detected."""
    pass
