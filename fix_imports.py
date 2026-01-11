#!/usr/bin/env python3
"""Fix import violations by moving imports to top of files."""

import re
from pathlib import Path

def fix_file_imports(file_path: Path):
    """Fix imports in a single file."""
    content = file_path.read_text()
    lines = content.split('\n')
    
    # Track imports to move to top
    imports_to_add = set()
    new_lines = []
    
    # Find existing imports section
    import_section_end = 0
    for i, line in enumerate(lines):
        if line.strip() and not (line.startswith('"""') or line.startswith("'''") or 
                                line.startswith('#') or line.startswith('from ') or 
                                line.startswith('import ') or line == '"""' or 
                                line == "'''" or line.startswith('__')):
            import_section_end = i
            break
    
    # Process lines
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Check for indented imports (inside functions/methods)
        if re.match(r'^\s+(from .+ import .+|import .+)', line):
            # Extract the import
            import_line = line.strip()
            if not import_line.endswith('# noqa: F401'):
                imports_to_add.add(import_line)
            # Skip this line (remove it)
            i += 1
            continue
        
        new_lines.append(line)
        i += 1
    
    # Add new imports after existing imports
    if imports_to_add:
        # Find where to insert imports
        insert_pos = import_section_end
        for i in range(len(new_lines)):
            if new_lines[i].startswith('from ') or new_lines[i].startswith('import '):
                insert_pos = i + 1
        
        # Insert new imports
        for imp in sorted(imports_to_add):
            new_lines.insert(insert_pos, imp)
            insert_pos += 1
    
    # Write back
    file_path.write_text('\n'.join(new_lines))

# Files to fix
files_to_fix = [
    "tests/unit/test_doc_fetcher_unit.py",
    "tests/unit/test_filesystem_unit_of_work.py", 
    "tests/unit/test_root_hub_unit.py",
    "tests/unit/test_search_bm25_engine.py",
    "tests/unit/test_search_code_analyzer.py",
    "tests/unit/test_sync_progress.py",
    "tests/unit/test_sync_progress_store.py",
    "tests/unit/test_sync_scheduler_extra.py",
    "tests/unit/test_sync_scheduler_unit.py",
    "tests/unit/test_tenant.py"
]

for file_path in files_to_fix:
    path = Path(file_path)
    if path.exists():
        print(f"Fixing {file_path}")
        fix_file_imports(path)
    else:
        print(f"File not found: {file_path}")
