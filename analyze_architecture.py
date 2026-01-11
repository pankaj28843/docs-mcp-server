#!/usr/bin/env python3
"""
Architecture analysis tool for docs-mcp-server.

Measures:
- Interface complexity vs functionality ratio
- Module depth analysis
- Anti-pattern detection (classitis, shallow modules)
- Dependency graph complexity

Usage:
    uv run python analyze_architecture.py
"""

import ast
import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple, Any
import json


@dataclass
class ClassMetrics:
    """Metrics for a single class."""
    name: str
    file_path: str
    line_count: int
    method_count: int
    public_methods: int
    private_methods: int
    pass_through_methods: int
    business_logic_lines: int
    interface_complexity: int
    functionality_ratio: float


@dataclass
class ModuleMetrics:
    """Metrics for a module."""
    name: str
    file_path: str
    classes: List[ClassMetrics]
    total_lines: int
    interface_methods: int
    implementation_lines: int
    depth_score: float


@dataclass
class ArchitectureAnalysis:
    """Complete architecture analysis results."""
    modules: List[ModuleMetrics]
    total_classes: int
    shallow_modules: List[str]
    classitis_indicators: List[str]
    pass_through_violations: List[str]
    interface_proliferation: List[str]
    overall_depth_score: float
    anti_patterns_count: int


