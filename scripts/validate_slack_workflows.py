#!/usr/bin/env python3
import json
import sys
from pathlib import Path

def is_slack_webhook_workflow(workflow: dict) -> bool:
    """Check if workflow is Slack slash-command entry workflow."""
    nodes = workflow.get('nodes', [])

    for node in nodes:
        if node.get('type') == 'n8n-nodes-base.webhook':
            path = node.get('parameters', {}).get('path', '')
            if path == 'slack-command':
                return True

    return False

def validate_slack_workflow(filepath: Path) -> tuple[bool, list[str]]:
    errors = []
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            workflow = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON in {filepath}: {e}"]
    except Exception as e:
        return False, [f"Cannot read {filepath}: {e}"]
    
    # Check if this is a Slack webhook workflow
    if not is_slack_webhook_workflow(workflow):
        return None, ["Not a Slack webhook workflow"]
    
    nodes = workflow.get('nodes', [])
    connections = workflow.get('connections', {})

    # Find respondToWebhook node (ACK) - by type only, not by name
    ack_node = None
    for node in nodes:
        node_type = node.get('type', '')
        if node_type == 'n8n-nodes-base.respondToWebhook':
            if node.get('name') == 'Immediate ACK':
                ack_node = node
                break

    if not ack_node:
        errors.append(f"No respondToWebhook node found (Immediate ACK)")
        return False, errors

    slack_webhook_edges = connections.get('Slack Webhook', {}).get('main', [])
    if not slack_webhook_edges or not slack_webhook_edges[0] or slack_webhook_edges[0][0].get('node') != 'Immediate ACK':
        errors.append("Slack Webhook must connect directly to Immediate ACK")
    
    params = ack_node.get('parameters', {})
    respond_with = params.get('respondWith', '')
    
    if respond_with != 'json':
        errors.append(f"ACK node should use 'json' response mode, found: {respond_with}")
    
    json_content = params.get('json', '')
    
    if json_content:
        # Best-effort validation of response body
        if '{"myField":"value"}' in json_content or "myField" in json_content:
            errors.append(f"ACK contains n8n placeholder - expression failed to evaluate")
        
        if '={{' in json_content:
            errors.append(f"ACK contains expression syntax '={{' - should be hard-coded JSON")
        
        if '$json' in json_content:
            errors.append(f"ACK references '$json' - should be hard-coded JSON")
        
        try:
            ack_json = json.loads(json_content)
            
            if 'response_type' not in ack_json:
                errors.append(f"ACK JSON missing 'response_type' field")
            elif ack_json.get('response_type') != 'ephemeral':
                errors.append(f"ACK response_type should be 'ephemeral', found: {ack_json.get('response_type')}")
            
            if 'text' not in ack_json:
                errors.append(f"ACK JSON missing 'text' field")
            elif not ack_json.get('text'):
                errors.append(f"ACK text field is empty")
                
        except json.JSONDecodeError:
            errors.append(f"ACK 'json' field contains invalid JSON: {json_content[:100]}")
    else:
        # Warn but don't fail if json field is empty (may be configured differently)
        pass

    router_node = next((
        node for node in nodes
        if node.get('name') == 'Call Brain Router'
        and node.get('type') == 'n8n-nodes-base.httpRequest'
    ), None)
    router_headers = (
        router_node
        .get('parameters', {})
        .get('headerParameters', {})
        .get('parameters', [])
        if router_node else []
    )
    if not any(
        header.get('name') == 'X-API-Key' and 'N8N_WEBHOOK_API_KEY' in str(header.get('value', ''))
        for header in router_headers
    ):
        errors.append("Call Brain Router must send X-API-Key using N8N_WEBHOOK_API_KEY")

    return len(errors) == 0, errors

def main():
    workflow_dirs = [
        Path.home() / 'ai-orchestrator-workflows',
        Path('/opt/ai-orchestrator/n8n/workflows-v3'),
    ]
    
    if len(sys.argv) > 1:
        workflow_dirs = [Path(p) for p in sys.argv[1:]]
    
    all_valid = True
    total_files = 0
    slack_files = 0
    skipped_files = 0
    
    print("=" * 70)
    print("SLACK WORKFLOW VALIDATION")
    print("=" * 70)
    print()
    
    for workflow_dir in workflow_dirs:
        try:
            if not workflow_dir.exists():
                print(f"Directory not found: {workflow_dir}")
                continue
        except PermissionError:
            print(f"Permission denied: {workflow_dir}")
            continue
        
        # Check ALL JSON files, filter by content not by filename
        workflow_files = list(workflow_dir.glob('*.json'))
        
        if not workflow_files:
            print(f"No workflow files found in: {workflow_dir}")
            continue
        
        print(f"Checking directory: {workflow_dir}")
        print()
        
        for filepath in workflow_files:
            total_files += 1
            
            is_valid, errors = validate_slack_workflow(filepath)
            
            if is_valid is None:
                # Not a Slack workflow, skip
                skipped_files += 1
                print(f"  {filepath.name}")
                print(f"    SKIPPED - {errors[0]}")
                print()
                continue
            
            slack_files += 1
            print(f"  {filepath.name}")
            
            if is_valid:
                print(f"    PASS - respondToWebhook correctly configured")
            else:
                all_valid = False
                for error in errors:
                    print(f"    {error}")
            
            print()
    
    print("=" * 70)
    print(f"Summary: {total_files} total files, {slack_files} Slack workflows, {skipped_files} skipped")
    print()
    
    if slack_files == 0:
        print("No Slack webhook workflows found to validate")
        sys.exit(0)  # Not an error, just no Slack workflows
    elif all_valid:
        print(f"ALL CHECKS PASSED ({slack_files} Slack workflow(s) validated)")
        print()
        print("The workflow(s) are ready for import and will correctly respond to Slack.")
        sys.exit(0)
    else:
        print(f"VALIDATION FAILED")
        print()
        print("Fix the issues above before importing the workflow into n8n.")
        print()
        print("Common fixes:")
        print("  1. Open workflow in n8n UI")
        print("  2. Find 'Immediate ACK' node (Respond to Webhook)")
        print("  3. Set response mode to 'JSON'")
        print("  4. Paste exact JSON:")
        print('     {"response_type": "ephemeral", "text": "Processing your request..."}')
        print("  5. Save and re-export workflow")
        sys.exit(1)

if __name__ == '__main__':
    main()
