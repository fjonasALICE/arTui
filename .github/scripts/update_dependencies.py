#!/usr/bin/env python3
"""
Script to update README.md with dependencies from pyproject.toml
"""

import re
import toml
from pathlib import Path


def parse_dependency(dep_string):
    """Parse a dependency string and return name and version constraint."""
    # Handle dependencies with extras like "textual[syntax]>=0.41.0"
    if '[' in dep_string:
        name_with_extra = dep_string.split('>=')[0].split('>')[0].split('==')[0].split('~=')[0].split('<')[0]
        name = name_with_extra.split('[')[0]
    else:
        name = dep_string.split('>=')[0].split('>')[0].split('==')[0].split('~=')[0].split('<')[0]
    
    return name.strip(), dep_string


def get_pypi_url(package_name):
    """Generate PyPI URL for a package."""
    return f"https://pypi.org/project/{package_name}/"


def create_dependencies_section(dependencies):
    """Create the dependencies section content."""
    lines = ["## Dependencies", ""]
    lines.append("This project depends on the following Python packages:")
    lines.append("")
    
    for dep_string in dependencies:
        name, full_spec = parse_dependency(dep_string)
        pypi_url = get_pypi_url(name)
        lines.append(f"- [{name}]({pypi_url}) - `{full_spec}`")
    
    lines.append("")
    return lines


def update_readme():
    """Update README.md with dependencies from pyproject.toml."""
    # Read pyproject.toml
    pyproject_path = Path("pyproject.toml")
    if not pyproject_path.exists():
        print("pyproject.toml not found!")
        return
    
    with open(pyproject_path, 'r') as f:
        pyproject_data = toml.load(f)
    
    # Extract dependencies
    dependencies = pyproject_data.get('project', {}).get('dependencies', [])
    if not dependencies:
        print("No dependencies found in pyproject.toml")
        return
    
    # Read README.md
    readme_path = Path("README.md")
    if not readme_path.exists():
        print("README.md not found!")
        return
    
    with open(readme_path, 'r') as f:
        readme_content = f.read()
    
    # Remove existing dependencies section if it exists
    # Look for ## Dependencies section and remove everything from there to the end
    # or to the next ## section
    pattern = r'\n## Dependencies.*?(?=\n## |\Z)'
    readme_content = re.sub(pattern, '', readme_content, flags=re.DOTALL)
    
    # Ensure README ends with a newline
    if not readme_content.endswith('\n'):
        readme_content += '\n'
    
    # Create new dependencies section
    deps_section = create_dependencies_section(dependencies)
    
    # Add dependencies section at the end
    updated_content = readme_content + '\n'.join(deps_section)
    
    # Write updated README
    with open(readme_path, 'w') as f:
        f.write(updated_content)
    
    print(f"Updated README.md with {len(dependencies)} dependencies")


if __name__ == "__main__":
    update_readme()
