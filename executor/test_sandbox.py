"""
Unit tests for CodeSandbox
Phase 1: Core Sandbox Infrastructure
"""

import json
import pytest
from concurrent.futures import TimeoutError as FuturesTimeoutError
from unittest.mock import Mock, patch, MagicMock
from executor.sandbox import CodeSandbox, SandboxError, SandboxTimeoutError


class TestCodeSandbox:
    """Test suite for CodeSandbox class."""
    
    @pytest.fixture
    def mock_docker_client(self):
        """Create a mock Docker client."""
        with patch('executor.sandbox.docker.from_env') as mock_from_env:
            mock_client = Mock()
            mock_from_env.return_value = mock_client
            yield mock_client
    
    @pytest.fixture
    def sandbox(self, mock_docker_client):
        """Create a CodeSandbox instance with mocked Docker."""
        return CodeSandbox()
    
    def test_init(self, mock_docker_client):
        """Test sandbox initialization."""
        sandbox = CodeSandbox()
        
        assert sandbox.image == "executor-sandbox:latest"
        assert sandbox.timeout == 30
        assert sandbox.memory_limit == "512m"
        assert sandbox.cpu_quota == 100000
        assert sandbox.network_disabled is True
        assert sandbox.container is None
        assert len(sandbox.container_id) == 8
    
    def test_init_custom_params(self, mock_docker_client):
        """Test sandbox initialization with custom parameters."""
        sandbox = CodeSandbox(
            image="custom-image",
            timeout=60,
            memory_limit="1g",
            cpu_quota=200000,
            network_disabled=False
        )
        
        assert sandbox.image == "custom-image"
        assert sandbox.timeout == 60
        assert sandbox.memory_limit == "1g"
        assert sandbox.cpu_quota == 200000
        assert sandbox.network_disabled is False
    
    def test_create_success(self, mock_docker_client, sandbox):
        """Test successful container creation."""
        mock_container = Mock()
        mock_container.id = "abc123def456"
        mock_docker_client.containers.run.return_value = mock_container
        
        result = sandbox.create()
        
        assert result == sandbox
        assert sandbox.container == mock_container
        mock_docker_client.containers.run.assert_called_once()
        
        # Verify container config
        call_args = mock_docker_client.containers.run.call_args
        assert call_args[1]['image'] == "executor-sandbox:latest"
        assert call_args[1]['mem_limit'] == "512m"
        assert call_args[1]['network_disabled'] is True
        assert call_args[1]['read_only'] is True
    
    def test_create_failure(self, mock_docker_client, sandbox):
        """Test container creation failure."""
        mock_docker_client.containers.run.side_effect = Exception("Docker error")
        
        with pytest.raises(Exception, match="Docker error"):
            sandbox.create()
    
    def test_destroy(self, mock_docker_client, sandbox):
        """Test container destruction."""
        mock_container = Mock()
        sandbox.container = mock_container
        
        sandbox.destroy()
        
        mock_container.stop.assert_called_once_with(timeout=1)
        mock_container.remove.assert_called_once_with(force=True)
        assert sandbox.container is None
    
    def test_destroy_no_container(self, mock_docker_client, sandbox):
        """Test destroy when no container exists."""
        sandbox.container = None
        
        # Should not raise
        sandbox.destroy()
    
    def test_run_code_success(self, mock_docker_client, sandbox):
        """Test successful code execution."""
        mock_container = Mock()
        mock_container.exec_run.return_value = Mock(
            exit_code=0,
            output=(b"Hello World", b"")
        )
        sandbox.container = mock_container
        
        result = sandbox.run_code("print('Hello World')")
        
        assert result['status'] == "success"
        assert result['exit_code'] == 0
        assert result['stdout'] == "Hello World"
        assert result['stderr'] == ""
        assert result['language'] == "python"
        assert 'execution_time' in result
    
    def test_run_code_with_error(self, mock_docker_client, sandbox):
        """Test code execution with error."""
        mock_container = Mock()
        mock_container.exec_run.return_value = Mock(
            exit_code=1,
            output=(b"", b"SyntaxError: invalid syntax")
        )
        sandbox.container = mock_container
        
        result = sandbox.run_code("invalid syntax")
        
        assert result['status'] == "error"
        assert result['exit_code'] == 1
        assert "SyntaxError" in result['stderr']

    def test_run_code_timeout_returns_error(self, mock_docker_client, sandbox):
        """Test run_code timeout handling."""
        mock_container = Mock()
        sandbox.container = mock_container

        with patch.object(sandbox, "_exec_run_with_timeout", side_effect=SandboxTimeoutError("timeout")):
            result = sandbox.run_code("while True: pass")

        assert result["status"] == "error"
        assert result["exit_code"] == -1
        assert "timeout" in result["error"]

    def test_exec_run_with_timeout_destroys_sandbox(self, mock_docker_client, sandbox):
        """Test timeout enforcement and cleanup during exec_run."""
        mock_container = Mock()
        sandbox.container = mock_container
        sandbox.timeout = 1

        mock_future = Mock()
        mock_future.result.side_effect = FuturesTimeoutError()
        mock_executor = Mock()
        mock_executor.submit.return_value = mock_future

        with patch("executor.sandbox.ThreadPoolExecutor", return_value=mock_executor), patch.object(
            sandbox, "destroy"
        ) as mock_destroy:
            with pytest.raises(SandboxTimeoutError):
                sandbox._exec_run_with_timeout(["python", "main.py"])

        mock_destroy.assert_called_once()
    
    def test_run_code_no_container(self, mock_docker_client, sandbox):
        """Test run_code when container not created."""
        sandbox.container = None
        
        with pytest.raises(RuntimeError, match="Sandbox not created"):
            sandbox.run_code("print('test')")
    
    def test_run_code_unsupported_language(self, mock_docker_client, sandbox):
        """Test run_code with unsupported language."""
        mock_container = Mock()
        sandbox.container = mock_container
        
        with pytest.raises(ValueError, match="Unsupported language: ruby"):
            sandbox.run_code("puts 'test'", language="ruby")
    
    def test_write_file_success(self, mock_docker_client, sandbox):
        """Test successful file write."""
        mock_container = Mock()
        mock_container.put_archive.return_value = True
        sandbox.container = mock_container
        
        result = sandbox.write_file("test.py", "print('hello')")
        
        assert result is True
        mock_container.put_archive.assert_called_once()
    
    def test_write_file_invalid_path(self, mock_docker_client, sandbox):
        """Test write_file with invalid path."""
        mock_container = Mock()
        sandbox.container = mock_container
        
        result = sandbox.write_file("../etc/passwd", "evil")
        
        assert result is False
    
    def test_read_file_success(self, mock_docker_client, sandbox):
        """Test successful file read."""
        import tarfile
        from io import BytesIO
        
        mock_container = Mock()
        
        # Create a tar archive with test content
        tar_buffer = BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
            content = b"print('hello')"
            info = tarfile.TarInfo(name="test.py")
            info.size = len(content)
            tar.addfile(info, BytesIO(content))
        tar_buffer.seek(0)
        
        mock_container.get_archive.return_value = (iter([tar_buffer.read()]), None)
        sandbox.container = mock_container
        
        result = sandbox.read_file("test.py")
        
        assert result == "print('hello')"
    
    def test_read_file_not_found(self, mock_docker_client, sandbox):
        """Test read_file when file doesn't exist."""
        mock_container = Mock()
        mock_container.get_archive.side_effect = Exception("File not found")
        sandbox.container = mock_container
        
        result = sandbox.read_file("nonexistent.py")
        
        assert result is None
    
    def test_install_packages_success(self, mock_docker_client, sandbox):
        """Test successful package installation."""
        mock_container = Mock()
        mock_container.exec_run.return_value = Mock(
            exit_code=0,
            output=(b"Successfully installed numpy", b"")
        )
        sandbox.container = mock_container
        
        result = sandbox.install_packages(["numpy", "pandas"])
        
        assert result['status'] == "success"
        assert result['exit_code'] == 0
        assert result['packages'] == ["numpy", "pandas"]
    
    def test_context_manager(self, mock_docker_client):
        """Test context manager usage."""
        mock_container = Mock()
        mock_docker_client.containers.run.return_value = mock_container
        
        with CodeSandbox() as sandbox:
            assert sandbox.container is not None
        
        # Verify cleanup
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()


