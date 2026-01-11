#!/usr/bin/env python3
"""
Architecture analysis script for docs-mcp-server.

Measures interface complexity, module depth, and identifies architectural
anti-patterns as defined in Ousterhout's "A Philosophy of Software Design".
"""

import argparse
import ast
import json
import os
from pathlib import Path
from typing import Dict, List, Set, Tuple


class ArchitectureAnalyzer:
    """Analyze codebase architecture and measure complexity."""
    
    def __init__(self, src_path: str = "src/docs_mcp_server"):
        self.src_path = Path(src_path)
        self.modules = {}
        self.classes = {}
        self.functions = {}
        
    def analyze_file(self, file_path: Path) -> Dict:
        """Analyze a single Python file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            
            classes = []
            functions = []
            imports = []
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    classes.append({
                        "name": node.name,
                        "methods": [n.name for n in node.body if isinstance(n, ast.FunctionDef)],
                        "lines": node.end_lineno - node.lineno if hasattr(node, 'end_lineno') else 0,
                        "docstring": ast.get_docstring(node) or "",
                    })
                elif isinstance(node, ast.FunctionDef) and node.col_offset == 0:  # Top-level functions
                    functions.append({
                        "name": node.name,
                        "args": len(node.args.args),
                        "lines": node.end_lineno - node.lineno if hasattr(node, 'end_lineno') else 0,
                        "docstring": ast.get_docstring(node) or "",
                    })
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.Import):
                        imports.extend([alias.name for alias in node.names])
                    else:
                        imports.append(node.module or "")
            
            return {
                "file": str(file_path.relative_to(self.src_path)),
                "lines": len(content.splitlines()),
                "classes": classes,
                "functions": functions,
                "imports": imports,
            }
            
        except Exception as e:
            print(f"Error analyzing {file_path}: {e}")
            return {"file": str(file_path), "error": str(e)}
    
    def analyze_codebase(self) -> Dict:
        """Analyze entire codebase."""
        results = {
            "files": [],
            "summary": {
                "total_files": 0,
                "total_lines": 0,
                "total_classes": 0,
                "total_functions": 0,
            }
        }
        
        for py_file in self.src_path.rglob("*.py"):
            if py_file.name.startswith("__"):
                continue
                
            file_analysis = self.analyze_file(py_file)
            results["files"].append(file_analysis)
            
            if "error" not in file_analysis:
                results["summary"]["total_files"] += 1
                results["summary"]["total_lines"] += file_analysis["lines"]
                results["summary"]["total_classes"] += len(file_analysis["classes"])
                results["summary"]["total_functions"] += len(file_analysis["functions"])
        
        return results
    
    def measure_interface_complexity(self, analysis: Dict) -> Dict:
        """Measure interface complexity per Ousterhout Ch. 4."""
        
        interface_metrics = {}
        
        for file_data in analysis["files"]:
            if "error" in file_data:
                continue
                
            file_name = file_data["file"]
            
            # Count public methods/functions (interface)
            public_methods = 0
            total_methods = 0
            
            for class_data in file_data["classes"]:
                for method in class_data["methods"]:
                    total_methods += 1
                    if not method.startswith("_"):
                        public_methods += 1
            
            for func_data in file_data["functions"]:
                total_methods += 1
                if not func_data["name"].startswith("_"):
                    public_methods += 1
            
            # Calculate interface complexity ratio
            if total_methods > 0:
                interface_ratio = public_methods / total_methods
                complexity_score = public_methods  # Simple metric: more public methods = more complex
                
                interface_metrics[file_name] = {
                    "public_methods": public_methods,
                    "total_methods": total_methods,
                    "interface_ratio": interface_ratio,
                    "complexity_score": complexity_score,
                    "lines_of_code": file_data["lines"],
                    "functionality_to_interface_ratio": file_data["lines"] / max(public_methods, 1),
                }
        
        return interface_metrics
    
    def identify_shallow_modules(self, interface_metrics: Dict) -> List[Dict]:
        """Identify shallow modules (high interface complexity, low functionality)."""
        
        shallow_modules = []
        
        for module, metrics in interface_metrics.items():
            # Ousterhout's criteria for shallow modules:
            # 1. High interface complexity (many public methods)
            # 2. Low functionality per interface element
            
            functionality_ratio = metrics["functionality_to_interface_ratio"]
            
            # Thresholds based on Ousterhout's principles
            is_shallow = (
                metrics["public_methods"] > 5 and  # Many public methods
                functionality_ratio < 10  # Less than 10 lines per public method
            )
            
            if is_shallow:
                shallow_modules.append({
                    "module": module,
                    "public_methods": metrics["public_methods"],
                    "lines_per_method": functionality_ratio,
                    "complexity_score": metrics["complexity_score"],
                    "assessment": "SHALLOW - High interface complexity, low functionality"
                })
        
        return shallow_modules
    
    def identify_pass_through_methods(self, analysis: Dict) -> List[Dict]:
        """Identify potential pass-through methods (anti-pattern)."""
        
        # This is a simplified heuristic - would need more sophisticated AST analysis
        # for complete detection
        
        pass_through_candidates = []
        
        for file_data in analysis["files"]:
            if "error" in file_data:
                continue
                
            for class_data in file_data["classes"]:
                if len(class_data["methods"]) > 3:  # Only analyze classes with multiple methods
                    
                    # Heuristic: classes with many short methods might have pass-through
                    avg_method_lines = class_data["lines"] / max(len(class_data["methods"]), 1)
                    
                    if avg_method_lines < 5:  # Very short methods on average
                        pass_through_candidates.append({
                            "file": file_data["file"],
                            "class": class_data["name"],
                            "method_count": len(class_data["methods"]),
                            "avg_lines_per_method": avg_method_lines,
                            "total_lines": class_data["lines"],
                            "assessment": "POTENTIAL PASS-THROUGH - Many short methods"
                        })
        
        return pass_through_candidates
    
    def detect_classitis(self, analysis: Dict) -> Dict:
        """Detect classitis anti-pattern (too many small classes)."""
        
        small_classes = []
        class_sizes = []
        
        for file_data in analysis["files"]:
            if "error" in file_data:
                continue
                
            for class_data in file_data["classes"]:
                class_sizes.append(class_data["lines"])
                
                # Small class heuristic: < 20 lines and < 3 methods
                if class_data["lines"] < 20 and len(class_data["methods"]) < 3:
                    small_classes.append({
                        "file": file_data["file"],
                        "class": class_data["name"],
                        "lines": class_data["lines"],
                        "methods": len(class_data["methods"]),
                        "assessment": "SMALL CLASS - Potential classitis"
                    })
        
        avg_class_size = sum(class_sizes) / len(class_sizes) if class_sizes else 0
        
        return {
            "small_classes": small_classes,
            "total_classes": len(class_sizes),
            "small_class_count": len(small_classes),
            "small_class_percentage": len(small_classes) / len(class_sizes) * 100 if class_sizes else 0,
            "average_class_size": avg_class_size,
            "classitis_risk": "HIGH" if len(small_classes) / len(class_sizes) > 0.5 else "LOW" if class_sizes else "NONE"
        }
    
    def generate_architecture_report(self) -> Dict:
        """Generate comprehensive architecture analysis report."""
        
        print("🔍 Analyzing codebase architecture...")
        analysis = self.analyze_codebase()
        
        print("📊 Measuring interface complexity...")
        interface_metrics = self.measure_interface_complexity(analysis)
        
        print("🕳️  Identifying shallow modules...")
        shallow_modules = self.identify_shallow_modules(interface_metrics)
        
        print("🔄 Detecting pass-through methods...")
        pass_through_methods = self.identify_pass_through_methods(analysis)
        
        print("🏭 Analyzing classitis patterns...")
        classitis_analysis = self.detect_classitis(analysis)
        
        return {
            "summary": analysis["summary"],
            "interface_complexity": interface_metrics,
            "architectural_issues": {
                "shallow_modules": shallow_modules,
                "pass_through_methods": pass_through_methods,
                "classitis_analysis": classitis_analysis,
            },
            "recommendations": self.generate_recommendations(
                shallow_modules, pass_through_methods, classitis_analysis
            )
        }
    
    def generate_recommendations(self, shallow_modules, pass_through_methods, classitis_analysis) -> List[str]:
        """Generate architecture improvement recommendations."""
        
        recommendations = []
        
        if shallow_modules:
            recommendations.append(
                f"🔧 CONSOLIDATE SHALLOW MODULES: {len(shallow_modules)} modules have high interface "
                f"complexity but low functionality. Consider merging related functionality."
            )
        
        if pass_through_methods:
            recommendations.append(
                f"🔧 ELIMINATE PASS-THROUGH METHODS: {len(pass_through_methods)} classes may contain "
                f"pass-through methods. Consider direct delegation or interface redesign."
            )
        
        if classitis_analysis["classitis_risk"] == "HIGH":
            recommendations.append(
                f"🔧 REDUCE CLASSITIS: {classitis_analysis['small_class_percentage']:.1f}% of classes "
                f"are very small. Consider consolidating related classes into deeper modules."
            )
        
        if not recommendations:
            recommendations.append("✅ ARCHITECTURE LOOKS GOOD: No major anti-patterns detected.")
        
        return recommendations


def main():
    parser = argparse.ArgumentParser(description="Analyze docs-mcp-server architecture")
    parser.add_argument("--src", default="src/docs_mcp_server", help="Source code path")
    parser.add_argument("--output", help="Output JSON file for detailed results")
    
    args = parser.parse_args()
    
    analyzer = ArchitectureAnalyzer(args.src)
    report = analyzer.generate_architecture_report()
    
    print("\n" + "="*60)
    print("📋 ARCHITECTURE ANALYSIS REPORT")
    print("="*60)
    
    # Summary
    summary = report["summary"]
    print(f"\n📊 Codebase Summary:")
    print(f"   Files:     {summary['total_files']}")
    print(f"   Lines:     {summary['total_lines']}")
    print(f"   Classes:   {summary['total_classes']}")
    print(f"   Functions: {summary['total_functions']}")
    
    # Interface Complexity
    print(f"\n🔌 Interface Complexity Analysis:")
    interface_metrics = report["interface_complexity"]
    
    if interface_metrics:
        avg_complexity = sum(m["complexity_score"] for m in interface_metrics.values()) / len(interface_metrics)
        avg_functionality_ratio = sum(m["functionality_to_interface_ratio"] for m in interface_metrics.values()) / len(interface_metrics)
        
        print(f"   Average Interface Complexity: {avg_complexity:.1f}")
        print(f"   Average Functionality Ratio:  {avg_functionality_ratio:.1f} lines/method")
        
        # Show most complex modules
        sorted_modules = sorted(
            interface_metrics.items(), 
            key=lambda x: x[1]["complexity_score"], 
            reverse=True
        )[:5]
        
        print(f"\n   Most Complex Modules:")
        for module, metrics in sorted_modules:
            print(f"     {module}: {metrics['complexity_score']} public methods, "
                  f"{metrics['functionality_to_interface_ratio']:.1f} lines/method")
    
    # Architectural Issues
    issues = report["architectural_issues"]
    
    print(f"\n⚠️  Architectural Issues:")
    print(f"   Shallow Modules:      {len(issues['shallow_modules'])}")
    print(f"   Pass-through Methods: {len(issues['pass_through_methods'])}")
    print(f"   Classitis Risk:       {issues['classitis_analysis']['classitis_risk']}")
    
    if issues["shallow_modules"]:
        print(f"\n   🕳️  Shallow Modules:")
        for module in issues["shallow_modules"][:3]:  # Show top 3
            print(f"     {module['module']}: {module['public_methods']} methods, "
                  f"{module['lines_per_method']:.1f} lines/method")
    
    if issues["classitis_analysis"]["small_classes"]:
        print(f"\n   🏭 Small Classes ({issues['classitis_analysis']['small_class_percentage']:.1f}%):")
        for cls in issues["classitis_analysis"]["small_classes"][:3]:  # Show top 3
            print(f"     {cls['file']}::{cls['class']}: {cls['lines']} lines, {cls['methods']} methods")
    
    # Recommendations
    print(f"\n💡 Recommendations:")
    for rec in report["recommendations"]:
        print(f"   {rec}")
    
    # Save detailed results
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\n📁 Detailed results saved to: {args.output}")
    
    print("\n" + "="*60)


if __name__ == "__main__":
    main()
