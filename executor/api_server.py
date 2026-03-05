"""
Executor API Server for n8n integration
Phase 2: Sandbox Integration

Provides HTTP API for sandbox execution that can be called from n8n.
"""

import json
import logging
import os
import time
import uuid
from typing import Dict, Any, Optional
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import threading

# Import our sandbox modules
from executor.sandbox import CodeSandbox
from executor.session import SessionManager
from executor.filesystem import FileSystemManager
from executor.templates import template_manager
from executor.policy_client import PolicyClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Security configuration
API_KEY = os.environ.get('EXECUTOR_API_KEY')
PRODUCTION_MODE = os.environ.get('EXECUTOR_PRODUCTION', 'false').lower() == 'true'

# Global session manager
session_manager = SessionManager(
    default_ttl=300,
    max_sessions=10,
    enable_cleanup_thread=True
)
policy_client = PolicyClient()
POLICY_METRICS = {
    "total": 0,
    "allow": 0,
    "deny": 0,
    "requires_approval": 0,
    "errors": 0,
    "latency_ms_sum": 0.0,
    "latency_ms_count": 0,
}
REQUEST_METRICS = {
    "total": 0,
    "errors": 0,
    "latency_ms_sum": 0.0,
    "latency_ms_count": 0,
    "methods": {},
    "statuses": {},
}


def sanitize_error(error: str) -> str:
    """
    Sanitize error messages for production.
    
    Args:
        error: Original error message
    
    Returns:
        Sanitized error message
    """
    if not PRODUCTION_MODE:
        return error
    
    # In production, don't expose internal details
    error_lower = error.lower()
    if any(sensitive in error_lower for sensitive in [
        'password', 'secret', 'key', 'token', 'credential', 
        '/workspace', '/tmp', 'container', 'docker'
    ]):
        return "Internal server error"
    
    # Generic error mapping
    if 'permission' in error_lower or 'access' in error_lower:
        return "Access denied"
    if 'not found' in error_lower or 'no such' in error_lower:
        return "Resource not found"
    
    return "Request failed"


