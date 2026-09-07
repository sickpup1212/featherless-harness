# local_agent/toolkit/code_reader.py
import ast
import re
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field
from pathlib import Path
from toolkit.filesystem import FileNode, ProjectExplorer

@dataclass
class CodeSymbol:
    """Represents a symbol (function, class, variable) in code."""
    name: str
    kind: str  # 'function', 'class', 'variable', 'import', 'constant'
    start_line: int
    end_line: int
    docstring: Optional[str] = None
    parameters: List[Dict] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    base_classes: List[str] = field(default_factory=list)
    return_type: Optional[str] = None
    is_async: bool = False


@dataclass
class CodeChunk:
    """A meaningful chunk of code with metadata."""
    file_path: Path
    start_line: int
    end_line: int
    content: str
    symbol: Optional[CodeSymbol] = None
    chunk_type: str = "general"  # 'function', 'class', 'imports', 'general'


class LanguageDetector:
    """Detect programming language from file extension and content."""
    
    EXTENSION_MAP = {
        '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
        '.jsx': 'javascript', '.tsx': 'typescript', '.rb': 'ruby',
        '.go': 'go', '.rs': 'rust', '.java': 'java', '.c': 'c',
        '.cpp': 'cpp', '.h': 'c', '.hpp': 'cpp', '.cs': 'csharp',
        '.swift': 'swift', '.kt': 'kotlin', '.scala': 'scala',
        '.php': 'php', '.lua': 'lua', '.pl': 'perl', '.r': 'r',
        '.yaml': 'yaml', '.yml': 'yaml', '.json': 'json', '.toml': 'toml',
        '.xml': 'xml', '.html': 'html', '.css': 'css', '.scss': 'scss',
        '.sql': 'sql', '.sh': 'shell', '.bash': 'shell', '.zsh': 'shell',
        '.md': 'markdown', '.txt': 'text'
    }
    
    @classmethod
    def detect(cls, file_path: Path) -> str:
        """Detect language from file extension."""
        return cls.EXTENSION_MAP.get(file_path.suffix.lower(), 'unknown')


class PythonCodeAnalyzer(ast.NodeVisitor):
    """Analyze Python code using AST."""
    
    def __init__(self):
        self.symbols: List[CodeSymbol] = []
        self.current_function: Optional[ast.FunctionDef] = None
        self.current_class: Optional[ast.ClassDef] = None
    
    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._analyze_function(node)
        self.generic_visit(node)
    
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._analyze_function(node, is_async=True)
        self.generic_visit(node)
    
    def visit_ClassDef(self, node: ast.ClassDef):
        self._analyze_class(node)
        self.generic_visit(node)
    
    def _analyze_function(self, node: ast.FunctionDef, is_async: bool = False):
        params = []
        for arg in node.args.args:
            param_info = {
                'name': arg.arg,
                'annotation': ast.unparse(arg.annotation) if arg.annotation else None
            }
            params.append(param_info)
        
        # Handle *args and **kwargs
        if node.args.vararg:
            params.append({'name': f"*{node.args.vararg.arg}", 'annotation': 'args'})
        if node.args.kwarg:
            params.append({'name': f"**{node.args.kwarg.arg}", 'annotation': 'kwargs'})
        
        # Get return type
        returns = ast.unparse(node.returns) if node.returns else None
        
        # Get docstring
        docstring = ast.get_docstring(node)
        
        # Get decorators
        decorators = [ast.unparse(d) for d in node.decorator_list]
        
        symbol = CodeSymbol(
            name=node.name,
            kind='function',
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno + 1,
            docstring=docstring,
            parameters=params,
            decorators=decorators,
            return_type=returns,
            is_async=is_async
        )
        self.symbols.append(symbol)
    
    def _analyze_class(self, node: ast.ClassDef):
        bases = [ast.unparse(base) for base in node.bases]
        decorator_list = [ast.unparse(d) for d in node.decorator_list]
        
        symbol = CodeSymbol(
            name=node.name,
            kind='class',
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno + 1,
            docstring=ast.get_docstring(node),
            base_classes=bases,
            decorators=decorator_list
        )
        self.symbols.append(symbol)