class ArchitectureAnalyzer:
    """Analyzes codebase architecture for anti-patterns."""
    
    def __init__(self, src_path: str = "src/docs_mcp_server"):
        self.src_path = Path(src_path)
        self.modules = {}
        self.classes = {}
    
    def analyze_class(self, node: ast.ClassDef, file_path: str, source_lines: List[str]) -> ClassMetrics:
        """Analyze a single class for metrics."""
        methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
        
        public_methods = [m for m in methods if not m.name.startswith('_')]
        private_methods = [m for m in methods if m.name.startswith('_') and not m.name.startswith('__')]
        
        # Count pass-through methods (methods that just delegate)
        pass_through_count = 0
        business_logic_lines = 0
        
        for method in methods:
            method_lines = method.end_lineno - method.lineno + 1
            method_source = '\n'.join(source_lines[method.lineno-1:method.end_lineno])
            
            # Simple heuristic: if method is short and contains 'return self.' or similar delegation
            if (method_lines <= 3 and 
                ('return self.' in method_source or 
                 'return super().' in method_source or
                 method_source.count('return') == 1)):
                pass_through_count += 1
            else:
                business_logic_lines += method_lines
        
        # Calculate interface complexity (public methods + properties)
        interface_complexity = len(public_methods)
        
        # Calculate functionality ratio (business logic / interface complexity)
        functionality_ratio = business_logic_lines / max(interface_complexity, 1)
        
        return ClassMetrics(
            name=node.name,
            file_path=file_path,
            line_count=node.end_lineno - node.lineno + 1,
            method_count=len(methods),
            public_methods=len(public_methods),
            private_methods=len(private_methods),
            pass_through_methods=pass_through_count,
            business_logic_lines=business_logic_lines,
            interface_complexity=interface_complexity,
            functionality_ratio=functionality_ratio
        )
    
    def analyze_file(self, file_path: Path) -> List[ClassMetrics]:
        """Analyze a single Python file."""
        try:
            source = file_path.read_text(encoding='utf-8')
            source_lines = source.split('\n')
            tree = ast.parse(source)
            
            classes = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_metrics = self.analyze_class(node, str(file_path), source_lines)
                    classes.append(class_metrics)
            
            return classes
        except Exception as e:
            print(f"⚠️  Error analyzing {file_path}: {e}")
            return []
    
    def analyze_module(self, module_path: Path) -> ModuleMetrics:
        """Analyze a module (directory or file)."""
        if module_path.is_file() and module_path.suffix == '.py':
            classes = self.analyze_file(module_path)
            total_lines = len(module_path.read_text().split('\n'))
        else:
            classes = []
            total_lines = 0
            for py_file in module_path.rglob('*.py'):
                if '__pycache__' not in str(py_file):
                    file_classes = self.analyze_file(py_file)
                    classes.extend(file_classes)
                    total_lines += len(py_file.read_text().split('\n'))
        
        # Calculate module metrics
        interface_methods = sum(c.public_methods for c in classes)
        implementation_lines = sum(c.business_logic_lines for c in classes)
        
        # Depth score: implementation lines / interface methods
        depth_score = implementation_lines / max(interface_methods, 1)
        
        return ModuleMetrics(
            name=module_path.name,
            file_path=str(module_path),
            classes=classes,
            total_lines=total_lines,
            interface_methods=interface_methods,
            implementation_lines=implementation_lines,
            depth_score=depth_score
        )
    
    def detect_anti_patterns(self, modules: List[ModuleMetrics]) -> Tuple[List[str], List[str], List[str], List[str]]:
        """Detect architecture anti-patterns."""
        shallow_modules = []
        classitis_indicators = []
        pass_through_violations = []
        interface_proliferation = []
        
        all_classes = []
        for module in modules:
            all_classes.extend(module.classes)
        
        # 1. Shallow modules (depth score < 5)
        for module in modules:
            if module.depth_score < 5 and module.interface_methods > 0:
                shallow_modules.append(f"{module.name} (depth: {module.depth_score:.1f})")
        
        # 2. Classitis (many small classes)
        small_classes = [c for c in all_classes if c.line_count < 30 and c.method_count < 5]
        if len(small_classes) > 5:
            classitis_indicators.append(f"{len(small_classes)} classes with <30 lines and <5 methods")
        
        # 3. Pass-through violations (>30% pass-through methods)
        for cls in all_classes:
            if cls.method_count > 0:
                pass_through_ratio = cls.pass_through_methods / cls.method_count
                if pass_through_ratio > 0.3:
                    pass_through_violations.append(f"{cls.name} ({pass_through_ratio:.1%} pass-through)")
        
        # 4. Interface proliferation (too many public methods per class)
        for cls in all_classes:
            if cls.public_methods > 10:
                interface_proliferation.append(f"{cls.name} ({cls.public_methods} public methods)")
        
        return shallow_modules, classitis_indicators, pass_through_violations, interface_proliferation
    
    def analyze_codebase(self) -> ArchitectureAnalysis:
        """Analyze the entire codebase."""
        print(f"🔍 Analyzing architecture in: {self.src_path}")
        
        modules = []
        
        # Analyze main modules
        for item in self.src_path.iterdir():
            if item.name.startswith('.') or item.name == '__pycache__':
                continue
            
            if item.is_dir() or (item.is_file() and item.suffix == '.py'):
                module_metrics = self.analyze_module(item)
                if module_metrics.classes:  # Only include modules with classes
                    modules.append(module_metrics)
        
        # Detect anti-patterns
        shallow_modules, classitis_indicators, pass_through_violations, interface_proliferation = \
            self.detect_anti_patterns(modules)
        
        # Calculate overall metrics
        total_classes = sum(len(m.classes) for m in modules)
        overall_depth_score = sum(m.depth_score * len(m.classes) for m in modules) / max(total_classes, 1)
        
        anti_patterns_count = (len(shallow_modules) + len(classitis_indicators) + 
                             len(pass_through_violations) + len(interface_proliferation))
        
        return ArchitectureAnalysis(
            modules=modules,
            total_classes=total_classes,
            shallow_modules=shallow_modules,
            classitis_indicators=classitis_indicators,
            pass_through_violations=pass_through_violations,
            interface_proliferation=interface_proliferation,
            overall_depth_score=overall_depth_score,
            anti_patterns_count=anti_patterns_count
        )
    
    def print_analysis(self, analysis: ArchitectureAnalysis):
        """Print architecture analysis results."""
        print("\n" + "="*70)
        print("🏗️  ARCHITECTURE ANALYSIS REPORT")
        print("="*70)
        
        print(f"\n📊 Overall Metrics:")
        print(f"   Total Modules: {len(analysis.modules)}")
        print(f"   Total Classes: {analysis.total_classes}")
        print(f"   Overall Depth Score: {analysis.overall_depth_score:.1f}")
        print(f"   Anti-patterns Found: {analysis.anti_patterns_count}")
        
        print(f"\n📋 Module Analysis:")
        for module in sorted(analysis.modules, key=lambda m: m.depth_score):
            print(f"   {module.name:25} | Classes: {len(module.classes):2} | Depth: {module.depth_score:5.1f} | Lines: {module.total_lines:4}")
        
        # Anti-patterns section
        if analysis.anti_patterns_count > 0:
            print(f"\n🚨 ANTI-PATTERNS DETECTED:")
            
            if analysis.shallow_modules:
                print(f"\n   ❌ Shallow Modules (depth < 5):")
                for item in analysis.shallow_modules:
                    print(f"      • {item}")
            
            if analysis.classitis_indicators:
                print(f"\n   ❌ Classitis Syndrome:")
                for item in analysis.classitis_indicators:
                    print(f"      • {item}")
            
            if analysis.pass_through_violations:
                print(f"\n   ❌ Pass-through Violations (>30% delegation):")
                for item in analysis.pass_through_violations:
                    print(f"      • {item}")
            
            if analysis.interface_proliferation:
                print(f"\n   ❌ Interface Proliferation (>10 public methods):")
                for item in analysis.interface_proliferation:
                    print(f"      • {item}")
        else:
            print(f"\n✅ NO ANTI-PATTERNS DETECTED")
        
        # Recommendations
        print(f"\n💡 RECOMMENDATIONS:")
        
        if analysis.overall_depth_score < 10:
            print("   🎯 CRITICAL: Overall depth score too low - consolidate shallow modules")
        elif analysis.overall_depth_score < 20:
            print("   ⚠️  WARNING: Depth score could be improved - review module boundaries")
        else:
            print("   ✅ GOOD: Depth score indicates well-designed modules")
        
        if analysis.total_classes > 20:
            print("   🎯 CRITICAL: Too many classes - consider consolidation")
        elif analysis.total_classes > 10:
            print("   ⚠️  WARNING: High class count - review necessity of each class")
        else:
            print("   ✅ GOOD: Reasonable number of classes")
        
        if analysis.anti_patterns_count > 5:
            print("   🎯 CRITICAL: Multiple anti-patterns detected - major refactoring needed")
        elif analysis.anti_patterns_count > 0:
            print("   ⚠️  WARNING: Some anti-patterns detected - targeted refactoring recommended")
        else:
            print("   ✅ EXCELLENT: Clean architecture with no detected anti-patterns")