class ExecutorHandler(BaseHTTPRequestHandler):
    """HTTP request handler for executor API."""

    GET_ROUTES = {
        "/": "_handle_get_root",
        "/health": "_handle_get_health",
        "/capabilities": "_handle_get_capabilities",
        "/templates": "_handle_get_templates",
        "/sessions": "_handle_get_sessions",
        "/metrics": "_handle_get_metrics",
        "/metrics/prometheus": "_handle_get_metrics_prometheus",
    }

    POST_ROUTES = {
        "/execute": "_handle_execute",
        "/session/create": "_handle_create_session",
        "/session/destroy": "_handle_destroy_session",
        "/session/execute": "_handle_session_execute",
    }
    
    def log_message(self, format, *args):
        """Suppress default access log; application uses structured logging instead."""
        return

    def log_error(self, format, *args):
        """Emit structured logs for low-level HTTP/server errors."""
        try:
            message = format % args if args else str(format)
        except Exception:
            message = str(format)

        remote_addr = ""
        if getattr(self, "client_address", None):
            remote_addr = str(self.client_address[0])

        self._log_json(
            "error",
            {
                "event": "http_server_error",
                "message": message,
                "method": getattr(self, "command", ""),
                "path": getattr(self, "_request_path", getattr(self, "path", "")),
                "remote_addr": remote_addr,
                "request_id": getattr(self, "request_id", ""),
            },
        )

    def _assign_request_id(self):
        """Adopt inbound request ID or generate a new one."""
        inbound = self.headers.get("X-Request-ID", "")
        inbound = inbound.strip() if inbound else ""
        self.request_id = inbound or str(uuid.uuid4())

    def _request_latency_ms(self) -> float:
        started = getattr(self, "_request_started", None)
        if started is None:
            return 0.0
        return (time.monotonic() - started) * 1000.0

    def _log_json(self, level: str, payload: Dict[str, Any]):
        log_fn = getattr(logger, level, logger.info)
        log_fn(json.dumps(payload, separators=(",", ":"), sort_keys=True))

    def _log_access(self, method: str, path: str):
        status_code = int(getattr(self, "response_status_code", 0))
        latency_ms = round(self._request_latency_ms(), 3)

        REQUEST_METRICS["total"] += 1
        REQUEST_METRICS["latency_ms_sum"] += latency_ms
        REQUEST_METRICS["latency_ms_count"] += 1
        REQUEST_METRICS["methods"][method] = REQUEST_METRICS["methods"].get(method, 0) + 1
        status_key = str(status_code)
        REQUEST_METRICS["statuses"][status_key] = REQUEST_METRICS["statuses"].get(status_key, 0) + 1
        if status_code >= 400:
            REQUEST_METRICS["errors"] += 1

        self._log_json(
            "info",
            {
                "event": "request_complete",
                "latency_ms": latency_ms,
                "method": method,
                "path": path,
                "request_id": getattr(self, "request_id", ""),
                "status": status_code,
            },
        )
    
    def _check_auth(self) -> bool:
        """
        Check API key authentication if enabled.
        
        Returns:
            True if authenticated or auth not required
        """
        if not API_KEY:
            return True
        
        auth_header = self.headers.get('X-API-Key', '')
        if auth_header == API_KEY:
            return True
        
        self._log_json(
            "warning",
            {
                "event": "auth_failed",
                "method": getattr(self, "command", ""),
                "path": getattr(self, "_request_path", ""),
                "request_id": getattr(self, "request_id", ""),
                "source_ip": self.client_address[0],
                "status": 401,
            },
        )
        return False

    def send_response(self, code: int, message: Optional[str] = None):
        self.response_status_code = code
        super().send_response(code, message)
    
    def _send_security_headers(self):
        """Send security headers with response."""
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-XSS-Protection', '1; mode=block')
        self.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    
    def _send_json_response(self, data: Dict[str, Any], status: int = 200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        request_id = getattr(self, "request_id", None)
        if request_id:
            self.send_header("X-Request-ID", request_id)
        self._send_security_headers()
        body = json.dumps(data).encode('utf-8')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def _send_text_response(self, text: str, status: int = 200, content_type: str = "text/plain; version=0.0.4"):
        """Send plain text response (for Prometheus)."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        request_id = getattr(self, "request_id", None)
        if request_id:
            self.send_header("X-Request-ID", request_id)
        self._send_security_headers()
        body = text.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def _prometheus_metrics(self) -> str:
        """Build Prometheus exposition text."""
        latency_count = POLICY_METRICS["latency_ms_count"]
        latency_avg = POLICY_METRICS["latency_ms_sum"] / latency_count if latency_count else 0.0
        request_latency_count = REQUEST_METRICS["latency_ms_count"]
        request_latency_avg = REQUEST_METRICS["latency_ms_sum"] / request_latency_count if request_latency_count else 0.0
        lines = [
            "# HELP executor_policy_eval_total Total number of policy evaluations",
            "# TYPE executor_policy_eval_total counter",
            f'executor_policy_eval_total {POLICY_METRICS["total"]}',
            "# HELP executor_policy_decisions_total Total number of policy decisions",
            "# TYPE executor_policy_decisions_total counter",
            f'executor_policy_decisions_total{{decision="allow"}} {POLICY_METRICS["allow"]}',
            f'executor_policy_decisions_total{{decision="deny"}} {POLICY_METRICS["deny"]}',
            f'executor_policy_decisions_total{{decision="requires_approval"}} {POLICY_METRICS["requires_approval"]}',
            "# HELP executor_policy_eval_errors_total Total number of policy evaluation errors",
            "# TYPE executor_policy_eval_errors_total counter",
            f'executor_policy_eval_errors_total {POLICY_METRICS["errors"]}',
            "# HELP executor_policy_eval_latency_ms_sum Sum of policy evaluation latency in ms",
            "# TYPE executor_policy_eval_latency_ms_sum counter",
            f'executor_policy_eval_latency_ms_sum {POLICY_METRICS["latency_ms_sum"]:.3f}',
            "# HELP executor_policy_eval_latency_ms_count Number of policy evaluations with latency samples",
            "# TYPE executor_policy_eval_latency_ms_count counter",
            f"executor_policy_eval_latency_ms_count {latency_count}",
            "# HELP executor_policy_eval_latency_ms_avg Average policy evaluation latency in ms",
            "# TYPE executor_policy_eval_latency_ms_avg gauge",
            f"executor_policy_eval_latency_ms_avg {latency_avg:.3f}",
            "# HELP executor_http_requests_total Total number of HTTP requests",
            "# TYPE executor_http_requests_total counter",
            f'executor_http_requests_total {REQUEST_METRICS["total"]}',
            "# HELP executor_http_request_errors_total Total number of HTTP error responses (status >= 400)",
            "# TYPE executor_http_request_errors_total counter",
            f'executor_http_request_errors_total {REQUEST_METRICS["errors"]}',
            "# HELP executor_http_request_latency_ms_sum Sum of HTTP request latency in ms",
            "# TYPE executor_http_request_latency_ms_sum counter",
            f'executor_http_request_latency_ms_sum {REQUEST_METRICS["latency_ms_sum"]:.3f}',
            "# HELP executor_http_request_latency_ms_count Number of HTTP request latency samples",
            "# TYPE executor_http_request_latency_ms_count counter",
            f"executor_http_request_latency_ms_count {request_latency_count}",
            "# HELP executor_http_request_latency_ms_avg Average HTTP request latency in ms",
            "# TYPE executor_http_request_latency_ms_avg gauge",
            f"executor_http_request_latency_ms_avg {request_latency_avg:.3f}",
        ]
        for method in sorted(REQUEST_METRICS["methods"]):
            lines.append(
                f'executor_http_requests_by_method_total{{method="{method}"}} {REQUEST_METRICS["methods"][method]}'
            )
        for status in sorted(REQUEST_METRICS["statuses"]):
            lines.append(
                f'executor_http_requests_by_status_total{{status="{status}"}} {REQUEST_METRICS["statuses"][status]}'
            )
        return "\n".join(lines) + "\n"
    
    def _send_error(self, message: str, status: int = 400, log_error: bool = True):
        """Send error response."""
        if log_error:
            self._log_json(
                "warning",
                {
                    "error": message,
                    "event": "request_error",
                    "latency_ms": round(self._request_latency_ms(), 3),
                    "method": getattr(self, "command", ""),
                    "path": getattr(self, "_request_path", ""),
                    "request_id": getattr(self, "request_id", ""),
                    "status": int(status),
                },
            )
        
        # Sanitize error message for production
        sanitized = sanitize_error(message)
        self._send_json_response({"status": "error", "error": sanitized}, status)
    
    def _read_body(self) -> Dict[str, Any]:
        """Read and parse request body."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return {}
        
        body = self.rfile.read(content_length).decode('utf-8')
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    
    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        self._assign_request_id()
        self._request_path = path
        self._request_started = time.monotonic()
        self.response_status_code = 0

        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-API-Key, X-Request-ID')
        self.send_header("X-Request-ID", self.request_id)
        self._send_security_headers()
        self.end_headers()
        self._log_access("OPTIONS", path)
    
    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        self._assign_request_id()
        self._request_path = path
        self._request_started = time.monotonic()
        self.response_status_code = 0

        try:
            if not self._check_auth():
                self._send_error("Unauthorized", 401)
                return
            self._dispatch_get(path)
        except Exception as e:
            self._log_json(
                "error",
                {
                    "error": str(e),
                    "event": "request_exception",
                    "latency_ms": round(self._request_latency_ms(), 3),
                    "method": "GET",
                    "path": path,
                    "request_id": self.request_id,
                    "status": 500,
                },
            )
            self._send_error(f"Internal error: {sanitize_error(str(e))}", 500, log_error=False)
        finally:
            self._log_access("GET", path)
    
    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        self._assign_request_id()
        self._request_path = path
        self._request_started = time.monotonic()
        self.response_status_code = 0

        try:
            if not self._check_auth():
                self._send_error("Unauthorized", 401)
                return
            body = self._read_body()
            self._dispatch_post(path, body)
        except Exception as e:
            self._log_json(
                "error",
                {
                    "error": str(e),
                    "event": "request_exception",
                    "latency_ms": round(self._request_latency_ms(), 3),
                    "method": "POST",
                    "path": path,
                    "request_id": self.request_id,
                    "status": 500,
                },
            )
            self._send_error(f"Internal error: {sanitize_error(str(e))}", 500, log_error=False)
        finally:
            self._log_access("POST", path)

    def _dispatch_get(self, path: str):
        handler_name = self.GET_ROUTES.get(path)
        if not handler_name:
            self._send_error("Not found", 404)
            return
        getattr(self, handler_name)()

    def _dispatch_post(self, path: str, body: Dict[str, Any]):
        handler_name = self.POST_ROUTES.get(path)
        if not handler_name:
            self._send_error("Not found", 404)
            return
        getattr(self, handler_name)(body)

    def _handle_get_root(self):
        self._send_json_response({
            "status": "success",
            "service": "executor-api",
            "version": "2.0.0",
            "routes": {
                "get": sorted(self.GET_ROUTES.keys()),
                "post": sorted(self.POST_ROUTES.keys()),
            },
        })

    def _handle_get_health(self):
        self._send_json_response({
            "status": "healthy",
            "service": "executor-api",
            "version": "2.0.0"
        })

    def _handle_get_capabilities(self):
        self._send_json_response({
            "status": "success",
            "capabilities": {
                "interactive_execution": False,
                "snapshot_restore": False,
                "pause_resume": False,
                "supported_languages": [
                    "python",
                    "javascript",
                    "node",
                    "r",
                    "bash",
                    "sh",
                    "go",
                    "rust",
                    "java",
                    "cpp"
                ]
            }
        })

    def _handle_get_templates(self):
        templates = template_manager.list_templates()
        self._send_json_response({
            "status": "success",
            "templates": templates
        })

    def _handle_get_sessions(self):
        sessions = session_manager.list_sessions()
        self._send_json_response({
            "status": "success",
            "sessions": sessions
        })

    def _handle_get_metrics(self):
        metrics = session_manager.get_metrics()
        self._send_json_response({
            "status": "success",
            "metrics": {
                **metrics,
                "policy": POLICY_METRICS,
                "requests": REQUEST_METRICS,
            }
        })

    def _handle_get_metrics_prometheus(self):
        self._send_text_response(self._prometheus_metrics())

    def _evaluate_policy(
        self,
        action: str,
        subject: Dict[str, Any],
        resource: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        policy_input = {
            "subject": subject,
            "resource": resource,
            "action": action,
            "context": context
        }
        started = time.monotonic()
        result = policy_client.evaluate(policy_input)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        POLICY_METRICS["total"] += 1
        POLICY_METRICS["latency_ms_sum"] += elapsed_ms
        POLICY_METRICS["latency_ms_count"] += 1
        decision = str(result.get("decision", "deny"))
        if decision in ("allow", "deny", "requires_approval"):
            POLICY_METRICS[decision] += 1
        else:
            POLICY_METRICS["deny"] += 1
        if result.get("error"):
            POLICY_METRICS["errors"] += 1
        logger.info(
            "Policy decision request_id=%s action=%s decision=%s risk=%s latency_ms=%.2f reasons=%s error=%s",
            self.request_id,
            action,
            decision,
            result.get("risk_score"),
            elapsed_ms,
            ",".join(result.get("reasons", [])),
            result.get("error"),
        )
        return result

    def _enforce_or_respond(self, policy_result: Dict[str, Any]) -> bool:
        if policy_client.enforce(policy_result):
            return True

        decision = policy_result.get("decision", "deny")
        message = "Policy denied"
        if decision == "requires_approval":
            message = "Policy requires approval"

        self._send_json_response(
            {
                "status": "error",
                "error": message,
                "request_id": self.request_id,
                "policy": policy_result,
            },
            403,
        )
        return False
    
    def _handle_execute(self, body: Dict[str, Any]):
        """Handle direct code execution."""
        tenant_id = body.get('tenant_id')
        scope = body.get('scope')
        code = body.get('code')
        language = body.get('language', 'python')
        template = body.get('template', 'default')
        task_type = body.get('task_type', 'code_execution')
        files = body.get('files', {})
        
        if not all([tenant_id, scope, code]):
            self._send_error("Missing required fields: tenant_id, scope, code")
            return
        
        code = str(code)  # Ensure code is string
        
        # Get template configuration
        template_kwargs = template_manager.get_sandbox_kwargs(template)
        policy_result = self._evaluate_policy(
            action="executor.execute",
            subject={
                "tenant_id": tenant_id,
                "scope": scope,
                "role": "api",
            },
            resource={
                "tenant_id": tenant_id,
                "scope": scope,
                "template": template,
                "language": language,
                "task_type": task_type,
            },
            context={
                "request_id": self.request_id,
                "payload_size": len(code),
                "network_enabled": not template_kwargs.get("network_disabled", True),
            },
        )
        if not self._enforce_or_respond(policy_result):
            return
        
        try:
            with CodeSandbox(**template_kwargs) as sandbox:
                # Upload files if provided
                if files:
                    for path, content in files.items():
                        sandbox.write_file(path, content)
                
                # Execute code
                result = sandbox.run_code(code, language)
                
                response = {
                    "status": "success" if result['exit_code'] == 0 else "error",
                    "tenant_id": tenant_id,
                    "scope": scope,
                    "request_id": self.request_id,
                    "policy": policy_result,
                    "result": result
                }
                
                self._send_json_response(response)
                
        except Exception as e:
            logger.error(f"Execution failed: {e}")
            self._send_json_response({
                "status": "error",
                "tenant_id": tenant_id,
                "scope": scope,
                "request_id": self.request_id,
                "policy": policy_result,
                "error": sanitize_error(str(e))
            })
    
    def _handle_create_session(self, body: Dict[str, Any]):
        """Handle session creation."""
        tenant_id = body.get('tenant_id')
        scope = body.get('scope')
        template = body.get('template', 'default')
        ttl = body.get('ttl', 300)
        
        if not all([tenant_id, scope]):
            self._send_error("Missing required fields: tenant_id, scope")
            return
        
        try:
            # Get template configuration
            template_kwargs = template_manager.get_sandbox_kwargs(template)
            policy_result = self._evaluate_policy(
                action="executor.session.create",
                subject={
                    "tenant_id": tenant_id,
                    "scope": scope,
                    "role": "api",
                },
                resource={
                    "tenant_id": tenant_id,
                    "scope": scope,
                    "template": template,
                },
                context={
                    "request_id": self.request_id,
                    "ttl": ttl,
                    "network_enabled": not template_kwargs.get("network_disabled", True),
                },
            )
            if not self._enforce_or_respond(policy_result):
                return
            
            # Create session
            session_id = session_manager.create_session(
                template=template,
                ttl=ttl,
                metadata={
                    "tenant_id": tenant_id,
                    "scope": scope
                },
                **template_kwargs
            )
            
            self._send_json_response({
                "status": "success",
                "session_id": session_id,
                "template": template,
                "ttl": ttl,
                "request_id": self.request_id,
                "policy": policy_result,
            })
            
        except Exception as e:
            logger.error(f"Session creation failed: {e}")
            self._send_error(str(e))
    
    def _handle_destroy_session(self, body: Dict[str, Any]):
        """Handle session destruction."""
        session_id = body.get('session_id')
        
        if not session_id:
            self._send_error("Missing required field: session_id")
            return
        
        success = session_manager.destroy_session(session_id)
        
        if success:
            self._send_json_response({
                "status": "success",
                "message": f"Session {session_id} destroyed",
                "request_id": self.request_id,
            })
        else:
            self._send_json_response(
                {
                    "status": "error",
                    "error": f"Session {session_id} not found",
                    "request_id": self.request_id,
                },
                404,
            )
    
    def _handle_session_execute(self, body: Dict[str, Any]):
        """Handle execution in existing session."""
        session_id = body.get('session_id')
        code = body.get('code')
        language = body.get('language', 'python')
        files = body.get('files', {})
        
        if not all([session_id, code]):
            self._send_error("Missing required fields: session_id, code")
            return

        session = session_manager.get_session(session_id)
        scope = ""
        tenant_id = ""
        template = ""
        if session:
            scope = str(session.metadata.get("scope", ""))
            tenant_id = str(session.metadata.get("tenant_id", ""))
            template = session.template
        policy_result = self._evaluate_policy(
            action="executor.session.execute",
            subject={
                "tenant_id": tenant_id,
                "scope": scope,
                "role": "api",
            },
            resource={
                "session_id": session_id,
                "tenant_id": tenant_id,
                "scope": scope,
                "template": template,
            },
            context={
                "request_id": self.request_id,
                "payload_size": len(str(code)),
            },
        )
        if not self._enforce_or_respond(policy_result):
            return
        
        result = session_manager.execute_in_session(
            session_id, code, language, files
        )
        result["request_id"] = self.request_id
        result["policy"] = policy_result
        if result.get("status") == "error" and "not found or expired" in str(result.get("error", "")).lower():
            self._send_json_response(result, 404)
            return
        self._send_json_response(result)


def start_server(host: str = '0.0.0.0', port: int = 8080):
    """
    Start the executor API server.
    
    Args:
        host: Host to bind to
        port: Port to listen on
    """
    server = HTTPServer((host, port), ExecutorHandler)
    logger.info(f"Executor API server started on {host}:{port}")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        session_manager.stop()
        server.shutdown()


if __name__ == "__main__":
    # Get port from environment or use default
    port = int(os.environ.get('EXECUTOR_PORT', 8080))
    start_server(port=port)
