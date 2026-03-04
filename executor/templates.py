"""
Template system for pre-configured sandbox environments
Phase 2: Environment Templates

Provides pre-configured environments with specific packages,
settings, and initialization for common use cases.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class SandboxTemplate:
    """Definition of a sandbox environment template."""
    
    name: str
    description: str
    base_image: str
    packages: List[str] = field(default_factory=list)
    environment_variables: Dict[str, str] = field(default_factory=dict)
    setup_commands: List[str] = field(default_factory=list)
    memory_limit: str = "512m"
    cpu_quota: int = 100000
    timeout: int = 30
    network_enabled: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert template to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SandboxTemplate':
        """Create template from dictionary."""
        return cls(**data)


# Built-in templates
BUILTIN_TEMPLATES: Dict[str, SandboxTemplate] = {
    "default": SandboxTemplate(
        name="default",
        description="Default Python sandbox with essential packages",
        base_image="executor-sandbox:latest",
        packages=[],
        memory_limit="512m",
        cpu_quota=100000,
        timeout=30
    ),
    
    "python-data": SandboxTemplate(
        name="python-data",
        description="Python data science environment",
        base_image="executor-sandbox:latest",
        packages=[
            "pandas==2.2.0",
            "numpy==1.26.4",
            "matplotlib==3.8.3",
            "seaborn==0.13.2",
            "scipy==1.12.0",
            "scikit-learn==1.4.0",
            "openpyxl==3.1.2",
            "xlrd==2.0.1"
        ],
        environment_variables={
            "MPLBACKEND": "Agg",
            "PYTHONDONTWRITEBYTECODE": "1"
        },
        memory_limit="1g",
        cpu_quota=100000,
        timeout=60
    ),
    
    "python-ml": SandboxTemplate(
        name="python-ml",
        description="Python machine learning environment",
        base_image="executor-sandbox:latest",
        packages=[
            "torch==2.2.0",
            "transformers==4.37.2",
            "datasets==2.16.1",
            "accelerate==0.26.1",
            "numpy==1.26.4",
            "pandas==2.2.0",
            "matplotlib==3.8.3",
            "seaborn==0.13.2",
            "scikit-learn==1.4.0",
            "tqdm==4.66.1"
        ],
        environment_variables={
            "MPLBACKEND": "Agg",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TRANSFORMERS_CACHE": "/tmp/transformers_cache",
            "HF_HOME": "/tmp/huggingface"
        },
        memory_limit="2g",
        cpu_quota=200000,
        timeout=120
    ),
    
    "python-nlp": SandboxTemplate(
        name="python-nlp",
        description="Natural Language Processing environment",
        base_image="executor-sandbox:latest",
        packages=[
            "nltk==3.8.1",
            "spacy==3.7.2",
            "textblob==0.17.1",
            "gensim==4.3.2",
            "pandas==2.2.0",
            "numpy==1.26.4",
            "matplotlib==3.8.3"
        ],
        setup_commands=[
            "python -m nltk.downloader punkt -d /tmp/nltk_data",
            "python -m nltk.downloader stopwords -d /tmp/nltk_data"
        ],
        memory_limit="1g",
        cpu_quota=100000,
        timeout=60
    ),
    
    "python-web": SandboxTemplate(
        name="python-web",
        description="Web scraping and HTTP requests",
        base_image="executor-sandbox:latest",
        packages=[
            "requests==2.31.0",
            "beautifulsoup4==4.12.3",
            "lxml==5.1.0",
            "selenium==4.17.2",
            "scrapy==2.11.0",
            "pandas==2.2.0"
        ],
        environment_variables={
            "PYTHONDONTWRITEBYTECODE": "1"
        },
        memory_limit="512m",
        cpu_quota=100000,
        timeout=60,
        network_enabled=True  # Network required for web scraping
    ),
    
    "node-basic": SandboxTemplate(
        name="node-basic",
        description="Node.js basic environment",
        base_image="node:18-slim",
        packages=[],  # npm packages installed separately
        environment_variables={
            "NODE_ENV": "production",
            "npm_config_cache": "/tmp/npm-cache"
        },
        memory_limit="512m",
        cpu_quota=100000,
        timeout=30
    ),
    
    "minimal": SandboxTemplate(
        name="minimal",
        description="Minimal environment with no extra packages",
        base_image="python:3.11-slim",
        packages=[],
        memory_limit="256m",
        cpu_quota=50000,
        timeout=30
    ),
    
    # Additional language templates
    "r-stats": SandboxTemplate(
        name="r-stats",
        description="R statistical computing environment",
        base_image="r-base:4.3.0",
        packages=[
            "ggplot2",
            "dplyr",
            "tidyr",
            "readr",
            "purrr",
            "tibble",
            "stringr",
            "forcats"
        ],
        setup_commands=[
            "R -e \"install.packages(c('ggplot2', 'dplyr', 'tidyr', 'readr', 'purrr', 'tibble', 'stringr', 'forcats'), repos='http://cran.rstudio.com/')\""
        ],
        memory_limit="1g",
        cpu_quota=100000,
        timeout=60
    ),
    
    "go-basic": SandboxTemplate(
        name="go-basic",
        description="Go programming environment",
        base_image="golang:1.21-alpine",
        packages=[],
        environment_variables={
            "GOPATH": "/go",
            "GOCACHE": "/tmp/go-cache"
        },
        memory_limit="512m",
        cpu_quota=100000,
        timeout=30
    ),
    
    "rust-basic": SandboxTemplate(
        name="rust-basic",
        description="Rust programming environment",
        base_image="rust:1.75-slim",
        packages=[],
        environment_variables={
            "CARGO_HOME": "/tmp/cargo",
            "RUSTUP_HOME": "/tmp/rustup"
        },
        memory_limit="1g",
        cpu_quota=100000,
        timeout=60
    ),
    
    "java-basic": SandboxTemplate(
        name="java-basic",
        description="Java programming environment",
        base_image="openjdk:21-slim",
        packages=[],
        environment_variables={
            "JAVA_HOME": "/usr/local/openjdk-21"
        },
        memory_limit="1g",
        cpu_quota=100000,
        timeout=45
    ),
    
    "cpp-basic": SandboxTemplate(
        name="cpp-basic",
        description="C++ programming environment with GCC",
        base_image="gcc:13.2",
        packages=[],
        setup_commands=[
            "apt-get update && apt-get install -y cmake"
        ],
        memory_limit="1g",
        cpu_quota=100000,
        timeout=60
    )
}


class TemplateManager:
    """
    Manages sandbox environment templates.
    
    Features:
    - Built-in templates
    - Custom template registration
    - Template validation
    - Template persistence
    """
    
    def __init__(self, custom_templates_path: Optional[str] = None):
        """
        Initialize template manager.
        
        Args:
            custom_templates_path: Path to custom templates JSON file
        """
        self.templates: Dict[str, SandboxTemplate] = {}
        self.custom_templates_path = custom_templates_path
        
        # Load built-in templates
        self._load_builtin_templates()
        
        # Load custom templates if path provided
        if custom_templates_path:
            self._load_custom_templates()
    
    def _load_builtin_templates(self):
        """Load built-in templates."""
        self.templates.update(BUILTIN_TEMPLATES)
        logger.info(f"Loaded {len(BUILTIN_TEMPLATES)} built-in templates")
    
    def _load_custom_templates(self):
        """Load custom templates from file."""
        if not self.custom_templates_path:
            return
        
        try:
            import os
            if os.path.exists(self.custom_templates_path):
                with open(self.custom_templates_path, 'r') as f:
                    data = json.load(f)
                
                for name, template_data in data.items():
                    template = SandboxTemplate.from_dict(template_data)
                    self.templates[name] = template
                
                logger.info(f"Loaded {len(data)} custom templates")
        except Exception as e:
            logger.error(f"Failed to load custom templates: {e}")
    
    def get_template(self, name: str) -> Optional[SandboxTemplate]:
        """
        Get template by name.
        
        Args:
            name: Template name
        
        Returns:
            Template or None if not found
        """
        return self.templates.get(name)
    
    def list_templates(self) -> List[Dict[str, Any]]:
        """
        List all available templates.
        
        Returns:
            List of template info dictionaries
        """
        return [
            {
                "name": t.name,
                "description": t.description,
                "base_image": t.base_image,
                "memory_limit": t.memory_limit,
                "cpu_quota": t.cpu_quota,
                "timeout": t.timeout,
                "network_enabled": t.network_enabled,
                "package_count": len(t.packages)
            }
            for t in self.templates.values()
        ]
    
    def register_template(
        self,
        template: SandboxTemplate,
        persist: bool = False
    ) -> bool:
        """
        Register a custom template.
        
        Args:
            template: Template to register
            persist: Whether to save to disk
        
        Returns:
            True if successful
        """
        try:
            errors = self.validate_template(template)
            if errors:
                raise ValueError("; ".join(errors))

            self.templates[template.name] = template
            
            if persist and self.custom_templates_path:
                self._save_custom_templates()
            
            logger.info(f"Registered template: {template.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register template: {e}")
            return False
    
    def unregister_template(self, name: str, persist: bool = False) -> bool:
        """
        Unregister a template.
        
        Args:
            name: Template name
            persist: Whether to save changes to disk
        
        Returns:
            True if successful
        """
        if name not in self.templates:
            return False
        
        # Don't allow removing built-in templates
        if name in BUILTIN_TEMPLATES:
            logger.warning(f"Cannot unregister built-in template: {name}")
            return False
        
        del self.templates[name]
        
        if persist and self.custom_templates_path:
            self._save_custom_templates()
        
        logger.info(f"Unregistered template: {name}")
        return True
    
    def _save_custom_templates(self):
        """Save custom templates to file."""
        if not self.custom_templates_path:
            return
        
        try:
            # Only save non-built-in templates
            custom = {
                name: template.to_dict()
                for name, template in self.templates.items()
                if name not in BUILTIN_TEMPLATES
            }
            
            with open(self.custom_templates_path, 'w') as f:
                json.dump(custom, f, indent=2)
            
            logger.info(f"Saved {len(custom)} custom templates")
            
        except Exception as e:
            logger.error(f"Failed to save custom templates: {e}")
    
    def validate_template(self, template: SandboxTemplate) -> List[str]:
        """
        Validate a template configuration.
        
        Args:
            template: Template to validate
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        if not template.name:
            errors.append("Template name is required")
        
        if not template.base_image:
            errors.append("Base image is required")
        
        # Validate memory limit format
        import re
        if not re.match(r'^\d+[mgMG]$', template.memory_limit):
            errors.append(f"Invalid memory limit format: {template.memory_limit}")
        else:
            memory_amount = int(template.memory_limit[:-1])
            if memory_amount <= 0:
                errors.append("Memory limit must be greater than 0")

        # Validate timeout
        if template.timeout < 1 or template.timeout > 3600:
            errors.append(f"Timeout must be between 1 and 3600 seconds")

        if template.cpu_quota <= 0:
            errors.append("CPU quota must be greater than 0")
        
        return errors
    
    def get_sandbox_kwargs(self, template_name: str) -> Dict[str, Any]:
        """
        Get sandbox initialization kwargs from template.
        
        Args:
            template_name: Template name
        
        Returns:
            Kwargs dict for CodeSandbox initialization
        """
        template = self.get_template(template_name)
        
        if not template:
            logger.warning(f"Template not found: {template_name}, using default")
            template = BUILTIN_TEMPLATES["default"]
        
        return {
            "image": template.base_image,
            "memory_limit": template.memory_limit,
            "cpu_quota": template.cpu_quota,
            "timeout": template.timeout,
            "network_disabled": not template.network_enabled
        }


# Global template manager instance
template_manager = TemplateManager()


def get_template(name: str) -> Optional[SandboxTemplate]:
    """Get template by name (convenience function)."""
    return template_manager.get_template(name)


def list_templates() -> List[Dict[str, Any]]:
    """List all templates (convenience function)."""
    return template_manager.list_templates()