class CodeReader:
    """Read and understand code files with context-aware chunking."""
    
    # Characters per chunk for context windows (rough estimate)
    CHUNK_SIZE_LINES = 150
    MAX_FILE_SIZE_LINES = 2000  # Files larger than this need chunking
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.analyzers = {
            'python': PythonCodeAnalyzer()
        }
    
    def read_file(self, file_path: Path, 
                  start_line: Optional[int] = None,
                  end_line: Optional[int] = None,
                  include_line_numbers: bool = False) -> str:
        """Read a file with optional line range."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            
            if start_line:
                start_line = max(0, start_line - 1)
            else:
                start_line = 0
            
            if end_line:
                end_line = min(len(lines), end_line)
            else:
                end_line = len(lines)
            
            selected_lines = lines[start_line:end_line]
            
            if include_line_numbers:
                return "".join(
                    f"{i + start_line + 1:6d} | {line}" 
                    for i, line in enumerate(selected_lines)
                )
            return "".join(selected_lines)
        except (IOError, OSError) as e:
            return f"# Error reading file: {e}"
    
    def analyze_file(self, file_path: Path) -> List[CodeSymbol]:
        """Analyze a file and extract symbols."""
        lang = LanguageDetector.detect(file_path)
        
        if lang not in self.analyzers:
            return []
        
        analyzer = self.analyzers[lang]
        try:
            content = self.read_file(file_path)
            tree = ast.parse(content)
            analyzer.visit(tree)
            return analyzer.symbols
        except SyntaxError:
            return []
    
    def get_file_symbols(self, file_path: Path) -> str:
        """Get a formatted string of all symbols in a file."""
        symbols = self.analyze_file(file_path)
        
        if not symbols:
            return f"# No symbols found in {file_path.name}"
        
        lines = [f"# Symbols in {file_path.name}:"]
        for sym in symbols:
            kind_icon = {
                'function': '⚡',
                'class': '📦',
                'variable': '📌',
                'import': '📥',
                'constant': '🔒'
            }.get(sym.kind, '•')
            
            sig_parts = []
            if sym.kind == 'function':
                params = ", ".join(
                    f"{p['name']}: {p['annotation']}" 
                    for p in sym.parameters 
                    if p['annotation']
                ) or ", ".join(p['name'] for p in sym.parameters)
                sig_parts.append(f"({params})")
                if sym.return_type:
                    sig_parts.append(f"-> {sym.return_type}")
            elif sym.kind == 'class':
                if sym.base_classes:
                    sig_parts.append(f"({', '.join(sym.base_classes)})")
            
            sig = "".join(sig_parts)
            lines.append(f"{kind_icon} {sym.name}{sig}")
            
            if sym.docstring:
                # Truncate long docstrings
                doc = sym.docstring[:100].replace('\n', ' ')
                lines.append(f"   📝 {doc}...")
            
            lines.append(f"   Lines {sym.start_line}-{sym.end_line}")
            lines.append("")
        
        return "\n".join(lines)
    
    def read_with_context(self, file_path: Path, 
                          focus_line: int,
                          context_lines: int = 10) -> str:
        """Read a file with context around a specific line."""
        total_lines = sum(1 for _ in open(file_path, 'r', errors='replace'))
        
        start = max(0, focus_line - context_lines - 1)
        end = min(total_lines, focus_line + context_lines)
        
        content = self.read_file(file_path, start + 1, end, include_line_numbers=True)
        
        # Add markers
        context_start_line = start + 1
        context_end_line = end
        
        lines = [
            f"### {file_path.name} (lines {context_start_line}-{context_end_line})",
            f"### Focus: line {focus_line}",
            "```",
            content,
            "```"
        ]
        return "\n".join(lines)
    
    def create_chunks(self, file_path: Path) -> List[CodeChunk]:
        """Split a large file into meaningful chunks."""
        symbols = self.analyze_file(file_path)
        content_lines = self.read_file(file_path).splitlines()
        total_lines = len(content_lines)
        
        chunks = []
        
        if total_lines <= self.CHUNK_SIZE_LINES:
            # Small file - single chunk
            chunks.append(CodeChunk(
                file_path=file_path,
                start_line=1,
                end_line=total_lines,
                content=self.read_file(file_path),
                chunk_type='general'
            ))
        else:
            # Large file - create chunks around symbols
            for sym in symbols:
                chunk_start = max(1, sym.start_line - 5)
                chunk_end = min(total_lines, sym.end_line + 5)
                
                chunks.append(CodeChunk(
                    file_path=file_path,
                    start_line=chunk_start,
                    end_line=chunk_end,
                    content=self.read_file(file_path, chunk_start, chunk_end),
                    symbol=sym,
                    chunk_type=sym.kind
                ))
            
            # Add import section if exists
            import_end = 0
            for i, line in enumerate(content_lines):
                if line.startswith('import ') or line.startswith('from '):
                    import_end = i + 1
                elif import_end > 0 and line.strip() and not line.startswith('#'):
                    break
            
            if import_end > 0:
                chunks.append(CodeChunk(
                    file_path=file_path,
                    start_line=1,
                    end_line=min(import_end + 5, total_lines),
                    content=self.read_file(file_path, 1, import_end + 5),
                    chunk_type='imports'
                ))
        
        return chunks
    
    def get_file_overview(self, file_path: Path) -> str:
        """Get a comprehensive overview of a file."""
        lang = LanguageDetector.detect(file_path)
        symbols = self.analyze_file(file_path)
        
        overview = [
            f"## File: {file_path.name}",
            f"- Language: {lang}",
            f"- Size: {file_path.stat().st_size} bytes",
            f"- Lines: {sum(1 for _ in open(file_path, 'r', errors='replace'))}",
            ""
        ]
        
        if symbols:
            overview.append("### Symbols:")
            overview.append(self.get_file_symbols(file_path))
        
        # First 30 lines as preview
        preview_lines = self.read_file(file_path, 1, 30, include_line_numbers=True).split('\n')
        non_empty = [l for l in preview_lines if l.strip()]
        
        if non_empty:
            overview.extend([
                "",
                "### Preview (first non-empty lines):",
            ])
            for line in non_empty[:10]:
                overview.append(f"```\n{line}\n```")
        
        return "\n".join(overview)


class ProjectIndex:
    """Index all code in a project for efficient retrieval."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.explorer = ProjectExplorer(str(project_root))
        self.reader = CodeReader(project_root)
        self._symbol_index: Dict[str, Dict] = {}
        self._relationship_graph: Dict[str, Set[str]] = {}
    
    def build_index(self, file_extensions: Optional[List[str]] = None):
        """Build a complete index of the project."""
        if file_extensions is None:
            file_extensions = ['.py', '.js', '.ts', '.jsx', '.tsx', '.rb', '.go', '.rs']
        
        tree = self.explorer.explore()
        self._index_files(tree, file_extensions)
        self._index_relationships()
    
    def _index_files(self, node: FileNode, extensions: List[str]):
        """Recursively index files."""
        if not node.is_dir:
            if node.path.suffix in extensions:
                symbols = self.reader.analyze_file(node.path)
                for sym in symbols:
                    key = f"{node.path.relative_to(self.project_root)}:{sym.name}"
                    self._symbol_index[key] = {
                        'file': str(node.path.relative_to(self.project_root)),
                        'symbol': sym.__dict__
                    }
        elif node.children:
            for child in node.children:
                self._index_files(child, extensions)
    
    def _index_relationships(self):
        """Index relationships between files (imports, etc.)."""
        for file_key, info in self._symbol_index.items():
            file_path = self.project_root / info['file']
            content = self.reader.read_file(file_path)
            
            # Find imports/includes
            imports = self._find_imports(content, file_path)
            self._relationship_graph[file_key] = set(imports)
    
    def _find_imports(self, content: str, source_path: Path) -> List[str]:
        """Find imported modules/files in code."""
        imports = []
        
        # Python-style imports
        import_pattern = r'^(?:from|import)\s+([\w.]+)'
        for match in re.finditer(import_pattern, content, re.MULTILINE):
            module = match.group(1).split('.')[0]
            # Try to find corresponding file
            possible_paths = [
                self.project_root / f"{module}.py",
                self.project_root / module / "__init__.py",
            ]
            for pp in possible_paths:
                if pp.exists():
                    rel = str(pp.relative_to(self.project_root))
                    imports.append(rel)
        
        return imports
    
    def search_symbols(self, query: str) -> List[Dict]:
        """Search for symbols matching a query."""
        query = query.lower()
        results = []
        
        for key, info in self._symbol_index.items():
            sym = info['symbol']
            if (query in key.lower() or 
                query in sym['name'].lower() or
                (sym.get('docstring') and query in sym['docstring'].lower())):
                results.append(info)
        
        return sorted(results, key=lambda x: x['file'])
    
    def get_related_files(self, file_path: str) -> List[str]:
        """Get files related to a given file."""
        file_key = f"{file_path}:*"
        related = set()
        
        # Find all symbols from this file
        for key in self._symbol_index:
            if key.startswith(file_path):
                related.update(self._relationship_graph.get(key, set()))
        
        return list(related)
    
    def get_index_summary(self) -> str:
        """Get a summary of the project index."""
        files = set()
        symbols_by_type = {}
        
        for info in self._symbol_index.values():
            files.add(info['file'])
            sym_type = info['symbol']['kind']
            symbols_by_type[sym_type] = symbols_by_type.get(sym_type, 0) + 1
        
        summary = [
            f"## Project Index: {self.project_root.name}",
            f"- Total files indexed: {len(files)}",
            f"- Total symbols: {len(self._symbol_index)}",
            "",
            "### Symbols by type:",
        ]
        
        for sym_type, count in sorted(symbols_by_type.items()):
            summary.append(f"- {sym_type}: {count}")
        
        summary.extend([
            "",
            "### Files:",
        ])
        summary.extend(sorted(files))
        
        return "\n".join(summary)