def main():
    """Main entry point."""
    analyzer = ArchitectureAnalyzer()
    
    if not analyzer.src_path.exists():
        print(f"❌ Source path not found: {analyzer.src_path}")
        sys.exit(1)
    
    try:
        analysis = analyzer.analyze_codebase()
        analyzer.print_analysis(analysis)
        
        # Save detailed results
        output_file = "architecture_analysis.json"
        output_data = {
            "timestamp": __import__("time").time(),
            "summary": {
                "total_modules": len(analysis.modules),
                "total_classes": analysis.total_classes,
                "overall_depth_score": analysis.overall_depth_score,
                "anti_patterns_count": analysis.anti_patterns_count
            },
            "modules": [
                {
                    "name": m.name,
                    "classes_count": len(m.classes),
                    "depth_score": m.depth_score,
                    "total_lines": m.total_lines,
                    "interface_methods": m.interface_methods,
                    "implementation_lines": m.implementation_lines
                }
                for m in analysis.modules
            ],
            "anti_patterns": {
                "shallow_modules": analysis.shallow_modules,
                "classitis_indicators": analysis.classitis_indicators,
                "pass_through_violations": analysis.pass_through_violations,
                "interface_proliferation": analysis.interface_proliferation
            }
        }
        
        Path(output_file).write_text(json.dumps(output_data, indent=2))
        print(f"\n💾 Detailed analysis saved to: {output_file}")
        
    except Exception as e:
        print(f"❌ Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