class TestSecurity:
    """Security-related tests."""
    
    @pytest.fixture
    def mock_docker_client(self):
        """Create a mock Docker client."""
        with patch('executor.sandbox.docker.from_env') as mock_from_env:
            mock_client = Mock()
            mock_from_env.return_value = mock_client
            yield mock_client
    
    def test_container_config_security(self, mock_docker_client):
        """Test that container is configured securely."""
        sandbox = CodeSandbox()
        mock_container = Mock()
        mock_docker_client.containers.run.return_value = mock_container
        
        sandbox.create()
        
        call_args = mock_docker_client.containers.run.call_args
        config = call_args[1]
        
        # Security checks
        assert config['read_only'] is True
        assert config['network_disabled'] is True
        assert config['security_opt'] == ["no-new-privileges:true"]
        assert config['cap_drop'] == ["ALL"]
        assert 'cap_add' in config
        assert config['user'] == "sandbox"
        assert 'tmpfs' in config
    
    def test_resource_limits(self, mock_docker_client):
        """Test resource limits are enforced."""
        sandbox = CodeSandbox(memory_limit="256m", cpu_quota=50000)
        mock_container = Mock()
        mock_docker_client.containers.run.return_value = mock_container
        
        sandbox.create()
        
        call_args = mock_docker_client.containers.run.call_args
        config = call_args[1]
        
        assert config['mem_limit'] == "256m"
        assert config['memswap_limit'] == "256m"
        assert config['cpu_quota'] == 50000
        assert config['cpu_period'] == 100000
        assert config['pids_limit'] == 128
        ulimits = {u.name: u for u in config["ulimits"]}
        assert "nofile" in ulimits
        assert "nproc" in ulimits
        assert ulimits["nofile"].soft == 1024
        assert ulimits["nproc"].hard == 256

    def test_invalid_timeout_rejected(self, mock_docker_client):
        with pytest.raises(ValueError, match="timeout must be between 1 and 3600 seconds"):
            CodeSandbox(timeout=0)

    def test_invalid_memory_limit_rejected(self, mock_docker_client):
        with pytest.raises(ValueError, match="memory_limit must match format"):
            CodeSandbox(memory_limit="1024")

    def test_invalid_memory_limit_zero_rejected(self, mock_docker_client):
        with pytest.raises(ValueError, match="memory_limit must be greater than 0"):
            CodeSandbox(memory_limit="0m")

    def test_invalid_cpu_quota_rejected(self, mock_docker_client):
        with pytest.raises(ValueError, match="cpu_quota must be greater than 0"):
            CodeSandbox(cpu_quota=0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
